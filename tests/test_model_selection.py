"""Project-local harness and model selection for distillation setup."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from lociaction.adapters.harness.model_catalog import (
    HarnessModelCatalog,
    models_from_entries,
)
from lociaction.adapters.model.types import ClientStatus, ModelClient
from lociaction.cli.distill_cmd import prompt_client_selection


def _prompts(values: list[str]) -> Iterator[str]:
    yield from values


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
    prompts = _prompts(["1", "3"])
    monkeypatch.setattr("typer.prompt", lambda *args, **kwargs: next(prompts))

    selected = prompt_client_selection(tmp_path)

    assert selected is not None
    assert selected.id == "codex-cli"
    assert selected.model == "gpt-5.1-codex"


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
