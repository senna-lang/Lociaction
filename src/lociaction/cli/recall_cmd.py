"""loci recall — resume 型セッションブラウザ（recall 再設計、2026-09）。

旧 recall は `--file`/`--branch` を必須とし、context+search を exchange 単位で
マージして返していた。semantic hit の confidence が一律 0.10 だったため実質
recency だけで並び、直近のセッション（例: recall 自体を相談している今の会話）
が exchange 数で押し寄せて古い実装セッションを覆い隠す問題があった。

再設計は Claude Code の `resume` に近い2段構成:

    loci recall                    # セッション一覧・新しい順
    loci recall "keyword"          # セッション一覧・関連度順（recency 減衰は既定 OFF）
    loci recall --session <id>     # 選んだセッションの要点ダイジェスト
    loci recall --session <id> --full   # + specific_context / user_content / agent_content

`--file`/`--branch` は一覧・ダイジェストどちらのモードにも掛けられる独立 AND
フィルタとして存続する（「このファイルを触ったセッション」に絞り込む形へ
格下げ——旧来の主用途を session 粒度で包含する）。

ピンポイントの設計判断を掘る用途は `loci context` → `loci show` のチェーンの
ほうが精度が高い（tiered confidence を持つため）。recall はセッション単位の
俯瞰・resume に特化し、ダイジェスト行の `exchange_id` から `loci show` へ降りられる。
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from lociaction.session_recall import DEFAULT_DIGEST_LINES, DEFAULT_LIST_LIMIT
from lociaction.utils import sanitize_terminal_text


def recall(
    query: Annotated[
        str | None,
        typer.Argument(help="Keyword. Omit to list sessions newest-first"),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            "-s",
            help="Show a session digest (session_id from the list; prefix match ok)",
        ),
    ] = None,
    file_path: Annotated[
        str | None,
        typer.Option(
            "--file",
            help="Restrict to sessions that touched this project-relative file",
        ),
    ] = None,
    branch: Annotated[
        str | None,
        typer.Option("--branch", "-b", help="Filter by git branch (substring match)"),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="List mode: session count (default 10) / digest mode: exchange lines (default 20)",
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
    full: Annotated[
        bool,
        typer.Option(
            "--full",
            help="Include specific_context / user_content / agent_content in the digest (--session)",
        ),
    ] = False,
    recency_half_life_days: Annotated[
        float,
        typer.Option(
            "--recency-half-life",
            help="Recency half-life in days for keyword ranking. 0 (default) disables recency",
        ),
    ] = 0.0,
) -> None:
    """Resume past sessions as a list or a one-session digest."""
    if session is not None and query is not None:
        typer.echo(
            "Error: --session cannot be combined with a keyword query.", err=True
        )
        raise typer.Exit(1)

    from lociaction.db import get_connection
    from lociaction.paths import db_path, find_project_root

    root = find_project_root()
    db = db_path(root)
    if not db.exists():
        from lociaction.cli.errors import abort_not_initialized

        abort_not_initialized()

    con = get_connection(db)
    try:
        if session is not None:
            _run_digest(con, session, limit, json_output, full)
            return

        resolved_file: str | None = None
        alias_paths: tuple[str, ...] = ()
        if file_path is not None:
            from lociaction.cli.search_cmd import _resolve_target_file_path

            resolved_file = _resolve_target_file_path(file_path, str(root))
            if resolved_file is None:
                typer.echo(f"Error: {file_path} is outside the project.", err=True)
                raise typer.Exit(1)
            from lociaction.file_renames import resolve_aliases

            alias_paths = tuple(resolve_aliases(con, str(root), resolved_file))

        if query:
            _run_relevance_list(
                con,
                db,
                query,
                resolved_file,
                alias_paths,
                branch,
                limit,
                json_output,
                recency_half_life_days,
            )
        else:
            _run_recency_list(
                con, resolved_file, alias_paths, branch, limit, json_output
            )
    finally:
        con.close()


def _run_recency_list(
    con,
    file_path: str | None,
    alias_paths: tuple[str, ...],
    branch: str | None,
    limit: int | None,
    json_output: bool,
) -> None:
    from lociaction.session_recall import list_sessions_by_recency

    n = limit or DEFAULT_LIST_LIMIT
    summaries = list_sessions_by_recency(
        con, n, file_path=file_path, alias_paths=alias_paths, branch=branch
    )
    _print_session_list(summaries, json_output)


def _run_relevance_list(
    con,
    db,
    query: str,
    file_path: str | None,
    alias_paths: tuple[str, ...],
    branch: str | None,
    limit: int | None,
    json_output: bool,
    recency_half_life_days: float,
) -> None:
    from lociaction.embedder import Embedder
    from lociaction.search import search_combined
    from lociaction.session_recall import list_sessions_by_relevance

    n = limit or DEFAULT_LIST_LIMIT
    # session 粒度への集約後に n 件残すには、より広い exchange 候補プールが要る
    # （同じセッションの exchange が複数ヒットしても session としては1件に潰れるため）。
    candidate_exchange_limit = min(max(n * 6, 40), 200)

    embedder = Embedder()
    query_vec = embedder.embed(query)
    half_life = recency_half_life_days if recency_half_life_days > 0 else None
    fused = search_combined(
        db,
        query,
        query_vec,
        limit=candidate_exchange_limit,
        recency_half_life_days=half_life,
    )
    exchange_scores = {r.exchange_id: r.score for r in fused}

    summaries = list_sessions_by_relevance(
        con,
        exchange_scores,
        n,
        file_path=file_path,
        alias_paths=alias_paths,
        branch=branch,
    )
    _print_session_list(summaries, json_output)


def _run_digest(
    con, session_ref: str, limit: int | None, json_output: bool, full: bool
) -> None:
    from lociaction.session_recall import build_session_digest, resolve_session_id

    resolved_id, candidates = resolve_session_id(con, session_ref)
    if resolved_id is None:
        if not candidates:
            typer.echo(f'Error: no session matches "{session_ref}".', err=True)
        else:
            shown = ", ".join(c[:12] for c in candidates[:5])
            typer.echo(
                f'Error: "{session_ref}" matches {len(candidates)} sessions '
                f"({shown}{'…' if len(candidates) > 5 else ''}); use more characters.",
                err=True,
            )
        raise typer.Exit(1)

    n = limit or DEFAULT_DIGEST_LINES
    digest = build_session_digest(con, resolved_id, limit_lines=n, full=full)
    if digest is None:
        typer.echo(f'Error: no session matches "{session_ref}".', err=True)
        raise typer.Exit(1)

    _print_digest(digest, json_output)


def _summary_to_dict(s) -> dict:
    return {
        "session_id": s.session_id,
        "harness": s.harness,
        "git_branch": s.git_branch,
        "started_at": s.started_at,
        "updated_at": s.updated_at,
        "title": s.title,
        "exchange_count": s.exchange_count,
        "distilled_count": s.distilled_count,
        "files_touched": s.files_touched,
        "top_rooms": s.top_rooms,
        "score": s.score,
    }


def _print_session_list(summaries: list, json_output: bool) -> None:
    if not summaries:
        if json_output:
            typer.echo("[]")
        else:
            typer.echo("No sessions found.")
        return

    if json_output:
        typer.echo(
            json.dumps(
                [_summary_to_dict(s) for s in summaries], ensure_ascii=False, indent=2
            )
        )
        return

    for i, s in enumerate(summaries, 1):
        score_note = f"  score={s.score:.4f}" if s.score is not None else ""
        typer.echo(
            f"\n[{i}] {s.session_id[:12]}  {s.updated_at}  {s.harness}"
            f"  {sanitize_terminal_text(s.git_branch) or '(no branch)'}{score_note}"
        )
        typer.echo(f"    {sanitize_terminal_text(s.title)}")
        typer.echo(f"    {s.exchange_count} exchanges ({s.distilled_count} distilled)")
        if s.files_touched:
            files = ", ".join(sanitize_terminal_text(path) for path in s.files_touched)
            typer.echo(f"    files: {files}")
        if s.top_rooms:
            labels = ", ".join(
                sanitize_terminal_text(r["room_label"]) for r in s.top_rooms
            )
            typer.echo(f"    concepts: {labels}")
    typer.echo(
        f"\nUse `loci recall --session {summaries[0].session_id[:12]}` "
        "for a session's digest."
    )


def _digest_line_to_dict(line) -> dict:
    item = {
        "exchange_id": line.exchange_id,
        "ply_start": line.ply_start,
        "exchange_core": line.exchange_core,
        "distilled": line.distilled,
    }
    if line.specific_context is not None:
        item["specific_context"] = line.specific_context
    if line.user_content is not None:
        item["user_content"] = line.user_content
    if line.agent_content is not None:
        item["agent_content"] = line.agent_content
    return item


def _print_digest(digest, json_output: bool) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "summary": _summary_to_dict(digest.summary),
                    "lines": [_digest_line_to_dict(line) for line in digest.lines],
                    "total_exchanges": digest.total_exchanges,
                    "truncated": digest.truncated_count,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    s = digest.summary
    typer.echo(
        f"Session {s.session_id[:12]} "
        f"({s.harness}, {sanitize_terminal_text(s.git_branch) or '(no branch)'})"
    )
    typer.echo(f"  {sanitize_terminal_text(s.title)}")
    typer.echo(f"  {s.exchange_count} exchanges ({s.distilled_count} distilled)")
    if s.files_touched:
        files = ", ".join(sanitize_terminal_text(path) for path in s.files_touched)
        typer.echo(f"  files: {files}")
    if s.top_rooms:
        typer.echo(
            "  concepts: "
            + ", ".join(sanitize_terminal_text(r["room_label"]) for r in s.top_rooms)
        )

    for line in digest.lines:
        note = "" if line.distilled else " [undistilled]"
        typer.echo(
            f"\n[ply {line.ply_start}] {sanitize_terminal_text(line.exchange_core)}"
            f"{note}  (ex={line.exchange_id[:12]})"
        )
        if line.specific_context:
            typer.echo(f"    {sanitize_terminal_text(line.specific_context)}")
        if line.user_content is not None:
            typer.echo(
                f"    user: {sanitize_terminal_text(line.user_content[:200])}"
            )
        if line.agent_content is not None:
            typer.echo(
                f"    agent: {sanitize_terminal_text(line.agent_content[:200])}"
            )

    if digest.truncated_count:
        typer.echo(
            f"\n… +{digest.truncated_count} more "
            f"(loci recall --session {s.session_id[:12]} -n {digest.total_exchanges} for all, "
            "or loci show <exchange_id> for verbatim text)"
        )
