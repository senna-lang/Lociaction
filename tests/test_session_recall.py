"""session_recall.py の純関数テスト（recall 再設計）。

セッション一覧（新しい順／関連度順）・関連度の session_id への max 集約・
session_id 解決（前方一致）・要点ダイジェストの組み立てを検証する。
"""

from __future__ import annotations

from pathlib import Path

from lociaction.db import get_connection, init_db
from lociaction.session_recall import (
    build_session_digest,
    list_sessions_by_recency,
    list_sessions_by_relevance,
    resolve_session_id,
    summarize_title,
)


def _setup_db(tmp_path: Path):
    db = tmp_path / "memory.db"
    init_db(db)
    return get_connection(db)


def _insert_session(
    con,
    *,
    session_id: str,
    harness: str = "claude",
    git_branch_last: str | None = None,
    started_at: str | None = "2026-01-01T00:00:00+00:00",
    updated_at: str,
) -> None:
    con.execute(
        """INSERT INTO sessions
           (id, harness, source_session_id, primary_ref, project_key,
            started_at, updated_at, git_branch_last)
           VALUES (?, ?, ?, ?, '', ?, ?, ?)""",
        (session_id, harness, session_id, session_id, started_at, updated_at, git_branch_last),
    )


def _insert_exchange(
    con,
    *,
    exchange_id: str,
    session_id: str,
    ply_start: int,
    user_content: str = "user message",
    agent_content: str = "agent response",
    distill_status: str = "pending",
    core: str | None = None,
    specific: str = "specific detail",
) -> None:
    con.execute(
        """INSERT INTO exchanges
           (id, conversation_id, ply_start, ply_end, user_content, agent_content,
            session_id, distill_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            exchange_id,
            f"conv-{session_id}",
            ply_start,
            ply_start + 1,
            user_content,
            agent_content,
            session_id,
            distill_status,
        ),
    )
    if core is not None:
        con.execute(
            """INSERT INTO palace_objects (id, exchange_id, exchange_core, specific_context, distill_text)
               VALUES (?, ?, ?, ?, ?)""",
            (f"p-{exchange_id}", exchange_id, core, specific, core),
        )


def _insert_exchange_file(con, exchange_id: str, file_path: str) -> None:
    con.execute(
        "INSERT OR IGNORE INTO exchange_files (exchange_id, file_path) VALUES (?, ?)",
        (exchange_id, file_path),
    )


# ---- summarize_title ----


def test_summarize_title_empty_returns_placeholder() -> None:
    assert summarize_title(None) == "(empty)"
    assert summarize_title("") == "(empty)"
    assert summarize_title("   \n  ") == "(empty)"


def test_summarize_title_uses_first_line_only() -> None:
    assert summarize_title("Implement GQA\nsome more detail\nand more") == "Implement GQA"


def test_summarize_title_strips_and_truncates_long_first_line() -> None:
    long_line = "x" * 200
    title = summarize_title(long_line, max_chars=80)
    assert len(title) == 80
    assert title.endswith("…")


# ---- list_sessions_by_recency ----


def test_list_sessions_by_recency_orders_newest_first(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-old", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-old", session_id="s-old", ply_start=0)
    _insert_session(con, session_id="s-new", updated_at="2026-06-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-new", session_id="s-new", ply_start=0)
    con.commit()

    summaries = list_sessions_by_recency(con, limit=10)

    assert [s.session_id for s in summaries] == ["s-new", "s-old"]


def test_list_sessions_by_recency_excludes_sessions_without_exchanges(tmp_path: Path) -> None:
    """再開する対象が無いセッション（exchange 0件）は一覧に出さない。"""
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-empty", updated_at="2026-06-01T00:00:00+00:00")
    _insert_session(con, session_id="s-real", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e1", session_id="s-real", ply_start=0)
    con.commit()

    summaries = list_sessions_by_recency(con, limit=10)

    assert [s.session_id for s in summaries] == ["s-real"]


def test_list_sessions_by_recency_file_filter(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-foo", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-foo", session_id="s-foo", ply_start=0)
    _insert_exchange_file(con, "e-foo", "src/foo.py")
    _insert_session(con, session_id="s-bar", updated_at="2026-02-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-bar", session_id="s-bar", ply_start=0)
    _insert_exchange_file(con, "e-bar", "src/bar.py")
    con.commit()

    summaries = list_sessions_by_recency(con, limit=10, file_path="src/foo.py")

    assert [s.session_id for s in summaries] == ["s-foo"]


def test_list_sessions_by_recency_branch_filter(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(
        con, session_id="s-main", updated_at="2026-01-01T00:00:00+00:00", git_branch_last="main"
    )
    _insert_exchange(con, exchange_id="e-main", session_id="s-main", ply_start=0)
    _insert_session(
        con,
        session_id="s-feat",
        updated_at="2026-02-01T00:00:00+00:00",
        git_branch_last="feat/gqa",
    )
    _insert_exchange(con, exchange_id="e-feat", session_id="s-feat", ply_start=0)
    con.commit()

    summaries = list_sessions_by_recency(con, limit=10, branch="feat")

    assert [s.session_id for s in summaries] == ["s-feat"]


def test_list_sessions_by_recency_limit_truncates(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    for i in range(5):
        sid = f"s-{i}"
        _insert_session(con, session_id=sid, updated_at=f"2026-01-0{i + 1}T00:00:00+00:00")
        _insert_exchange(con, exchange_id=f"e-{i}", session_id=sid, ply_start=0)
    con.commit()

    summaries = list_sessions_by_recency(con, limit=2)

    assert len(summaries) == 2
    assert summaries[0].session_id == "s-4"


def test_session_summary_title_is_first_exchange_first_line(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-1", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con,
        exchange_id="e-1",
        session_id="s-1",
        ply_start=0,
        user_content="Implement GQA\nmore context here",
    )
    _insert_exchange(con, exchange_id="e-2", session_id="s-1", ply_start=1, user_content="follow up")
    con.commit()

    summaries = list_sessions_by_recency(con, limit=10)

    assert summaries[0].title == "Implement GQA"
    assert summaries[0].exchange_count == 2


# ---- list_sessions_by_relevance ----


def test_list_sessions_by_relevance_aggregates_by_max_not_sum(tmp_path: Path) -> None:
    """長いセッション（弱いヒット2件）が、強いヒット1件のセッションに件数で勝たない
    （design: sum ではなく max で集約）。"""
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-strong", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-strong", session_id="s-strong", ply_start=0)
    _insert_session(con, session_id="s-weak-x2", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-weak-1", session_id="s-weak-x2", ply_start=0)
    _insert_exchange(con, exchange_id="e-weak-2", session_id="s-weak-x2", ply_start=1)
    con.commit()

    exchange_scores = {"e-strong": 0.9, "e-weak-1": 0.3, "e-weak-2": 0.3}
    summaries = list_sessions_by_relevance(con, exchange_scores, limit=10)

    assert [s.session_id for s in summaries] == ["s-strong", "s-weak-x2"]
    assert summaries[0].score == 0.9
    assert summaries[1].score == 0.3


def test_list_sessions_by_relevance_empty_scores_returns_empty(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    assert list_sessions_by_relevance(con, {}, limit=10) == []


def test_list_sessions_by_relevance_respects_file_filter(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-a", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-a", session_id="s-a", ply_start=0)
    _insert_exchange_file(con, "e-a", "src/a.py")
    _insert_session(con, session_id="s-b", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-b", session_id="s-b", ply_start=0)
    _insert_exchange_file(con, "e-b", "src/b.py")
    con.commit()

    exchange_scores = {"e-a": 0.5, "e-b": 0.9}
    summaries = list_sessions_by_relevance(con, exchange_scores, limit=10, file_path="src/a.py")

    assert [s.session_id for s in summaries] == ["s-a"]


# ---- resolve_session_id ----


def test_resolve_session_id_exact_match(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="abcdef123456", updated_at="2026-01-01T00:00:00+00:00")
    con.commit()

    resolved, candidates = resolve_session_id(con, "abcdef123456")

    assert resolved == "abcdef123456"
    assert candidates == ["abcdef123456"]


def test_resolve_session_id_unique_prefix_match(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="abcdef123456", updated_at="2026-01-01T00:00:00+00:00")
    con.commit()

    resolved, candidates = resolve_session_id(con, "abcdef")

    assert resolved == "abcdef123456"
    assert candidates == ["abcdef123456"]


def test_resolve_session_id_ambiguous_prefix_returns_none_with_candidates(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="abc111", updated_at="2026-01-01T00:00:00+00:00")
    _insert_session(con, session_id="abc222", updated_at="2026-01-01T00:00:00+00:00")
    con.commit()

    resolved, candidates = resolve_session_id(con, "abc")

    assert resolved is None
    assert sorted(candidates) == ["abc111", "abc222"]


def test_resolve_session_id_no_match_returns_none_and_empty(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    con.commit()

    resolved, candidates = resolve_session_id(con, "nope")

    assert resolved is None
    assert candidates == []


# ---- build_session_digest ----


def test_build_session_digest_unknown_session_returns_none(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    con.commit()

    assert build_session_digest(con, "nope") is None


def test_build_session_digest_lines_in_ply_order_with_distilled_core(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-1", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con,
        exchange_id="e-2",
        session_id="s-1",
        ply_start=4,
        distill_status="distilled",
        core="second decision",
    )
    _insert_exchange(
        con,
        exchange_id="e-1",
        session_id="s-1",
        ply_start=0,
        distill_status="distilled",
        core="first decision",
    )
    con.commit()

    digest = build_session_digest(con, "s-1")
    assert digest is not None

    assert [line.exchange_id for line in digest.lines] == ["e-1", "e-2"]
    assert digest.lines[0].exchange_core == "first decision"
    assert digest.lines[0].distilled is True
    assert digest.total_exchanges == 2
    assert digest.truncated_count == 0


def test_build_session_digest_falls_back_to_user_content_when_undistilled(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-1", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con,
        exchange_id="e-1",
        session_id="s-1",
        ply_start=0,
        user_content="not yet distilled question",
        distill_status="pending",
    )
    con.commit()

    digest = build_session_digest(con, "s-1")
    assert digest is not None

    assert digest.lines[0].exchange_core == "not yet distilled question"
    assert digest.lines[0].distilled is False


def test_build_session_digest_default_omits_full_text(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-1", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con, exchange_id="e-1", session_id="s-1", ply_start=0, distill_status="distilled", core="core"
    )
    con.commit()

    digest = build_session_digest(con, "s-1", full=False)
    assert digest is not None

    assert digest.lines[0].specific_context is None
    assert digest.lines[0].user_content is None
    assert digest.lines[0].agent_content is None


def test_build_session_digest_full_includes_specific_context_and_verbatim(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-1", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con,
        exchange_id="e-1",
        session_id="s-1",
        ply_start=0,
        distill_status="distilled",
        core="core",
        specific="specific",
        user_content="the user asked",
        agent_content="the agent answered",
    )
    con.commit()

    digest = build_session_digest(con, "s-1", full=True)
    assert digest is not None

    assert digest.lines[0].specific_context == "specific"
    assert digest.lines[0].user_content == "the user asked"
    assert digest.lines[0].agent_content == "the agent answered"


def test_build_session_digest_limit_lines_truncates(tmp_path: Path) -> None:
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="s-1", updated_at="2026-01-01T00:00:00+00:00")
    for i in range(5):
        _insert_exchange(
            con,
            exchange_id=f"e-{i}",
            session_id="s-1",
            ply_start=i,
            distill_status="distilled",
            core=f"decision {i}",
        )
    con.commit()

    digest = build_session_digest(con, "s-1", limit_lines=2)
    assert digest is not None

    assert len(digest.lines) == 2
    assert digest.total_exchanges == 5
    assert digest.truncated_count == 3


def test_build_session_digest_resolves_session_prefix(tmp_path: Path) -> None:
    """build_session_digest は完全な session_id のみを受け付ける
    （前方一致解決は resolve_session_id の責務、CLI 層で先に呼ばれる）。"""
    con = _setup_db(tmp_path)
    _insert_session(con, session_id="abcdef123456", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con, exchange_id="e-1", session_id="abcdef123456", ply_start=0, distill_status="distilled", core="c"
    )
    con.commit()

    assert build_session_digest(con, "abcdef") is None
    assert build_session_digest(con, "abcdef123456") is not None
