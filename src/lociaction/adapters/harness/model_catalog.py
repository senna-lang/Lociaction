"""Discover model IDs previously used by supported harnesses in one project.

The catalog is intentionally derived only from session logs stored on this
machine. It never calls a provider or guesses a vendor-wide, rapidly changing
model list. A returned ID is therefore a model the selected harness has used
for this project, not a claim that the account can still access it.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
