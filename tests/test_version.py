"""回帰テスト: lociaction.__version__ が pyproject.toml の version と一致すること。

codeatrium → lociaction リネーム時、pyproject.toml の version は 0.1.0 に
リセットされたが src/lociaction/__init__.py の __version__ は "0.3.0" のまま
放置され、`loci init` のバナー表示が食い違っていた。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from lociaction import __version__


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parent.parent / "pyproject.toml").read_text()
    )
    assert __version__ == pyproject["project"]["version"]
