"""回帰テスト: lociaction.__version__ が pyproject.toml の version と一致すること。

codeatrium → lociaction リネーム時、pyproject.toml の version は 0.1.0 に
リセットされたが src/lociaction/__init__.py の __version__ は "0.3.0" のまま
放置され、`loci init` のバナー表示が食い違っていた。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

from lociaction import __version__
from lociaction.cli import app

runner = CliRunner()


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parent.parent / "pyproject.toml").read_text()
    )
    assert __version__ == pyproject["project"]["version"]


def test_cli_version_is_a_single_line() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines == [f"lociaction {__version__}"]


def test_cli_help_points_at_docs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "loci docs list" in result.output
    assert "loci docs show troubleshooting" in result.output
