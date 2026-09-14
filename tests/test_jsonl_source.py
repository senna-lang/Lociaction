"""
JsonlLogSource の `.lociaction/ignore` プライバシフィルタと JSONL artifact 抽出のテスト。

artifact は indexer と同じ「有効な JSON エントリのみ」の ply 座標を使い、空行または
破損行を含むログでも対応する exchange へ touch を関連付ける。
"""
import json
from pathlib import Path

import pytest

from lociaction.adapters.harness.jsonl_source import JsonlLogSource
from lociaction.core.models import CanonicalSession
from lociaction.indexer import Exchange
from lociaction.models import CodeTouch
from lociaction.paths import session_file_matches_project_root


def _make_session(project_root: Path) -> CanonicalSession:
    return CanonicalSession(
        harness="fake",
        source_session_id="session-1",
        primary_ref=str(project_root / "session.jsonl"),
        project_key=str(project_root),
    )


class _RecordingTouchAdapter:
    """渡された raw entry から、どの entry が artifact 化されたかを返すテスト用 adapter。"""

    def extract_code_touches(
        self, entries: list[dict[str, object] | None]
    ) -> list[CodeTouch]:
        return [
            CodeTouch(
                harness="fake",
                tool_call_id=str(entry["id"]),
                file_path=str(entry["path"]),
                touch_kind="edit",
                locators=(),
                added=0,
                removed=0,
                ts=None,
            )
            for entry in entries
            if entry is not None
        ]


def test_parse_exchanges_excludes_exchange_touching_ignored_file(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    lociaction_dir = project_root / ".lociaction"
    lociaction_dir.mkdir(parents=True)
    (lociaction_dir / "ignore").write_text("secrets/*\n")

    def fake_parser(jsonl_path: Path, min_chars: int, last_ply_end: int) -> list[Exchange]:
        return [
            Exchange(
                id="ex1",
                conversation_id="conv1",
                ply_start=0,
                ply_end=1,
                user_content="normal request",
                agent_content="normal reply",
                files=["src/auth.py"],
            ),
            Exchange(
                id="ex2",
                conversation_id="conv1",
                ply_start=2,
                ply_end=3,
                user_content="secret request",
                agent_content="secret reply",
                files=["secrets/api_key.txt"],
            ),
        ]

    source = JsonlLogSource("fake", lambda root: root, fake_parser)
    session = _make_session(project_root)

    result = source.parse_exchanges(session, cursor=None, min_chars=1)

    assert [ex.source_turn_id for ex in result.exchanges] == ["0"]
    assert result.exchanges[0].user_content == "normal request"


def test_parse_exchanges_without_ignore_file_keeps_everything(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()

    def fake_parser(jsonl_path: Path, min_chars: int, last_ply_end: int) -> list[Exchange]:
        return [
            Exchange(
                id="ex1",
                conversation_id="conv1",
                ply_start=0,
                ply_end=1,
                user_content="secret request",
                agent_content="secret reply",
                files=["secrets/api_key.txt"],
            ),
        ]

    source = JsonlLogSource("fake", lambda root: root, fake_parser)
    session = _make_session(project_root)

    result = source.parse_exchanges(session, cursor=None, min_chars=1)

    assert len(result.exchanges) == 1


@pytest.mark.parametrize("invalid_line", ["", '{"broken":'])
def test_parse_exchanges_artifacts_skip_blank_and_malformed_lines(
    tmp_path: Path, invalid_line: str
) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    session = _make_session(project_root)
    Path(session.primary_ref).write_text(
        "\n".join(
            [
                json.dumps({"id": "earlier", "path": "src/earlier.py"}),
                invalid_line,
                json.dumps({"id": "target", "path": "src/target.py"}),
            ]
        ),
        encoding="utf-8",
    )

    def fake_parser(jsonl_path: Path, min_chars: int, last_ply_end: int) -> list[Exchange]:
        return [
            Exchange(
                id="ex-target",
                conversation_id="conv1",
                ply_start=1,
                ply_end=1,
                user_content="target request",
                agent_content="target reply",
                files=[],
            )
        ]

    source = JsonlLogSource(
        "fake",
        lambda root: root,
        fake_parser,
        touch_adapter=_RecordingTouchAdapter(),
    )

    result = source.parse_exchanges(session, cursor=None, min_chars=1)

    assert [
        (artifact.source_turn_id, [touch.file_path for touch in artifact.code_touches])
        for artifact in result.artifacts
    ] == [("1", ["src/target.py"])]


def test_session_path_validator_excludes_foreign_collision_logs(tmp_path: Path) -> None:
    """validator は同じ session directory 内でも foreign cwd のログを列挙しない。"""
    project_root = tmp_path / "project"
    foreign_root = tmp_path / "foreign"
    project_root.mkdir()
    foreign_root.mkdir()
    own_log = project_root / "own.jsonl"
    own_log.write_text(json.dumps({"cwd": str(project_root)}) + "\n")
    foreign_log = project_root / "foreign.jsonl"
    foreign_log.write_text(json.dumps({"cwd": str(foreign_root)}) + "\n")

    source = JsonlLogSource(
        "fake",
        lambda root: root,
        lambda *_args: [],
        session_path_validator=session_file_matches_project_root,
    )

    assert source.detect(project_root) is True
    assert [Path(session.primary_ref) for session in source.list_sessions(project_root)] == [
        own_log.resolve()
    ]
