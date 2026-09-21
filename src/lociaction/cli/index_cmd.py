"""loci index コマンド"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lociaction.adapters.harness import codex as codex_adapter
from lociaction.utils import sanitize_terminal_text

_HARNESS_CHOICES = ("claude", "codex", "opencode", "omp-pi", "grok")

# ハーネスごとのログファイル名パターン。同じディレクトリに別形式のファイルが
# 同居することがあるため（grok の prompt_history.jsonl / events.jsonl）、
# 素朴な "*.jsonl" では拾いすぎる。
_LOG_PATTERNS = {"codex": "rollout-*.jsonl", "grok": "updates.jsonl"}


def _purge_foreign_codex_exchanges(db: Path, project_root: Path) -> int:
    """Remove previously indexed Codex rollouts outside the active project."""
    from lociaction.db import get_connection

    con = get_connection(db)
    try:
        rows = con.execute(
            "SELECT id, session_ref FROM exchanges WHERE harness = 'codex'"
        ).fetchall()
        scope_by_rollout: dict[str, bool] = {}
        foreign_ids: list[str] = []
        for exchange_id, session_ref in rows:
            rollout = session_ref.partition("#")[0]
            in_scope = scope_by_rollout.get(rollout)
            if in_scope is None:
                rollout_path = Path(rollout)
                in_scope = not rollout_path.exists() or (
                    codex_adapter.session_belongs_to_project(rollout_path, project_root)
                )
                scope_by_rollout[rollout] = in_scope
            if not in_scope:
                foreign_ids.append(exchange_id)
        if not foreign_ids:
            return 0
        placeholders = ",".join("?" for _ in foreign_ids)
        palace_ids = (
            f"SELECT id FROM palace_objects WHERE exchange_id IN ({placeholders})"
        )
        con.execute(
            f"DELETE FROM rooms WHERE palace_object_id IN ({palace_ids})",
            foreign_ids,
        )
        con.execute(
            f"DELETE FROM vec_palace WHERE palace_id IN ({palace_ids})",
            foreign_ids,
        )
        for table in ("exchange_files", "code_touches", "code_edges"):
            con.execute(
                f"DELETE FROM {table} WHERE exchange_id IN ({placeholders})",
                foreign_ids,
            )
        con.execute(
            f"DELETE FROM palace_objects WHERE exchange_id IN ({placeholders})",
            foreign_ids,
        )
        con.execute(f"DELETE FROM exchanges WHERE id IN ({placeholders})", foreign_ids)
        con.execute(
            """
            DELETE FROM sessions
            WHERE harness = 'codex'
              AND id NOT IN (SELECT DISTINCT session_id FROM exchanges)
            """
        )
        con.commit()
        return len(foreign_ids)
    finally:
        con.close()


def index(
    path: Annotated[
        Path | None,
        typer.Option(help="Session path (OpenCode: DB file; others: directory)"),
    ] = None,
    harness: Annotated[
        str,
        typer.Option(
            "--harness",
            help="Log format (all / claude / codex / opencode / omp-pi / grok)",
        ),
    ] = "all",
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Index unprocessed session logs into exchanges and code-touch records."""
    from lociaction.config import load_config
    from lociaction.db import init_db
    from lociaction.indexer import index_file, index_opencode_db
    from lociaction.paths import (
        db_path,
        find_project_root,
        resolve_claude_projects_path,
        resolve_codex_sessions_path,
        resolve_grok_sessions_path,
        resolve_omp_pi_sessions_path,
        resolve_opencode_db_path,
        session_files_for_project,
    )

    root = find_project_root()
    db = db_path(root)

    if not db.exists():
        from lociaction.cli.errors import abort_not_initialized

        abort_not_initialized()
    if harness == "all":
        from lociaction.adapters.harness.registry import detected_jsonl_sources

        source_ids = [
            source.id for source in detected_jsonl_sources() if source.detect(root)
        ]
        if resolve_opencode_db_path() is not None:
            source_ids.append("opencode")
        if not source_ids:
            typer.echo("No detected harness sessions.")
            return
        for source_id in source_ids:
            index(path=None, harness=source_id, verbose=verbose)
        return
    if harness not in _HARNESS_CHOICES:
        choices = ", ".join(("all", *_HARNESS_CHOICES))
        typer.echo(f"Unsupported harness. Choose one of: {choices}.", err=True)
        raise typer.Exit(1)

    init_db(db)
    from lociaction.db import check_drift

    drifts = check_drift(db)
    for key, recorded, current in drifts:
        typer.echo(
            f"[warn] {key} changed ({recorded} -> {current}). Re-index recommended.",
            err=True,
        )
    cfg = load_config(root)
    if harness == "codex":
        _purge_foreign_codex_exchanges(db, root)

    if harness == "opencode":
        opencode_db = path or resolve_opencode_db_path()
        if opencode_db is None or not opencode_db.exists():
            typer.echo(
                "OpenCode session DB not found. Use --path to specify.", err=True
            )
            raise typer.Exit(1)

        total_exchanges = index_opencode_db(
            opencode_db, db, min_chars=cfg.index_min_chars, project_root=root
        )
        if total_exchanges == 0:
            typer.echo("Nothing new to index.")
            return
        typer.echo(f"Indexed 1 file(s), {total_exchanges} exchange(s).")
        return

    if path is not None:
        target_dir = path
    elif harness == "claude":
        target_dir = resolve_claude_projects_path(root)
    elif harness == "omp-pi":
        target_dir = resolve_omp_pi_sessions_path(root)
    elif harness == "grok":
        target_dir = resolve_grok_sessions_path(root)
    else:
        target_dir = resolve_codex_sessions_path()
    if target_dir is None:
        typer.echo(
            f"{harness.capitalize()} sessions dir not found. Use --path to specify.",
            err=True,
        )
        raise typer.Exit(1)

    jsonl_files = list(target_dir.rglob(_LOG_PATTERNS.get(harness, "*.jsonl")))
    if harness == "codex":
        jsonl_files = [
            rollout
            for rollout in jsonl_files
            if codex_adapter.session_belongs_to_project(rollout, root)
        ]
    elif harness in {"claude", "omp-pi"}:
        jsonl_files = session_files_for_project(
            target_dir, root, _LOG_PATTERNS.get(harness, "*.jsonl")
        )
    if not jsonl_files:
        typer.echo("No session files found.")
        return

    total_exchanges = 0
    files_with_new = 0
    for jsonl in jsonl_files:
        count = index_file(
            jsonl,
            db,
            min_chars=cfg.index_min_chars,
            project_root=root,
            harness=harness,
        )
        if count == 0:
            continue
        files_with_new += 1
        if verbose:
            typer.echo(f"  {sanitize_terminal_text(jsonl.name)}: {count} exchanges")
        total_exchanges += count

    if total_exchanges == 0:
        typer.echo("Nothing new to index.")
        return

    typer.echo(f"Indexed {files_with_new} file(s), {total_exchanges} exchange(s).")
