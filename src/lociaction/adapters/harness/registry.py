"""Composition helpers for the harness LogSource adapters."""

from __future__ import annotations

from lociaction.adapters.harness import (
    claude as claude_adapter,
)
from lociaction.adapters.harness import (
    codex as codex_adapter,
)
from lociaction.adapters.harness import (
    grok as grok_adapter,
)
from lociaction.adapters.harness import (
    omp_pi as omp_pi_adapter,
)
from lociaction.adapters.harness.jsonl_source import JsonlLogSource
from lociaction.indexer import (
    parse_codex_exchanges,
    parse_exchanges,
    parse_grok_exchanges,
    parse_omp_pi_exchanges,
)
from lociaction.paths import (
    resolve_claude_projects_path,
    resolve_codex_sessions_path,
    resolve_grok_sessions_path,
    resolve_omp_pi_sessions_path,
    session_file_matches_project_root,
)


def _resolve_codex(_project_root):
    return resolve_codex_sessions_path()


def detected_jsonl_sources() -> tuple[JsonlLogSource, ...]:
    """Return the JSONL sources supported by the current installation."""
    return (
        JsonlLogSource(
            "claude",
            resolve_claude_projects_path,
            parse_exchanges,
            touch_adapter=claude_adapter,
            parent_ref_resolver=claude_adapter.parent_session_ref,
            session_path_validator=session_file_matches_project_root,
        ),
        JsonlLogSource(
            "codex",
            _resolve_codex,
            parse_codex_exchanges,
            "rollout-*.jsonl",
            touch_adapter=codex_adapter,
            session_path_validator=codex_adapter.session_belongs_to_project,
        ),
        JsonlLogSource(
            "omp-pi",
            resolve_omp_pi_sessions_path,
            parse_omp_pi_exchanges,
            touch_adapter=omp_pi_adapter,
            session_path_validator=session_file_matches_project_root,
        ),
        JsonlLogSource(
            "grok",
            resolve_grok_sessions_path,
            parse_grok_exchanges,
            "updates.jsonl",
            touch_adapter=grok_adapter,
        ),
    )
