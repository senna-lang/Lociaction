"""パス解決ヘルパー: プロジェクトルート・DB パス・Claude セッションログパスの解決"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
LOCIACTION_DIR = ".lociaction"
DB_NAME = "memory.db"
MAX_SESSION_METADATA_LINES = 32
MAX_SESSION_METADATA_LINE_BYTES = 64 * 1024


def open_dir_relative(directory: Path, name: str, flags: int, mode: int = 0o644) -> int:
    """`directory` を O_DIRECTORY|O_NOFOLLOW で開いてから、その fd を基点に `name`
    を openat 相当で開く。

    呼び出し側が別の時点で確認した Path をそのまま `os.open(str(path))` すると、
    確認から書き込みまでの間に親ディレクトリが symlink にすり替えられる TOCTOU
    window が残る（leaf 側の O_NOFOLLOW は最終コンポーネントしか守らない）。
    dir_fd 経由の openat はこのレースを構造的に閉じる
    (LOCI-REGISTRY-CONFIGDIR-TOCTOU-01)。`directory` 自身が symlink の場合は
    ELOOP をそのまま呼び出し側へ伝える（leaf の symlink 拒否と同じ errno で
    統一的に扱えるようにするため）。
    """
    dir_fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # leaf 自体の symlink 拒否も常に強制する。呼び出し側が O_NOFOLLOW を
        # 渡し忘れても、この関数を使う意味（symlink 安全な open）が失われない
        # ようにするため。
        return os.open(name, flags | os.O_NOFOLLOW, mode, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)


def session_file_matches_project_root(session_path: Path, project_root: Path) -> bool:
    """JSONL session の記録済み cwd が active project root と一致する場合だけ True を返す。

    Claude/OMP の保存ディレクトリ名は lossy な slug なので、それだけで他プロジェクトの
    session を選択してはならない。cwd を記録しない古い/破損ログは fail-closed で除外する。

    session log は攻撃者（侵害された/悪意あるコーディングエージェント）が書ける前提の
    未信頼データなので、行数だけでなく1行あたりの読み取りバイト数も上限を設ける
    （readline() に size を渡さないと、改行を含まない単一の巨大行が丸ごとメモリに
    載ってしまう。LOCI-SESSION-READLINE-UNBOUNDED）。上限に達しても改行が来ない行は
    打ち切り、JSON として解釈せずそのチャンクを読み捨てて次のチャンクへ進む。

    同じ攻撃者制御ディレクトリには FIFO（名前付きパイプ）を仕込むこともできる。
    leaf を Path.stat() してから名前で開くと、その間に FIFO へ差し替えられる
    TOCTOU でもブロックしうる。親 directory fd を no-follow で固定した後、
    leaf を O_NONBLOCK で一度だけ開き、同じ descriptor を fstat/read する
    (LOCI-PATHS-SESSIONOPEN-BLOCK-01 / LOCI-PATHS-SESSION-STAT-OPEN-TOCTOU-01)。
    """
    fd = -1
    try:
        fd = open_dir_relative(
            session_path.parent,
            session_path.name,
            os.O_RDONLY | os.O_NONBLOCK,
        )
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return False
        expected_root = project_root.resolve()
        with os.fdopen(fd, encoding="utf-8", errors="replace") as session_file:
            fd = -1
            for _ in range(MAX_SESSION_METADATA_LINES):
                raw_line = session_file.readline(MAX_SESSION_METADATA_LINE_BYTES)
                if not raw_line:
                    break
                if (
                    len(raw_line) >= MAX_SESSION_METADATA_LINE_BYTES
                    and not raw_line.endswith("\n")
                ):
                    # 行が上限を超えて打ち切られた: 中途半端な JSON 断片として
                    # 解釈せず読み捨てる（fail-closed）。同じ物理行の残りは
                    # 次のチャンクとして読まれ、budget を消費し続ける。
                    continue
                try:
                    entry = json.loads(raw_line)
                except (json.JSONDecodeError, MemoryError, RecursionError):
                    continue
                if not isinstance(entry, dict):
                    continue
                cwd = entry.get("cwd")
                if not isinstance(cwd, str):
                    continue
                recorded_root = Path(cwd)
                return (
                    recorded_root.is_absolute()
                    and recorded_root.resolve() == expected_root
                )
    except (OSError, RuntimeError):
        # Path.resolve() は loop を RuntimeError として報告することがある。
        # session metadata 内の cwd は未信頼なので、解決不能なら非一致に倒す。
        return False
    finally:
        if fd != -1:
            os.close(fd)
    return False


# harness session directory は侵害/悪意ある coding agent が書き込める前提の
# 未信頼領域なので、decoy な .jsonl を大量生成して以降の `loci` 呼び出し全てを
# 比例的に重くする flooding も、1行あたり・1ファイルあたりの上限だけでは
# 防げない。`Path.rglob()` は遅延評価の再帰 generator で、`itertools.islice`
# は「消費したマッチ数」だけを絞る——マッチがほとんど無い巨大なディレクトリ
# ツリー（大量の空フォルダ等）では、N件目のマッチ（または0件確定）に届く
# までに経路上の全エントリを辿る必要があり、この cap は機能しない
# (LOCI-PATHS-SESSIONSCAN-TREEWALK-UNBOUNDED)。訪問した「エントリ総数」
# そのものに上限を設けた自前の bounded walk に置き換える。
MAX_SESSION_FILES_SCANNED = 4096


def _bounded_rglob(directory: Path, pattern: str, max_entries: int = MAX_SESSION_FILES_SCANNED):
    """`directory` 配下を再帰的に walk し、`pattern`（`fnmatch` 形式、`/` を
    含まない単純なファイル名パターンのみ想定）に一致するファイルを yield する。

    `os.scandir` を明示的なスタックで再帰し、訪問した「エントリ総数」が
    `max_entries` に達したら即座に打ち切る。symlink ディレクトリは辿らない
    （ループ回避、かつ攻撃者制御ツリーへ抜け出させない）。
    """
    visited = 0
    stack = [directory]
    while stack and visited < max_entries:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if visited >= max_entries:
                        return
                    visited += 1
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif fnmatch.fnmatch(entry.name, pattern):
                            yield Path(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue


def _has_project_session(candidate: Path, project_root: Path) -> bool:
    """candidate 配下に active root を明示した session が1つでもあるかを返す。"""
    return any(
        session_file_matches_project_root(session_path, project_root)
        for session_path in _bounded_rglob(candidate, "*.jsonl")
    )


def session_files_for_project(
    directory: Path, project_root: Path, pattern: str = "*.jsonl"
) -> list[Path]:
    """lossy harness directory から active project に属する JSONL だけを返す。"""
    return [
        session_path
        for session_path in _bounded_rglob(directory, pattern)
        if session_file_matches_project_root(session_path, project_root)
    ]


def lociaction_dir(project_root: Path) -> Path:
    """project-local state directory を返す。symlink は外部への書込みを防ぐため拒否する。"""
    state_dir = project_root / LOCIACTION_DIR
    if state_dir.is_symlink():
        raise ValueError(f"refusing symlinked {LOCIACTION_DIR} directory: {state_dir}")
    if state_dir.exists() and not state_dir.is_dir():
        raise ValueError(f"{LOCIACTION_DIR} must be a directory: {state_dir}")
    return state_dir


def git_root() -> Path | None:
    """git rev-parse --show-toplevel でリポジトリルートを返す。git 外/未インストールなら None"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def find_project_root(notify: bool = True) -> Path:
    """.lociaction/ を探してプロジェクトルートを返す。
    検索順: cwd → 親ディレクトリ（git root まで）
    git root を超えて遡らないことでプロジェクト外の DB を拾わない。

    cwd 以外（親）で `.lociaction/` を発見した場合は stderr に注意書きを出す。
    意図せず親プロジェクトの DB を共有していることに気付けるようにするため。
    notify=False で抑止可能（テスト・機械処理用途）。

    cwd は resolve() してから git_root()（実パス）と比較する。symlink 配下の
    cwd を未解決のまま使うと、`p == root` の break 条件が一致せず走査が
    git root を超えて続き、リポジトリ外の `.lociaction/` を拾いうる（issue #27）。
    """
    cwd = Path.cwd().resolve()
    root = git_root()
    if root:
        candidates = [cwd, *cwd.parents]
        for p in candidates:
            if (p / LOCIACTION_DIR).exists():
                if notify and p != cwd:
                    print(
                        f"Note: using .lociaction/ from parent directory: {p}",
                        file=sys.stderr,
                    )
                return p
            if p == root:
                break
        return root
    else:
        # git 外: cwd のみ探索（親を遡ると別プロジェクトの DB を拾う）
        if (cwd / LOCIACTION_DIR).exists():
            return cwd
        return cwd


def db_path(project_root: Path) -> Path:
    return lociaction_dir(project_root) / DB_NAME


def resolve_claude_projects_path(project_root: Path) -> Path | None:
    """project_root の Claude session directory を、記録済み cwd で検証して返す。

    Claude Code はパス中の英数字以外の文字（"/" や "." を含む）をすべて "-" に
    変換したディレクトリ名を使う。slug は衝突し得るため、候補内の各 JSONL は
    `session_files_for_project()` でさらに active root に絞り込む必要がある。
    """
    if not CLAUDE_PROJECTS_DIR.exists():
        return None
    dir_name = re.sub(r"[^a-zA-Z0-9]", "-", str(project_root))
    candidate = CLAUDE_PROJECTS_DIR / dir_name
    if candidate.is_dir() and _has_project_session(candidate, project_root):
        return candidate
    return None


def resolve_codex_sessions_path() -> Path | None:
    """Codex rollout JSONL を格納する既定セッションディレクトリを返す。"""
    path = Path.home() / ".codex" / "sessions"
    if path.exists() and any(_bounded_rglob(path, "rollout-*.jsonl")):
        return path
    return None


def resolve_opencode_db_path() -> Path | None:
    """OpenCode の固定 SQLite DB を regular non-symlink file に限って返す。

    OpenCode state は外部プロセスが更新するため、FIFO/symlink 等を SQLite へ渡して
    block や意図しない読取りを起こさない（LOCI-PATHS-OPENCODE-DB-SPECIALFILE-01）。
    """
    path = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
    fd = -1
    try:
        fd = open_dir_relative(
            path.parent, path.name, os.O_RDONLY | os.O_NONBLOCK
        )
        return path if stat.S_ISREG(os.fstat(fd).st_mode) else None
    except OSError:
        return None
    finally:
        if fd != -1:
            os.close(fd)


def resolve_omp_pi_sessions_path(project_root: Path) -> Path | None:
    """project_root の OMP session directory を、session envelope の cwd で検証して返す。

    omp-pi はホーム相対パスを "-" でつないだ slug を使う。slug は衝突し得るため、
    候補内の JSONL は `session_files_for_project()` で active root に絞り込む。
    """
    home = Path.home().resolve()
    sessions_dir = home / ".omp" / "agent" / "sessions"
    if not sessions_dir.exists():
        return None
    try:
        project_root = project_root.resolve()
        relative = project_root.relative_to(home)
    except (OSError, RuntimeError, ValueError):
        return None
    candidate = sessions_dir / ("-" + "-".join(relative.parts))
    if candidate.is_dir() and _has_project_session(candidate, project_root):
        return candidate
    return None


def resolve_grok_sessions_path(project_root: Path) -> Path | None:
    """project_root に対応する ~/.grok/sessions/<percent-encoded-path>/ を解決する。

    grok は作業ディレクトリの絶対パスをそのまま percent-encode した
    （`/` も `%2F` に変換する）ディレクトリ名を使う。実体のログはさらにその下の
    `<session-uuid>/updates.jsonl` にあるため、存在確認は再帰で行う。
    """
    sessions_dir = Path.home() / ".grok" / "sessions"
    if not sessions_dir.exists():
        return None

    for base in (project_root, Path.cwd()):
        candidate = sessions_dir / quote(str(base), safe="")
        if candidate.exists() and any(_bounded_rglob(candidate, "updates.jsonl")):
            return candidate
    return None


SOCK_FILENAME = "embedder.sock"
PID_FILENAME = "embedder.pid"


def sock_path(project_root: Path) -> Path:
    return db_path(project_root).parent / SOCK_FILENAME


def server_pid_path(project_root: Path) -> Path:
    return db_path(project_root).parent / PID_FILENAME


def loci_bin() -> str:
    """loci バイナリのフルパスを返す。
    まず sys.executable と同じ venv の bin/loci を探し、無ければ PATH 上の
    `loci`（shutil.which）にフォールバックする。venv 外（pipx/global install）
    での実行では venv 内に loci が存在しないため（issue #27）。
    どちらも見つからない場合は venv パスを返しつつ stderr に警告する。

    shutil.which() の結果は PATH に "." や空要素が含まれると相対パス
    （例: "./loci", "loci"）になり得る。この戻り値はグローバル Claude 設定の
    hook command へそのまま永続化されるため、相対パスのままだと後で別の cwd
    から実行された際に解決先が変わる、または解決できず失敗する。永続化前に
    必ず絶対パスへ正規化する（issue #27 レビュー指摘）。
    """
    venv_bin = Path(sys.executable).parent / "loci"
    if venv_bin.exists():
        return str(venv_bin)

    which_bin = shutil.which("loci")
    if which_bin:
        return str(Path(which_bin).resolve())

    print(
        f"Warning: could not locate `loci` binary (checked {venv_bin} and PATH); "
        "hooks referencing it may fail to run",
        file=sys.stderr,
    )
    return str(venv_bin)
