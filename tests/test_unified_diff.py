"""unified diff パーサのテスト。過長な hunk 座標は例外にせず捨てる。"""

from lociaction.adapters.harness.unified_diff import parse_unified_diff


def test_parse_unified_diff_valid_hunk() -> None:
    parsed = parse_unified_diff("@@ -1,1 +1,2 @@\n-old\n+new\n+extra\n")
    assert parsed is not None
    assert parsed.added == 2
    assert parsed.removed == 1
    assert parsed.line_ranges[0].old_start == 1
    assert parsed.line_ranges[0].new_lines == 2


def test_parse_unified_diff_oversized_coordinate_is_ignored() -> None:
    huge = "9" * 5000
    parsed = parse_unified_diff(f"@@ -{huge} +1 @@\n+ok\n")
    assert parsed is None
