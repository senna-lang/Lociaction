"""
`.lociaction/ignore` の gitignore 風パターンマッチングのテスト（issue #36）
"""

from pathlib import Path

from lociaction.ignore import load_ignore


def test_load_ignore_returns_empty_matcher_when_file_absent(tmp_path: Path) -> None:
    matcher = load_ignore(tmp_path)
    assert matcher.matches("secrets/api_key.txt") is False


def test_load_ignore_rejects_symlinked_ignore_file(tmp_path: Path) -> None:
    """.lociaction/ignore が symlink の場合、check-then-open ではなく
    openat 相当で拒否し、外部ファイルの内容を読み込まない
    (LOCI-IGNORE-LOADIGNORE-TOCTOU)。"""
    (tmp_path / ".lociaction").mkdir()
    outside = tmp_path / "outside-ignore"
    outside.write_text("*.pem\n")
    (tmp_path / ".lociaction" / "ignore").symlink_to(outside)

    matcher = load_ignore(tmp_path)

    assert matcher.matches("certs/server.pem") is False


def test_load_ignore_skips_fifo_without_blocking(tmp_path: Path) -> None:
    """.lociaction/ignore が FIFO の場合、open でブロックせず「無し」として
    扱う (LOCI-IGNORE-LOADIGNORE-TOCTOU)。"""
    import os as os_module

    (tmp_path / ".lociaction").mkdir()
    os_module.mkfifo(tmp_path / ".lociaction" / "ignore")

    matcher = load_ignore(tmp_path)

    assert matcher.matches("secrets/api_key.txt") is False


def test_matches_simple_filename_pattern_at_any_depth(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text(".env\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches(".env") is True
    assert matcher.matches("config/.env") is True
    assert matcher.matches("config/.env.local") is False


def test_matches_question_wildcard(tmp_path: Path) -> None:
    """`?` は任意の1文字に一致し、機微ファイル除外を fail-open にしない
    （LOCI-IGNORE-QUESTION-WILDCARD-BYPASS-01）。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("secrets?.env\n")

    matcher = load_ignore(tmp_path)

    assert matcher.matches("secrets1.env") is True
    assert matcher.matches("secrets.env") is False


def test_matches_extension_wildcard(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("*.pem\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("certs/server.pem") is True
    assert matcher.matches("server.pem.bak") is False


def test_matches_directory_pattern_only_matches_contents(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("secrets/\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("secrets/api_key.txt") is True
    assert matcher.matches("secrets") is False
    assert matcher.matches("mysecrets/x") is False


def test_matches_anchored_pattern_only_at_root(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("/config.local.toml\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("config.local.toml") is True
    assert matcher.matches("sub/config.local.toml") is False


def test_matches_double_star_crosses_directories(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("**/node_modules/**\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("a/b/node_modules/x/y.js") is True
    assert matcher.matches("node_modules/x.js") is True
    assert matcher.matches("node_modules") is False


def test_consecutive_globstars_are_skipped(tmp_path: Path) -> None:
    """曖昧な複数 globstar は指数バックトラッキングを避けるため採用しない。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("**/**/**/**/target\n")

    matcher = load_ignore(tmp_path)

    assert matcher.matches("a/b/c/d/not-target") is False



def test_alternating_globstars_match_deep_paths_without_backtracking_failure(
    tmp_path: Path,
) -> None:
    """許可する globstar でも深い非一致パスを安全に評価する。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("**/a/**/target\n")

    matcher = load_ignore(tmp_path)

    assert matcher.matches("/".join("a" for _ in range(500))) is False


def test_oversized_segment_fails_closed_as_excluded(tmp_path: Path) -> None:
    """attacker-controlled パス segment が極端に長い場合、DP評価を打ち切って
    「一致しない」(fail-open) にすると secret-exclusion ルールを長い path で
    迂回できてしまうため、安全側の「除外対象」として扱う
    (LOCI-IGNORE-LENCAP-BYPASS-01)。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("*a*a*a\n")

    matcher = load_ignore(tmp_path)
    oversized_segment = "a" * 200_000

    assert matcher.matches(oversized_segment) is True


def test_wildcard_pattern_does_not_backtrack_polynomially_at_full_segment_cap(
    tmp_path: Path,
) -> None:
    """3 wildcard + cap いっぱい(1024文字)の path という組み合わせでも
    DP matcher は多項式時間で確定する (LOCI-IGNORE-REDOS-POLY)。"""
    import time

    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("*a*a*b\n")

    matcher = load_ignore(tmp_path)
    # 末尾に必須の "b" を含めず、必ず失敗探索になる最悪ケースを作る。
    # ちょうど MAX_IGNORE_PATH_LENGTH(1024) に収め、fail-closed 早期リターンでは
    # なく実際の DP 経路を通ることを保証する。
    adversarial_segment = "a" * 1024

    started = time.monotonic()
    result = matcher.matches(adversarial_segment)
    elapsed = time.monotonic() - started

    assert result is False
    assert elapsed < 2.0


def test_leading_globstar_matches_deep_path_without_recursion_error(
    tmp_path: Path,
) -> None:
    """攻撃者が捏造した深い path（cap 未満だが多数の `/` 区切り segment）でも、
    非末尾 `**` の評価が RecursionError を起こさない
    (LOCI-IGNORE-GLOBSTAR-STACKDOS-01)。cap を超えると fail-closed 経路
    (LOCI-IGNORE-LENCAP-BYPASS-01) に入るため、cap(1024文字)未満で検証する。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("**/node_modules/**\n")

    matcher = load_ignore(tmp_path)
    # 1文字 segment を "/" で繋ぐことで、文字数上限内で segment 数を最大化する。
    deep_non_matching_path = "/".join("x" for _ in range(400))
    deep_matching_path = "/".join("x" for _ in range(300)) + "/node_modules/x.js"

    assert matcher.matches(deep_non_matching_path) is False
    assert matcher.matches(deep_matching_path) is True


def test_path_exceeding_length_cap_fails_closed_as_excluded(
    tmp_path: Path,
) -> None:
    """多数の小さな segment の合計文字数が cap を超える path も、rule の有無に
    関わらず安全側の「除外対象」として扱う (LOCI-IGNORE-LENCAP-BYPASS-01)。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("**/node_modules/**\n")

    matcher = load_ignore(tmp_path)
    over_cap_path = "/".join("x" for _ in range(600))

    assert matcher.matches(over_cap_path) is True


def test_many_adversarial_rules_against_cap_sized_path_stay_bounded(
    tmp_path: Path,
) -> None:
    """MAX_IGNORE_RULES いっぱいの敵対的ルール（各 256 文字・3 wildcard 使い切り）
    × cap いっぱいの path でも、2重 DP の積み重ねが現実的な時間で確定する
    (LOCI-IGNORE-DP-LEAFMATCH-BLOWUP)。"""
    import time

    (tmp_path / ".lociaction").mkdir()
    # 各ルールは MAX_IGNORE_PATTERN_LENGTH(256) をほぼ使い切り、末尾の必須文字
    # ("b" + rule 固有の桁)を含めないことで、必ず失敗探索になる最悪ケースにする。
    def _build_pattern(index: int) -> str:
        suffix = f"b{index}"
        # 256 ルール分の合計が MAX_IGNORE_FILE_BYTES(64KiB) に収まるよう、
        # MAX_IGNORE_PATTERN_LENGTH(256) いっぱいではなく少し余裕を持たせる。
        remaining = 245 - len(suffix) - 3  # 3 個の "*" 分を差し引く
        filler = "a" * (remaining // 3)
        return f"*{filler}*{filler}*{filler}{suffix}"

    rules = "\n".join(_build_pattern(i) for i in range(256))
    (tmp_path / ".lociaction" / "ignore").write_text(rules + "\n")

    matcher = load_ignore(tmp_path)
    adversarial_segment = "a" * 1024

    started = time.monotonic()
    result = matcher.matches(adversarial_segment)
    elapsed = time.monotonic() - started

    assert result is False
    assert elapsed < 10.0

def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text(
        "# secrets\n\n  \nsecrets/*\n"
    )
    matcher = load_ignore(tmp_path)
    assert matcher.matches("secrets/api_key.txt") is True
    assert matcher.matches("# secrets") is False


def test_negation_re_includes_a_later_pattern(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("secrets/*\n!secrets/public.txt\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("secrets/api_key.txt") is True
    assert matcher.matches("secrets/public.txt") is False


def test_matches_any_true_if_one_path_matches(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("secrets/*\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches_any(["src/foo.py", "secrets/api_key.txt"]) is True
    assert matcher.matches_any(["src/foo.py", "src/bar.py"]) is False
    assert matcher.matches_any([]) is False


def test_overlong_ignore_pattern_is_skipped(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("a" * 300 + "\n*.pem\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("certs/server.pem") is True
    assert matcher.matches("a" * 300) is False


def test_oversized_ignore_file_is_ignored_as_a_whole(tmp_path: Path) -> None:
    """上限を超える ignore ファイルは、末尾の有効ルールも採用しない。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_bytes(
        b"#" + b"x" * (64 * 1024) + b"\n*.pem\n"
    )

    assert load_ignore(tmp_path).matches("certs/server.pem") is False


def test_ignore_rule_limit_discards_rules_after_limit(tmp_path: Path) -> None:
    """ルール数上限より後のルールは処理せず、評価量を固定する。"""
    (tmp_path / ".lociaction").mkdir()
    ignored = "\n".join(f"ignored-{index}" for index in range(256))
    (tmp_path / ".lociaction" / "ignore").write_text(f"{ignored}\n*.pem\n")

    assert load_ignore(tmp_path).matches("certs/server.pem") is False


def test_ignore_rule_limit_warns_when_rules_are_dropped(tmp_path, capsys) -> None:
    """上限を超えて切り捨てられた有効な行がある場合、無言ではなく警告を出す
    (LOCI-IGNORE-RULECAP-SILENT-01)。"""
    (tmp_path / ".lociaction").mkdir()
    ignored = "\n".join(f"ignored-{index}" for index in range(256))
    (tmp_path / ".lociaction" / "ignore").write_text(f"{ignored}\n*.pem\n")

    load_ignore(tmp_path)

    assert "more than 256" in capsys.readouterr().err


def test_ignore_rule_limit_no_warning_when_nothing_is_dropped(tmp_path, capsys) -> None:
    """ちょうど上限までしかルールが無い場合は、警告を出さない（false positive 回避）。"""
    (tmp_path / ".lociaction").mkdir()
    exactly_at_cap = "\n".join(f"ignored-{index}" for index in range(256))
    (tmp_path / ".lociaction" / "ignore").write_text(exactly_at_cap + "\n")

    load_ignore(tmp_path)

    assert capsys.readouterr().err == ""


def test_excessive_wildcard_ignore_pattern_is_skipped(tmp_path: Path) -> None:
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("*" * 20 + "x\n*.pem\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("certs/server.pem") is True
    assert matcher.matches("xxxxxxxxxxxxxxxxxxxx") is False


def test_adjacent_wildcard_segment_pattern_is_skipped(tmp_path: Path) -> None:
    """多数の `*` が単一文字を挟んで隣接する行は、総数キャップ以下でも
    catastrophic backtracking の形なので拒否する(LOCI-IGNORE-REDOS-01)"""
    (tmp_path / ".lociaction").mkdir()
    adjacency_pattern = "a*" * 8 + "a"
    (tmp_path / ".lociaction" / "ignore").write_text(adjacency_pattern + "\n*.pem\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("certs/server.pem") is True


def test_empty_negated_char_class_does_not_crash(tmp_path: Path) -> None:
    """`[!]` は negation marker 直後の `]` を literal な closing bracket と
    誤解釈すると `[^]` という不正な正規表現になり re.compile が例外を投げる
    (loci-ignore-charclass-crash)。パターンごと捨てて他のルールは維持する。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("[!]\n*.pem\n")
    matcher = load_ignore(tmp_path)
    assert matcher.matches("certs/server.pem") is True
    assert matcher.matches("a" * 9) is False


def test_matches_memoizes_repeated_identical_path_queries(tmp_path: Path) -> None:
    """同じ正規化 path を繰り返し問い合わせても、rule ごとの DP sweep は
    1回しか実行しない（LOCI-IGNORE-AGGREGATE-DOS-01）。"""
    from lociaction import ignore as ignore_mod

    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("*.pem\n")
    matcher = load_ignore(tmp_path)

    call_count = 0
    original_matches = ignore_mod._Rule.matches

    def _counting_matches(self, path: str) -> bool:
        nonlocal call_count
        call_count += 1
        return original_matches(self, path)

    ignore_mod._Rule.matches = _counting_matches
    try:
        for _ in range(5):
            assert matcher.matches("certs/server.pem") is True
    finally:
        ignore_mod._Rule.matches = original_matches

    assert call_count == 1


def test_matches_any_reuses_cache_across_overlapping_path_sets(tmp_path: Path) -> None:
    """`matches_any()` を複数回、path が重複する集合で呼んでも、重複分は
    キャッシュヒットになる（LOCI-IGNORE-AGGREGATE-DOS-01）。"""
    from lociaction import ignore as ignore_mod

    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("*.pem\n")
    matcher = load_ignore(tmp_path)

    call_count = 0
    original_matches = ignore_mod._Rule.matches

    def _counting_matches(self, path: str) -> bool:
        nonlocal call_count
        call_count += 1
        return original_matches(self, path)

    ignore_mod._Rule.matches = _counting_matches
    try:
        assert matcher.matches_any(["src/a.py", "certs/server.pem"]) is True
        assert matcher.matches_any(["certs/server.pem", "src/b.py"]) is True
    finally:
        ignore_mod._Rule.matches = original_matches

    # certs/server.pem は2回問い合わせられるが、1回目で見つかった matches が
    # any() を短絡させるため、rule 評価は distinct path (src/a.py,
    # certs/server.pem) の2件分だけ。2回目の呼び出しはキャッシュヒットの
    # certs/server.pem だけで any() が即 True を返し、src/b.py は評価されない。
    assert call_count == 2


def test_matches_cache_is_bounded_under_many_distinct_paths(tmp_path: Path) -> None:
    """distinct path を大量に投入しても `_match_cache` は無制限に肥大しない
    （LOCI-IGNORE-AGGREGATE-DOS-01 の cache 導入自体が新たな DoS にならない
    ことの確認）。"""
    (tmp_path / ".lociaction").mkdir()
    (tmp_path / ".lociaction" / "ignore").write_text("*.pem\n")
    matcher = load_ignore(tmp_path)

    for index in range(matcher._MATCH_CACHE_MAX_ENTRIES + 500):
        matcher.matches(f"src/file-{index}.py")

    assert len(matcher._match_cache) <= matcher._MATCH_CACHE_MAX_ENTRIES
