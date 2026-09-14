"""loci docs — version-matched bundled documentation.

Works from any cwd without `.lociaction/`, network, or a distill client.
"""

from __future__ import annotations

import json
from importlib.resources import files

from typer.testing import CliRunner

from lociaction.cli import app
from lociaction.cli.docs_cmd import (
    DOCS_PACKAGE,
    SHOW_HELP,
    _parse_frontmatter,
    load_topics,
)

runner = CliRunner()

EXPECTED_TOPICS = (
    "distillation",
    "getting-started",
    "harnesses",
    "privacy",
    "recall",
    "troubleshooting",
)


def test_docs_list_json_is_parseable_from_any_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["docs", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    names = [item["name"] for item in payload["results"]]
    assert names == list(EXPECTED_TOPICS)
    assert all(item["description"] for item in payload["results"])
    assert payload["help"] == SHOW_HELP


def test_docs_list_human_output_is_a_table(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["docs", "list"])
    assert result.exit_code == 0, result.output
    for name in EXPECTED_TOPICS:
        assert name in result.output
    assert SHOW_HELP in result.output
    assert not result.output.lstrip().startswith("{")


def test_docs_show_matches_bundled_markdown() -> None:
    topics = {topic.name: topic for topic in load_topics()}
    assert set(topics) == set(EXPECTED_TOPICS)
    root = files(DOCS_PACKAGE)
    for name, topic in topics.items():
        result = runner.invoke(app, ["docs", "show", name])
        assert result.exit_code == 0, result.output
        packaged = root.joinpath(f"{name}.md").read_text(encoding="utf-8")
        _, body = _parse_frontmatter(packaged)
        assert result.output in (body, body + "\n")
        assert topic.body == body
        assert "description:" not in result.output.splitlines()[:3]


def test_docs_show_unknown_exits_nonzero_and_lists_names() -> None:
    result = runner.invoke(app, ["docs", "show", "not-a-topic"])
    assert result.exit_code != 0
    assert "Unknown document: not-a-topic" in result.output
    assert "loci docs list" in result.output
    for name in EXPECTED_TOPICS:
        assert name in result.output


def test_docs_does_not_require_initialization(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".lociaction").exists()
    listed = runner.invoke(app, ["docs", "list", "--json"])
    shown = runner.invoke(app, ["docs", "show", "getting-started"])
    assert listed.exit_code == 0
    assert shown.exit_code == 0
    assert "Not initialized" not in listed.output
    assert "Not initialized" not in shown.output


def test_parse_frontmatter_without_block_keeps_body() -> None:
    description, body = _parse_frontmatter("# Title\n\nHello\n")
    assert description == ""
    assert body == "# Title\n\nHello\n"


def test_parse_frontmatter_unclosed_block_keeps_original() -> None:
    text = "---\ndescription: incomplete\n# Title\n"
    description, body = _parse_frontmatter(text)
    assert description == ""
    assert body == text
