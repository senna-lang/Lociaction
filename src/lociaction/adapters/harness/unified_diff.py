"""標準 unified diff を、ハーネス非依存の編集位置と変更量へ正規化する。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lociaction.models import LineRange

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_lines>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_lines>\d+))? @@(?: .*)?$"
)
_MAX_HUNK_COORDINATE_DIGITS = 9


@dataclass(frozen=True)
class ParsedUnifiedDiff:
    """unified diff から直接読み取れる編集範囲と行ごとの変更量。"""

    line_ranges: tuple[LineRange, ...]
    added: int
    removed: int


def parse_unified_diff(diff: str) -> ParsedUnifiedDiff | None:
    """有効な hunk を含む diff を解析し、なければ ``None`` を返す。"""
    line_ranges: list[LineRange] = []
    added = 0
    removed = 0
    old_remaining = 0
    new_remaining = 0

    for line in diff.splitlines():
        header = _HUNK_HEADER_RE.match(line)
        if header is not None:
            parsed_old_remaining = _hunk_int(header["old_lines"], default=1)
            parsed_new_remaining = _hunk_int(header["new_lines"], default=1)
            parsed_old_start = _hunk_int(header["old_start"])
            parsed_new_start = _hunk_int(header["new_start"])
            if (
                parsed_old_remaining is None
                or parsed_new_remaining is None
                or parsed_old_start is None
                or parsed_new_start is None
            ):
                old_remaining = 0
                new_remaining = 0
                continue
            old_remaining = parsed_old_remaining
            new_remaining = parsed_new_remaining
            line_ranges.append(
                LineRange(
                    old_start=parsed_old_start,
                    old_lines=parsed_old_remaining,
                    new_start=parsed_new_start,
                    new_lines=parsed_new_remaining,
                )
            )
            continue

        if old_remaining == 0 and new_remaining == 0:
            continue
        if line.startswith("\\"):
            continue
        if line.startswith("+"):
            added += 1
            new_remaining -= 1
        elif line.startswith("-"):
            removed += 1
            old_remaining -= 1
        else:
            old_remaining -= 1
            new_remaining -= 1

    if not line_ranges:
        return None
    return ParsedUnifiedDiff(tuple(line_ranges), added, removed)


def _hunk_int(raw: str | None, default: int | None = None) -> int | None:
    """hunk 座標を安全な整数へ変換する。過長・非数値は None。"""
    if raw is None:
        return default
    if len(raw) > _MAX_HUNK_COORDINATE_DIGITS:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
