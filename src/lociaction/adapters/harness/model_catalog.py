"""Discover harness model IDs for distillation setup.

Project session logs supply history for every supported harness. For a harness
with a documented account-scoped catalog endpoint, the selected harness is
also queried at selection time. A live result is an availability claim for the
current account; history remains a clearly labelled offline fallback.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from lociaction.indexer import _load_raw_entries


@dataclass(frozen=True)
class HarnessModelCatalog:
    """One project-local harness and its recorded model IDs."""

    harness_id: str
    label: str
    client_id: str
    models: tuple[str, ...]


_HARNESS_DETAILS = {
    "claude": ("Claude Code", "claude-cli"),
    "codex": ("Codex", "codex-cli"),
    "omp-pi": ("Oh My Pi", "omp-cli"),
    "grok": ("Grok", "grok-cli"),
    "opencode": ("OpenCode", "opencode-cli"),
}


def discover_project_harness_models(root: Path) -> tuple[HarnessModelCatalog, ...]:
    """Return detected project harnesses with distinct model IDs from their logs."""
    from lociaction.adapters.harness.registry import detected_jsonl_sources

    catalogs: list[HarnessModelCatalog] = []
    for source in detected_jsonl_sources():
        details = _HARNESS_DETAILS[source.id]
        models: set[str] = set()
        sessions = source.list_sessions(root)
        for session in sessions:
            try:
                entries = _load_raw_entries(Path(session.primary_ref), last_ply_end=-1)
            except OSError:
                continue
            models.update(models_from_entries(source.id, entries))
        if sessions:
            label, client_id = details
            catalogs.append(
                HarnessModelCatalog(
                    harness_id=source.id,
                    label=label,
                    client_id=client_id,
                    models=tuple(sorted(models)),
                )
            )
    opencode = _discover_opencode_catalog(root)
    if opencode is not None:
        catalogs.append(opencode)
    return tuple(catalogs)


def _discover_opencode_catalog(root: Path) -> HarnessModelCatalog | None:
    """Read OpenCode's project-scoped model IDs from its read-only session DB."""
    from lociaction.paths import resolve_opencode_db_path

    db_path = resolve_opencode_db_path()
    if db_path is None:
        return None
    db_uri = f"file:{quote(str(db_path), safe='/')}?mode=ro"
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(db_uri, uri=True)
        project_ids = [
            row[0]
            for row in con.execute("SELECT id, worktree FROM project")
            if row[1] is not None
            and os.path.realpath(row[1]) == os.path.realpath(str(root))
        ]
        if not project_ids:
            return None
        placeholders = ",".join("?" * len(project_ids))
        session_ids = [
            row[0]
            for row in con.execute(
                f"SELECT id FROM session WHERE project_id IN ({placeholders})",
                project_ids,
            )
        ]
        if not session_ids:
            return None
        session_placeholders = ",".join("?" * len(session_ids))
        models: set[str] = set()
        for table in ("message", "part"):
            rows = con.execute(
                f"SELECT data FROM {table} WHERE session_id IN ({session_placeholders})",
                session_ids,
            )
            for (raw_data,) in rows:
                if not isinstance(raw_data, str):
                    continue
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue
                models.update(models_from_entries("opencode", [data]))
    except sqlite3.Error:
        return None
    finally:
        if con is not None:
            con.close()
    label, client_id = _HARNESS_DETAILS["opencode"]
    return HarnessModelCatalog(
        harness_id="opencode",
        label=label,
        client_id=client_id,
        models=tuple(sorted(models)),
    )


def models_from_entries(harness_id: str, entries: list[dict | None]) -> tuple[str, ...]:
    """Extract concrete model IDs from one harness's normalized JSONL records."""
    models: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for value in _model_values(harness_id, entry):
            if isinstance(value, str) and value.strip():
                models.add(value.strip())
    return tuple(sorted(models))


def _model_values(harness_id: str, entry: dict[str, Any]) -> tuple[Any, ...]:
    if harness_id == "claude":
        return (entry.get("model"), _mapping_value(entry.get("message"), "model"))
    if harness_id == "codex":
        return (_mapping_value(entry.get("payload"), "model"),)
    if harness_id == "omp-pi":
        return (_mapping_value(entry.get("message"), "model"),)
    if harness_id == "grok":
        params = entry.get("params")
        update = _mapping_value(params, "update")
        return (_mapping_value(params, "model"), _mapping_value(update, "model"))
    if harness_id == "opencode":
        model = entry.get("model")
        return (
            _mapping_value(model, "modelID"),
            entry.get("modelID"),
        )
    return ()


def _mapping_value(value: object, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


_CODEX_MODELS_URLS = (
    "https://chatgpt.com/backend-api/codex/models",
    "https://chatgpt.com/backend-api/models",
)


def discover_available_harness_models(harness_id: str) -> tuple[str, ...] | None:
    """Return the selected harness's current account-scoped model IDs.

    ``None`` means that this harness has no supported live discovery path or
    that the account could not be queried. An empty tuple is a successful,
    authoritative response with no selectable models.
    """
    if harness_id == "codex":
        return _discover_codex_models()
    if harness_id == "grok":
        return _discover_grok_models()
    if harness_id == "opencode":
        return _discover_opencode_models()
    if harness_id == "omp-pi":
        return _discover_omp_models()
    return None


def _discover_codex_models() -> tuple[str, ...] | None:
    """Query the active Codex account's backend model catalog.

    This follows Codex's account-scoped ``/codex/models`` discovery protocol,
    rather than treating local session history as an availability catalog.
    Credentials stay in-process and are never logged.
    """
    tokens = _read_codex_tokens()
    if tokens is None:
        return None
    access_token, account_id = tokens
    headers = {
        "Authorization": f"Bearer {access_token}",
        "OpenAI-Beta": "responses=experimental",
        "originator": "omp",
        "accept": "application/json",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    version = _codex_client_version()
    if version:
        headers["version"] = version

    for url in _CODEX_MODELS_URLS:
        request_url = f"{url}?client_version={quote(version)}" if version else url
        try:
            with urlopen(Request(request_url, headers=headers), timeout=10) as response:
                payload = json.load(response)
        except (HTTPError, OSError, TimeoutError, URLError, json.JSONDecodeError):
            continue
        models = _codex_model_ids(payload)
        if models is not None:
            return models
    return None


def _discover_grok_models() -> tuple[str, ...] | None:
    """Use Grok's own account-aware ``models`` command."""
    output = _run_harness_model_command(["grok", "models"])
    if output is None:
        return None
    models: dict[str, None] = {}
    for line in output.splitlines():
        match = re.match(r"^\s*[-*]\s+(.+?)(?:\s+\(default\))?\s*$", line)
        if match:
            models.setdefault(match.group(1), None)
    return tuple(models)


def _discover_opencode_models() -> tuple[str, ...] | None:
    """Use OpenCode's configured-provider ``models`` command."""
    output = _run_harness_model_command(["opencode", "models"])
    if output is None:
        return None
    return tuple(
        dict.fromkeys(
            line
            for line in (line.strip() for line in output.splitlines())
            if line and "/" in line and not any(char.isspace() for char in line)
        )
    )


def _discover_omp_models() -> tuple[str, ...] | None:
    """Use OMP's resolved runtime registry in its stable JSON format."""
    output = _run_harness_model_command(["omp", "models", "--json"])
    if output is None:
        return None
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return None
    models: dict[str, None] = {}
    for entry in payload["models"]:
        if not isinstance(entry, dict):
            continue
        selector = entry.get("selector")
        if isinstance(selector, str) and selector.strip():
            models.setdefault(selector.strip(), None)
    return tuple(models)


def _run_harness_model_command(args: list[str]) -> str | None:
    """Run a harness-owned model lister without inspecting its credentials."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _read_codex_tokens() -> tuple[str, str | None] | None:
    """Read only the active Codex CLI OAuth token and account ID."""
    auth_path = Path.home() / ".codex" / "auth.json"
    try:
        payload = json.loads(auth_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        return None
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    return access_token, account_id if isinstance(account_id, str) else None


def _codex_client_version() -> str | None:
    """Use the installed Codex version for its server-side model gate."""
    codex = shutil.which("codex")
    if codex is None:
        return None
    try:
        result = subprocess.run(
            [codex, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return None
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", result.stdout)
    return match.group(1) if result.returncode == 0 and match else None


def _codex_model_ids(payload: object) -> tuple[str, ...] | None:
    """Extract visible server-advertised slugs, preserving server order."""
    if not isinstance(payload, dict):
        return None
    entries = payload.get("models", payload.get("data"))
    if not isinstance(entries, list):
        return None
    models: dict[str, None] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        visibility = entry.get("visibility")
        if isinstance(visibility, str) and visibility.lower() in {"hide", "hidden"}:
            continue
        model_id = entry.get("slug", entry.get("id"))
        if isinstance(model_id, str) and model_id.strip():
            models.setdefault(model_id.strip(), None)
    return tuple(models)
