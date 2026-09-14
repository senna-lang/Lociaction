"""`.lociaction/ignore` に書かれた gitignore 風パターンでファイルパスを判定する。

verbatim 会話にはトークンやシークレットが混入し得るため、`.env` や `secrets/**` の
ように機微なファイルへ触れた exchange は索引前に弾けるようにする（issue #36）。

対応する記法（`.gitignore` のサブセット）:
  - `#` で始まる行はコメント、空行は無視する。
  - `!` を先頭に置くと、それより前の行のマッチを打ち消す（否定）。
  - `/` を含まないパターンは深さを問わず一致する（`*.pem` は `certs/x.pem` にも一致）。
  - `/` を含むパターンは `.lociaction/ignore` が置かれたプロジェクトルートからの
    相対パスとして固定される。
  - 末尾の `/` はディレクトリ配下限定（そのディレクトリ自身のパスには一致しない）。
  - ワイルドカードは `*`（`/` をまたがない）・`?`・`[...]`・`**`（`/` をまたぐ）。
  - ルールは記述順で評価し、最後にマッチしたルールの否定有無が結果を決める。

ignore パターンも検査対象パスも攻撃者制御になり得る（前者はクローンした repo が
出荷する `.lociaction/ignore`、後者は session log 由来の file_path）ため、
regex の catastrophic backtracking や再帰によるコールスタック肥大化に頼らず、
すべて多項式時間で確定するアルゴリズムだけで評価する。
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Union

from lociaction.paths import lociaction_dir

IGNORE_FILENAME = "ignore"
MAX_IGNORE_PATTERN_LENGTH = 256
MAX_IGNORE_WILDCARD_TOKENS = 16
MAX_WILDCARDS_PER_SEGMENT = 3

MAX_IGNORE_FILE_BYTES = 64 * 1024
MAX_IGNORE_RULES = 256
MAX_GLOBSTAR_SEGMENTS = 2
# 検査対象パス全体の文字数を上限で束ねる（実在の PATH_MAX 相当の考え方）。
# `_segment_fullmatch` の1回あたりコストは O(rule segment 長 * path segment 長)
# で、outer DP は rule segment ごとに全 path segment を1回ずつ評価するため、
# 総コストは「rule 全体の文字数（≤ MAX_IGNORE_PATTERN_LENGTH）× path 全体の
# 文字数」に factor される。segment 数と segment 長を別々にキャップしても、
# その積（4096×4096）は依然として攻撃者が作れてしまい、DP を導入した後も
# rule 1件あたり数十億 op 規模の計算コストが残っていた
# (LOCI-IGNORE-DP-LEAFMATCH-BLOWUP)。path 全体の文字数を1つの上限で
# 束ねることで、その積を rule 1件あたり ~256K 操作程度（256 rule でも
# 数秒以内）に確実に収める。
MAX_IGNORE_PATH_LENGTH = 1024

# 1文字ちょうどに一致する segment 内 atom（`_translate_segment_atoms` が生成）。
# - `_STAR`: `*`（0文字以上、`/` を跨がない）
# - `_ANY`: `?`（任意の1文字）
# - `str`（長さ1）: リテラル1文字
# - `re.Pattern`: `[...]` 文字クラスを1文字にだけ fullmatch する（量指定子を
#   含まないので backtracking risk が無い）
_STAR = object()
_ANY = object()
_SegmentAtom = Union[object, str, "re.Pattern[str]"]


@dataclass(frozen=True)
class _Rule:
    # "**" は None、ワイルドカードを含まない literal segment は str（完全一致で
    # 十分なので DP を経由しない高速経路）、それ以外は atom 列（DP で評価）。
    segments: tuple[str | tuple[_SegmentAtom, ...] | None, ...]
    negate: bool
    anchored: bool
    dir_only: bool

    def matches(self, path: str) -> bool:
        """globstar は bottom-up DP テーブルで評価し、regex backtracking も
        再帰によるコールスタック肥大化も避ける。"""
        path_segments = tuple(segment for segment in path.split("/") if segment)
        table = _build_match_table(self.segments, path_segments, self.dir_only)
        starts = range(1) if self.anchored else range(len(path_segments) + 1)
        return any(table[0][start] for start in starts)


def _leaf_matches(
    segment: str | tuple[_SegmentAtom, ...], text: str
) -> bool:
    """globstar ではない1 segment のパターンが `text` に完全一致するかを返す。"""
    if isinstance(segment, str):
        return segment == text
    return _segment_fullmatch(segment, text)


def _build_match_table(
    rule_segments: tuple[str | tuple[_SegmentAtom, ...] | None, ...],
    path_segments: tuple[str, ...],
    dir_only: bool,
) -> list[list[bool]]:
    """`table[r][p]` = `rule_segments[r:]` が `path_segments[p:]` に一致するか。

    依存関係が常により大きい `r`・`p` 側を向くよう、両方を降順に埋める bottom-up DP。
    再帰を使わないため、path の深さに比例したコールスタックを積まない
    （LOCI-IGNORE-GLOBSTAR-STACKDOS-01: 従来の再帰実装は非末尾の `**` 分岐で
    スタック深さが path segment 数に比例し、攻撃者が細切れの path を大量の `/`
    で作るだけで RecursionError を誘発できた）。
    """
    m = len(rule_segments)
    n = len(path_segments)
    table: list[list[bool]] = [[False] * (n + 1) for _ in range(m + 1)]
    for path_index in range(n + 1):
        table[m][path_index] = path_index < n if dir_only else True

    for rule_index in range(m - 1, -1, -1):
        segment = rule_segments[rule_index]
        row = table[rule_index]
        next_row = table[rule_index + 1]
        for path_index in range(n, -1, -1):
            if segment is None:
                if rule_index == m - 1 and rule_index > 0:
                    row[path_index] = path_index < n and next_row[path_index + 1]
                else:
                    row[path_index] = next_row[path_index] or (
                        path_index < n and row[path_index + 1]
                    )
            else:
                row[path_index] = (
                    path_index < n
                    and _leaf_matches(segment, path_segments[path_index])
                    and next_row[path_index + 1]
                )
    return table


def _segment_fullmatch(atoms: tuple[_SegmentAtom, ...], text: str) -> bool:
    """`*`/`?`/文字クラスを含む1 segment パターンを、regex ではなく古典的な
    wildcard-matching DP で評価する（LOCI-IGNORE-REDOS-POLY）。

    regex の `[^/]*` を複数個 fullmatch させると、一致しない入力に対して
    O(n^(star数+1)) の catastrophic backtracking になり得る。ここでは
    O(len(atoms) * len(text)) の bottom-up DP に置き換えることで、
    パターン・入力のどちらが攻撃者制御でも多項式時間（実質線形〜二次）に収める。
    """
    m = len(atoms)
    n = len(text)
    dp = [[False] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = True
    for i in range(1, m + 1):
        if atoms[i - 1] is _STAR:
            dp[i][0] = dp[i - 1][0]
    for i in range(1, m + 1):
        atom = atoms[i - 1]
        row = dp[i]
        prev_row = dp[i - 1]
        if atom is _STAR:
            for j in range(1, n + 1):
                row[j] = prev_row[j] or row[j - 1]
        elif atom is _ANY:
            for j in range(1, n + 1):
                row[j] = prev_row[j - 1]
        elif isinstance(atom, re.Pattern):
            for j in range(1, n + 1):
                row[j] = prev_row[j - 1] and atom.fullmatch(text[j - 1]) is not None
        else:
            for j in range(1, n + 1):
                row[j] = prev_row[j - 1] and atom == text[j - 1]
    return dp[m][n]


class IgnoreMatcher:
    """1つの ignore ファイルから読み込んだルール集合。ルール自体は不変だが、
    `matches()` の結果は正規化 path をキーに `_match_cache` へ記憶する。

    `matches()`/`matches_any()` は同じ path を何度も問い合わせる呼び出し側
    （複数 exchange が同じファイルへ触れる、`matches_any()` が重複する path
    集合を跨いで呼ばれる等）に対して、毎回 rule 全体の DP sweep を再実行して
    いた。攻撃者が問い合わせ path 自体を制御できるわけではないが、正規の
    呼び出しパターンでも同じ path が繰り返し評価されるため、キャッシュを
    持たないことは呼び出し回数に対して不必要な二次的コストを課していた
    (LOCI-IGNORE-AGGREGATE-DOS-01)。キャッシュは attacker-controlled な
    大量の distinct path で無制限に肥大しないよう上限で束ねる。
    """

    _MATCH_CACHE_MAX_ENTRIES = 4096

    def __init__(self, rules: tuple[_Rule, ...] = ()) -> None:
        self._rules = rules
        self._match_cache: dict[str, bool] = {}

    def matches(self, path: str) -> bool:
        """path（プロジェクトルート相対、区切りは `/` か `\\`）が除外対象なら True。"""
        normalized = PurePosixPath(path.replace("\\", "/")).as_posix().lstrip("/")
        if len(normalized) > MAX_IGNORE_PATH_LENGTH:
            # 攻撃者が捏造した極端に長い file_path は DP でも計算コストが
            # 無視できないため評価を打ち切るが、打ち切りを「一致しない」
            # (fail-open) として扱うと、機微ファイルの exclusion ルールを長い
            # path で迂回できてしまう (LOCI-IGNORE-LENCAP-BYPASS-01)。ルール
            # 内容や negate に関わらず、安全側に倒して常に除外対象として扱う。
            return True
        cached = self._match_cache.get(normalized)
        if cached is not None:
            return cached
        ignored = False
        for rule in self._rules:
            if rule.matches(normalized):
                ignored = not rule.negate
        if len(self._match_cache) >= self._MATCH_CACHE_MAX_ENTRIES:
            # 上限に達したら単純にクリアする（LRU 相当の精度は不要 —
            # 攻撃者制御の distinct path 大量投入でメモリが無制限に伸びない
            # ことが目的で、キャッシュヒット率の最適化は目的ではない）。
            self._match_cache.clear()
        self._match_cache[normalized] = ignored
        return ignored

    def matches_any(self, paths: Iterable[str]) -> bool:
        """paths のいずれか1つでも除外対象なら True（exchange 全体を除外する判定に使う）。"""
        return any(self.matches(path) for path in paths)


def parse_ignore_rules(text: str, *, warn_on_truncate: bool = False) -> IgnoreMatcher:
    """gitignore 風パターンのテキストから `IgnoreMatcher` を構築する。

    `.lociaction/ignore` だけでなく、実効的な ignore 状態を判定したい他の
    gitignore 風ファイル（例: `.gitignore`）の解析にも再利用する
    （LOCI-GITIGNORE-NEGATION-BYPASS: 単純な文字列一致では否定行による
    打ち消しを見逃すため、同じ「最後に一致した行が勝つ」規則で判定する）。

    `warn_on_truncate=True` なら、MAX_IGNORE_RULES を超えて切り捨てられる
    有効な行が実際に残っている場合だけ stderr に警告する
    （LOCI-IGNORE-RULECAP-SILENT-01: 手編集される `.lociaction/ignore` で
    ユーザー自身の保護ルールが無言で無視されるのを防ぐ）。
    """
    lines = text.splitlines()
    rules: list[_Rule] = []
    truncated_at: int | None = None
    for index, raw_line in enumerate(lines):
        pattern = raw_line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        rule = _compile_rule(pattern)
        if rule is not None:
            rules.append(rule)
            if len(rules) >= MAX_IGNORE_RULES:
                truncated_at = index + 1
                break
    if warn_on_truncate and truncated_at is not None:
        remaining_has_content = any(
            line.strip() and not line.strip().startswith("#")
            for line in lines[truncated_at:]
        )
        if remaining_has_content:
            print(
                f"Warning: .lociaction/ignore has more than {MAX_IGNORE_RULES} "
                "valid rules; rules beyond this limit are ignored.",
                file=sys.stderr,
            )
    return IgnoreMatcher(tuple(rules))


def load_ignore(project_root: Path) -> IgnoreMatcher:
    """`project_root/.lociaction/ignore` を読み込む。存在しなければ空の matcher を返す。

    is_symlink()/is_file() の別チェックと後続の open('rb') では、その間に
    leaf を symlink や FIFO へすり替えられる TOCTOU window が残る
    （config.toml/.gitignore/distill.lock に既に適用済みの
    open_dir_relative(openat 相当) パターンと同じ穴。
    LOCI-IGNORE-LOADIGNORE-TOCTOU）。stat() で通常ファイルであることも
    確認し、FIFO を仕込まれても open がブロックしないようにする
    （session_file_matches_project_root の LOCI-PATHS-SESSIONOPEN-BLOCK-01
    ガードと同じ考え方）。
    """
    import stat as stat_module

    from lociaction.paths import open_dir_relative

    state_dir = lociaction_dir(project_root)
    try:
        fd = open_dir_relative(
            state_dir, IGNORE_FILENAME, os.O_RDONLY | os.O_NONBLOCK
        )
    except OSError:
        # 見つからない・symlink（ELOOP）・親が壊れている等、いずれも
        # 「ignore ファイル無し」と同じ安全側のフォールバックにする。
        return IgnoreMatcher()
    try:
        try:
            st = os.fstat(fd)
            if not stat_module.S_ISREG(st.st_mode):
                return IgnoreMatcher()
            # 攻撃者制御の repo が出荷しうる巨大な ignore ファイルを全文
            # メモリに読み込んでからサイズ判定するのではなく、上限+1 byte だけ
            # 読んで即座に足切りする（LOCI-IGNORE-FILEREAD-UNBOUNDED）。
            with os.fdopen(fd, "rb") as f:
                fd = -1  # fdopen が close の責務を引き継いだ
                content = f.read(MAX_IGNORE_FILE_BYTES + 1)
        finally:
            if fd != -1:
                os.close(fd)
    except OSError:
        return IgnoreMatcher()
    if len(content) > MAX_IGNORE_FILE_BYTES:
        return IgnoreMatcher()
    return parse_ignore_rules(
        content.decode("utf-8", errors="replace"), warn_on_truncate=True
    )


def _compile_rule(pattern: str) -> _Rule | None:
    """1行の gitignore 風パターンを `_Rule` へ変換する。複雑すぎる行は捨てる。"""
    if len(pattern) > MAX_IGNORE_PATTERN_LENGTH:
        return None
    if pattern.count("*") + pattern.count("?") > MAX_IGNORE_WILDCARD_TOKENS:
        return None
    negate = pattern.startswith("!")
    if negate:
        pattern = pattern[1:]
    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]
    dir_only = pattern.endswith("/")
    if dir_only:
        pattern = pattern[:-1]

    segments = pattern.split("/")
    if segments.count("**") > MAX_GLOBSTAR_SEGMENTS:
        return None
    if any(left == right == "**" for left, right in zip(segments, segments[1:])):
        return None
    for segment in segments:
        if segment != "**" and segment.count("*") > MAX_WILDCARDS_PER_SEGMENT:
            return None
    # 内部に `/` を含む（=複数 segment になる）パターンは git 同様ルート相対に固定する。
    anchored = anchored or len(segments) > 1

    try:
        compiled_segments = tuple(
            _compile_segment(segment) for segment in segments
        )
    except re.error:
        # 想定外の文字クラス組み合わせ等で不正な正規表現になった場合、
        # そのルールだけ捨てて index/distill 全体を落とさない。
        return None
    return _Rule(
        segments=compiled_segments,
        negate=negate,
        anchored=anchored,
        dir_only=dir_only,
    )


def _compile_segment(segment: str) -> str | tuple[_SegmentAtom, ...] | None:
    """1 segment を `_Rule.segments` の要素へ変換する。

    ワイルドカードを含まない segment は文字列そのもの（完全一致、DP 不要の
    高速経路）。`**` は None。それ以外は `_translate_segment_atoms` の atom 列。
    """
    if segment == "**":
        return None
    if not any(c in segment for c in "*?["):
        return segment
    return _translate_segment_atoms(segment)


def _translate_segment_atoms(segment: str) -> tuple[_SegmentAtom, ...]:
    """`**` を含まない1つのパス segment を atom 列へ変換する（DP matcher 用）。"""
    atoms: list[_SegmentAtom] = []
    i = 0
    n = len(segment)
    while i < n:
        c = segment[i]
        if c == "*":
            atoms.append(_STAR)
            i += 1
        elif c == "?":
            atoms.append(_ANY)
            i += 1
        elif c == "[":
            end = segment.find("]", i + 1)
            if end == -1:
                atoms.append(c)
                i += 1
            else:
                char_class = segment[i : end + 1]
                if char_class == "[!]":
                    # `[!]` は negation marker 直後の `]` が literal な最初の
                    # class member ではなく、そのまま `[^` + `]` と単純結合すると
                    # 空 body の unterminated character set になり re.compile が
                    # 例外を投げる。body が空のこのケースだけエスケープして
                    # 「']' 以外の任意の1文字」として扱う。
                    char_class = "[^\\]]"
                elif char_class.startswith("[!"):
                    char_class = "[^" + char_class[2:]
                # 量指定子を含まない単一文字クラスの fullmatch は backtracking
                # risk が無い（O(class size) で確定する）。
                atoms.append(re.compile(char_class))
                i = end + 1
        else:
            atoms.append(c)
            i += 1
    return tuple(atoms)
