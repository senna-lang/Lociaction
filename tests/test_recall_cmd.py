"""loci recall コマンドの出力契約テスト（recall 再設計）。

セッション一覧（新しい順／関連度順）・`--session` ダイジェスト・`--file`/
`--branch` フィルタ・エラー系（session未初期化・曖昧な session_ref・
query と --session の同時指定）を検証する。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from typer.testing import CliRunner

from lociaction.cli import app
from lociaction.db import get_connection, init_db

runner = CliRunner()

LONG = "x" * 200


@pytest.fixture(autouse=True)
def _stub_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """キーワード一覧モードは search_combined を呼ぶため、モデルロードを避ける。"""
    mock = MagicMock()
    mock.embed.return_value = np.zeros(384, dtype=np.float32)
    monkeypatch.setattr("lociaction.embedder.Embedder", lambda: mock)


def _setup(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    db = lociaction_dir / "memory.db"
    init_db(db)
    return db, get_connection(db)


def _insert_session(
    con: sqlite3.Connection,
    *,
    session_id: str,
    harness: str = "claude",
    git_branch_last: str | None = None,
    updated_at: str,
) -> None:
    con.execute(
        """INSERT INTO sessions
           (id, harness, source_session_id, primary_ref, project_key,
            started_at, updated_at, git_branch_last)
           VALUES (?, ?, ?, ?, '', ?, ?, ?)""",
        (session_id, harness, session_id, session_id, updated_at, updated_at, git_branch_last),
    )


def _insert_exchange(
    con: sqlite3.Connection,
    *,
    exchange_id: str,
    session_id: str,
    ply_start: int = 0,
    user_content: str | None = None,
    agent_content: str | None = None,
    distill_status: str = "distilled",
    core: str = "core summary",
    specific: str = "specific detail",
    file_path: str | None = None,
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
            user_content or ("user " + LONG),
            agent_content or ("agent " + LONG),
            session_id,
            distill_status,
        ),
    )
    con.execute(
        """INSERT INTO palace_objects (id, exchange_id, exchange_core, specific_context, distill_text)
           VALUES (?, ?, ?, ?, ?)""",
        (f"p-{exchange_id}", exchange_id, core, specific, core),
    )
    if file_path is not None:
        con.execute(
            "INSERT INTO exchange_files (exchange_id, file_path) VALUES (?, ?)",
            (exchange_id, file_path),
        )


def _invoke_recall(args: list[str]):
    return runner.invoke(app, ["recall", *args])


# ---- not initialized ----


def test_recall_not_initialized_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = _invoke_recall([])

    assert result.exit_code == 1
    assert "Not initialized" in result.output


# ---- bare recall: session list, newest first ----


def test_recall_bare_lists_sessions_newest_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="s-old", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-old", session_id="s-old", core="old work")
    _insert_session(con, session_id="s-new", updated_at="2026-06-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-new", session_id="s-new", core="new work")
    con.commit()
    con.close()

    result = _invoke_recall(["--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [row["session_id"] for row in data] == ["s-new", "s-old"]
    assert data[0]["score"] is None


def test_recall_bare_text_output_sanitizes_git_branch(tmp_path, monkeypatch):
    """session-log 由来の git_branch に terminal 制御シーケンスが含まれても、
    text 出力ではそのまま echo しない(LOCI-CLI-001)"""
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(
        con,
        session_id="s-evil",
        updated_at="2026-01-01T00:00:00+00:00",
        git_branch_last="main\x1b[31mpwned",
    )
    _insert_exchange(con, exchange_id="e-evil", session_id="s-evil", core="work")
    con.commit()
    con.close()

    result = _invoke_recall([])

    assert result.exit_code == 0
    assert "\x1b" not in result.output
    assert "pwned" in result.output


def test_recall_bare_no_sessions_reports_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup(tmp_path)[1].close()

    result = _invoke_recall([])

    assert result.exit_code == 0
    assert "No sessions found" in result.output


def test_recall_bare_excludes_sessions_without_exchanges(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="s-empty", updated_at="2026-06-01T00:00:00+00:00")
    con.commit()
    con.close()

    result = _invoke_recall(["--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == []


# ---- --file / --branch filters on list mode ----


def test_recall_file_filter_restricts_session_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="s-foo", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-foo", session_id="s-foo", file_path="src/foo.py")
    _insert_session(con, session_id="s-bar", updated_at="2026-02-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-bar", session_id="s-bar", file_path="src/bar.py")
    con.commit()
    con.close()

    result = _invoke_recall(["--file", "src/foo.py", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [row["session_id"] for row in data] == ["s-foo"]


def test_recall_branch_filter_restricts_session_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(
        con, session_id="s-main", updated_at="2026-01-01T00:00:00+00:00", git_branch_last="main"
    )
    _insert_exchange(con, exchange_id="e-main", session_id="s-main")
    _insert_session(
        con,
        session_id="s-feat",
        updated_at="2026-02-01T00:00:00+00:00",
        git_branch_last="feat/gqa",
    )
    _insert_exchange(con, exchange_id="e-feat", session_id="s-feat")
    con.commit()
    con.close()

    result = _invoke_recall(["--branch", "feat", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [row["session_id"] for row in data] == ["s-feat"]


def test_recall_file_outside_project_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup(tmp_path)[1].close()

    result = _invoke_recall(["--file", "/completely/outside/project/foo.py"])

    assert result.exit_code == 1
    assert "outside the project" in result.output


# ---- keyword mode: relevance-ranked session list ----


def test_recall_keyword_ranks_sessions_by_relevance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="s-gqa", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con,
        exchange_id="e-gqa",
        session_id="s-gqa",
        user_content="grouped query attention implementation details " + LONG,
        core="GQA implementation",
    )
    _insert_exchange(
        con,
        exchange_id="e-gqa-2",
        session_id="s-gqa",
        ply_start=1,
        user_content="follow up on attention heads " + LONG,
        core="follow-up detail",
    )
    _insert_session(con, session_id="s-unrelated", updated_at="2026-06-01T00:00:00+00:00")
    _insert_exchange(
        con,
        exchange_id="e-unrelated",
        session_id="s-unrelated",
        user_content="totally unrelated chatter " + LONG,
        core="unrelated chatter",
    )
    _insert_exchange(
        con,
        exchange_id="e-unrelated-2",
        session_id="s-unrelated",
        ply_start=1,
        user_content="more unrelated chatter " + LONG,
        core="more unrelated chatter",
    )
    con.commit()
    con.close()

    result = _invoke_recall(["grouped query attention", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    ids = [row["session_id"] for row in data]
    assert "s-gqa" in ids
    # 関連度順なので、より新しいだけの無関係セッションが先頭に来ない。
    assert ids[0] == "s-gqa"
    assert data[0]["score"] is not None


def test_recall_keyword_no_match_reports_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup(tmp_path)[1].close()

    result = _invoke_recall(["nonexistent keyword phrase"])

    assert result.exit_code == 0
    assert "No sessions found" in result.output


# ---- --session digest ----


def test_recall_session_digest_returns_ordered_lines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="abcdef123456", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con, exchange_id="e-1", session_id="abcdef123456", ply_start=0, core="first decision"
    )
    _insert_exchange(
        con, exchange_id="e-2", session_id="abcdef123456", ply_start=4, core="second decision"
    )
    con.commit()
    con.close()

    result = _invoke_recall(["--session", "abcdef123456", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["summary"]["session_id"] == "abcdef123456"
    assert [line["exchange_core"] for line in data["lines"]] == [
        "first decision",
        "second decision",
    ]
    assert data["total_exchanges"] == 2
    assert data["truncated"] == 0
    # 既定は全文を含まない（design: Tier 1）
    assert "specific_context" not in data["lines"][0]
    assert "user_content" not in data["lines"][0]


def test_recall_session_digest_full_includes_verbatim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="abcdef123456", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(
        con,
        exchange_id="e-1",
        session_id="abcdef123456",
        core="decision",
        specific="specific detail",
        user_content="verbatim user text",
        agent_content="verbatim agent text",
    )
    con.commit()
    con.close()

    result = _invoke_recall(["--session", "abcdef123456", "--full", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["lines"][0]["specific_context"] == "specific detail"
    assert data["lines"][0]["user_content"] == "verbatim user text"
    assert data["lines"][0]["agent_content"] == "verbatim agent text"


def test_recall_session_prefix_match_resolves_uniquely(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="abcdef123456", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-1", session_id="abcdef123456", core="decision")
    con.commit()
    con.close()

    result = _invoke_recall(["--session", "abcdef", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["summary"]["session_id"] == "abcdef123456"


def test_recall_session_ambiguous_prefix_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="abc111", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-1", session_id="abc111", core="decision")
    _insert_session(con, session_id="abc222", updated_at="2026-01-01T00:00:00+00:00")
    _insert_exchange(con, exchange_id="e-2", session_id="abc222", core="decision")
    con.commit()
    con.close()

    result = _invoke_recall(["--session", "abc"])

    assert result.exit_code == 1
    assert "matches 2 sessions" in result.output


def test_recall_session_unknown_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup(tmp_path)[1].close()

    result = _invoke_recall(["--session", "nonexistent"])

    assert result.exit_code == 1
    assert "no session matches" in result.output


def test_recall_session_digest_truncates_with_limit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db, con = _setup(tmp_path)
    _insert_session(con, session_id="abcdef123456", updated_at="2026-01-01T00:00:00+00:00")
    for i in range(5):
        _insert_exchange(
            con, exchange_id=f"e-{i}", session_id="abcdef123456", ply_start=i, core=f"decision {i}"
        )
    con.commit()
    con.close()

    result = _invoke_recall(["--session", "abcdef123456", "--limit", "2", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["lines"]) == 2
    assert data["total_exchanges"] == 5
    assert data["truncated"] == 3


# ---- mutually exclusive query + --session ----


def test_recall_query_and_session_together_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup(tmp_path)[1].close()

    result = _invoke_recall(["some query", "--session", "abc"])

    assert result.exit_code == 1
    assert "cannot be combined" in result.output
