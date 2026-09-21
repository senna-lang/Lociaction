"""Project-local harness and model selection for distillation setup."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import lociaction.adapters.harness.model_catalog as model_catalog
from lociaction.adapters.harness.model_catalog import (
    HarnessModelCatalog,
    discover_available_harness_models,
    models_from_entries,
)
from lociaction.adapters.model.types import ClientStatus, ModelClient
from lociaction.cli.distill_cmd import (
    _select_harness_model,
    prompt_client_selection,
)


def _prompts(values: list[str]) -> Iterator[str]:
    yield from values


def _accept_default(_prompt, default=None, **_kwargs):
    """Simulate pressing Enter: Click's `typer.prompt` returns `default` on empty input."""
    return default


def test_models_from_entries_reads_each_harness_model_field() -> None:
    """The catalog keeps only concrete model IDs emitted by each harness."""
    fixtures = Path(__file__).parent / "fixtures" / "harness_logs"
    codex_entries = [
        json.loads(line) for line in (fixtures / "codex.jsonl").read_text().splitlines()
    ]
    omp_entries = [
        json.loads(line)
        for line in (fixtures / "omp_pi.jsonl").read_text().splitlines()
    ]
    opencode_fixture = json.loads((fixtures / "opencode.json").read_text())
    opencode_entries = [message["data"] for message in opencode_fixture["messages"]]

    assert models_from_entries("codex", codex_entries) == ("gpt-5-codex",)
    assert models_from_entries("omp-pi", omp_entries) == ("claude-sonnet-5",)
    assert models_from_entries("opencode", opencode_entries) == ("claude-sonnet-5",)


def test_project_catalog_excludes_foreign_codex_rollouts(tmp_path, monkeypatch) -> None:
    """Codex's global rollout directory is scoped before exposing model history."""
    project_root = tmp_path / "project"
    foreign_root = tmp_path / "foreign"
    sessions_dir = tmp_path / "sessions"
    project_root.mkdir()
    foreign_root.mkdir()
    sessions_dir.mkdir()
    (sessions_dir / "rollout-own.jsonl").write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"cwd": str(project_root), "model": "gpt-project"},
            }
        )
        + "\n"
    )
    (sessions_dir / "rollout-foreign.jsonl").write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"cwd": str(foreign_root), "model": "gpt-foreign"},
            }
        )
        + "\n"
    )
    monkeypatch.setattr(
        "lociaction.adapters.harness.registry.resolve_codex_sessions_path",
        lambda: sessions_dir,
    )

    catalogs = model_catalog.discover_project_harness_models(project_root)

    assert [(catalog.harness_id, catalog.models) for catalog in catalogs] == [
        ("codex", ("gpt-project",))
    ]


def test_prompt_client_selection_uses_model_recorded_for_project_harness(
    tmp_path, monkeypatch
) -> None:
    """A selected project harness persists the explicitly selected observed model."""
    codex = ModelClient(
        id="codex-cli",
        provider="codex",
        model=None,
        base_url=None,
        label="Codex CLI",
    )
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.discover",
        lambda: [
            ClientStatus(
                id="llamacpp-ft",
                label="Local FT",
                state="unavailable",
                reason="not installed",
            ),
            ClientStatus(
                id="codex-cli",
                label="Codex CLI",
                state="ready",
                reason="ready",
                client=codex,
            ),
        ],
    )
    monkeypatch.setattr(
        "lociaction.adapters.harness.model_catalog.discover_project_harness_models",
        lambda root: (
            HarnessModelCatalog(
                harness_id="codex",
                label="Codex",
                client_id="codex-cli",
                models=("gpt-5-codex", "gpt-5.1-codex"),
            ),
        ),
    )
    monkeypatch.setattr(
        "lociaction.adapters.harness.model_catalog.discover_available_harness_models",
        lambda harness_id: ("gpt-5-codex", "gpt-5.1-codex"),
    )
    prompts = _prompts(["1", "2"])
    monkeypatch.setattr("typer.prompt", lambda *args, **kwargs: next(prompts))

    selected = prompt_client_selection(tmp_path)

    assert selected is not None
    assert selected.id == "codex-cli"
    assert selected.model == "gpt-5.1-codex"


def test_discover_codex_models_uses_active_account_catalog(monkeypatch) -> None:
    """Codex options come from the active account endpoint, not project history."""
    request = None

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "models": [
                        {"slug": "gpt-5.6-luna"},
                        {"id": "gpt-5.6-sol"},
                        {"slug": "hidden", "visibility": "hidden"},
                        {"slug": "gpt-5.6-luna"},
                    ]
                }
            )

    def fake_urlopen(value, *, timeout):
        nonlocal request
        request = value
        assert timeout == 10
        return Response()

    monkeypatch.setattr(
        model_catalog, "_read_codex_tokens", lambda: ("token", "account")
    )
    monkeypatch.setattr(model_catalog, "_codex_client_version", lambda: "0.149.1")
    monkeypatch.setattr(model_catalog, "urlopen", fake_urlopen)

    assert discover_available_harness_models("codex") == (
        "gpt-5.6-luna",
        "gpt-5.6-sol",
    )
    assert request is not None
    assert request.full_url.endswith("/codex/models?client_version=0.149.1")
    assert request.get_header("Authorization") == "Bearer token"
    assert request.get_header("Chatgpt-account-id") == "account"


def test_discover_harness_commands_use_each_cli_catalog(monkeypatch) -> None:
    """Grok, OpenCode, and OMP defer availability to their own CLIs."""
    outputs = {
        ("grok", "models"): "Available models:\n  - grok-4.6\n  * grok-4.5 (default)\n",
        (
            "opencode",
            "models",
        ): "opencode-go/gpt-5.6-luna\nollama/qwen2.5:14b\n",
        (
            "omp",
            "models",
            "--json",
        ): json.dumps(
            {
                "models": [
                    {"selector": "openai-codex/gpt-5.6-luna"},
                    {"selector": "xai-oauth/grok-4.6"},
                ]
            }
        ),
    }
    monkeypatch.setattr(
        model_catalog,
        "_run_harness_model_command",
        lambda args: outputs[tuple(args)],
    )

    assert discover_available_harness_models("grok") == ("grok-4.6", "grok-4.5")
    assert discover_available_harness_models("opencode") == (
        "opencode-go/gpt-5.6-luna",
        "ollama/qwen2.5:14b",
    )
    assert discover_available_harness_models("omp-pi") == (
        "openai-codex/gpt-5.6-luna",
        "xai-oauth/grok-4.6",
    )


def test_discover_harness_models_keeps_claude_history_only() -> None:
    """Claude Code has no documented noninteractive availability catalog."""
    assert discover_available_harness_models("claude") is None


def test_select_harness_model_prefers_live_catalog_over_history(monkeypatch) -> None:
    """A successful live catalog replaces stale project history in the picker."""
    catalog = HarnessModelCatalog(
        harness_id="codex",
        label="Codex",
        client_id="codex-cli",
        models=("gpt-5.1-codex",),
    )
    monkeypatch.setattr(
        "lociaction.adapters.harness.model_catalog.discover_available_harness_models",
        lambda harness_id: ("gpt-5.6-luna", "gpt-5.6-sol"),
    )
    prompts = _prompts(["1"])
    monkeypatch.setattr("typer.prompt", lambda *args, **kwargs: next(prompts))

    assert _select_harness_model(catalog) == "gpt-5.6-luna"


def test_select_harness_model_falls_back_to_history_when_live_query_fails(
    monkeypatch, capsys
) -> None:
    """A failed live query remains truthful: history is a labelled fallback."""
    catalog = HarnessModelCatalog(
        harness_id="codex",
        label="Codex",
        client_id="codex-cli",
        models=("gpt-5.1-codex",),
    )
    monkeypatch.setattr(
        "lociaction.adapters.harness.model_catalog.discover_available_harness_models",
        lambda harness_id: None,
    )
    prompts = _prompts(["1"])
    monkeypatch.setattr("typer.prompt", lambda *args, **kwargs: next(prompts))

    assert _select_harness_model(catalog) == "gpt-5.1-codex"
    assert "Could not query the current Codex model catalog" in capsys.readouterr().out


def test_select_harness_model_custom_entry_returns_typed_model_id(monkeypatch) -> None:
    """Custom remains an explicit escape hatch outside the advertised catalog."""
    catalog = HarnessModelCatalog(
        harness_id="codex",
        label="Codex",
        client_id="codex-cli",
        models=(),
    )
    monkeypatch.setattr(
        "lociaction.adapters.harness.model_catalog.discover_available_harness_models",
        lambda harness_id: ("gpt-5.6-luna",),
    )
    prompts = _prompts(["3", "custom-model"])
    monkeypatch.setattr("typer.prompt", lambda *args, **kwargs: next(prompts))

    assert _select_harness_model(catalog) == "custom-model"


def test_prompt_client_selection_reprompts_invalid_source_choice(
    tmp_path, monkeypatch
) -> None:
    """An invalid source choice must not silently select the default local FT setup."""
    local = ModelClient(
        id="llamacpp-ft",
        provider="openai",
        model="local-ft",
        base_url=None,
        label="Local FT",
    )
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.discover",
        lambda: [
            ClientStatus(
                id="llamacpp-ft",
                label="Local FT",
                state="ready",
                reason="ready",
                client=local,
            )
        ],
    )
    monkeypatch.setattr(
        "lociaction.adapters.harness.model_catalog.discover_project_harness_models",
        lambda root: (),
    )
    prompts = _prompts(["invalid", "1"])
    monkeypatch.setattr("typer.prompt", lambda *args, **kwargs: next(prompts))

    selected = prompt_client_selection(tmp_path)

    assert selected == local
