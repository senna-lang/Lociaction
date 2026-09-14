"""find_project_root の探索動作と親ディレクトリ通知のテスト"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lociaction.paths import db_path, find_project_root


def _mock_git_root(monkeypatch, root):
    """git_root() を固定値返却にモックする（テスト中は実 git を呼ばない）"""
    monkeypatch.setattr("lociaction.paths.git_root", lambda: root)


def test_find_project_root_uses_cwd_when_initialized(tmp_path, monkeypatch, capsys):
    """cwd 直下に .lociaction/ がある場合は cwd を返し、通知を出さない"""
    (tmp_path / ".lociaction").mkdir()
    _mock_git_root(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)

    root = find_project_root()
    captured = capsys.readouterr()

    assert root == tmp_path
    assert "parent directory" not in captured.err


def test_db_path_rejects_symlinked_lociaction_directory(tmp_path: Path) -> None:
    """プロジェクト状態をリポジトリ外へ redirect する symlink を拒否する。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".lociaction").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        db_path(tmp_path)

def test_find_project_root_walks_to_parent_with_notice(tmp_path, monkeypatch, capsys):
    """サブディレクトリで実行時、親の .lociaction/ を拾った場合は stderr に通知"""
    (tmp_path / ".lociaction").mkdir()
    sub = tmp_path / "sub"
    sub.mkdir()
    _mock_git_root(monkeypatch, tmp_path)
    monkeypatch.chdir(sub)

    root = find_project_root()
    captured = capsys.readouterr()

    assert root == tmp_path
    assert "parent directory" in captured.err
    assert str(tmp_path) in captured.err


def test_find_project_root_notify_false_suppresses_notice(
    tmp_path, monkeypatch, capsys
):
    """notify=False で親通知を抑止できる"""
    (tmp_path / ".lociaction").mkdir()
    sub = tmp_path / "sub"
    sub.mkdir()
    _mock_git_root(monkeypatch, tmp_path)
    monkeypatch.chdir(sub)

    root = find_project_root(notify=False)
    captured = capsys.readouterr()

    assert root == tmp_path
    assert captured.err == ""


def test_find_project_root_uninitialized_returns_git_root_silently(
    tmp_path, monkeypatch, capsys
):
    """git 内で .lociaction/ が見つからない場合は git root を返し、通知も出さない

    （呼び出し側が db.exists() で "Not initialized" を出す責務を持つ）
    """
    sub = tmp_path / "sub"
    sub.mkdir()
    _mock_git_root(monkeypatch, tmp_path)
    monkeypatch.chdir(sub)

    root = find_project_root()
    captured = capsys.readouterr()

    assert root == tmp_path
    assert captured.err == ""


def test_find_project_root_does_not_cross_git_root(tmp_path, monkeypatch, capsys):
    """別プロジェクト（git root 外）の .lociaction/ は拾わない"""
    # 親（git 管理外）に .lociaction/ を配置
    (tmp_path / ".lociaction").mkdir()

    # 子に独立した git リポジトリ
    inner = tmp_path / "inner_repo"
    inner.mkdir()
    _mock_git_root(monkeypatch, inner)
    monkeypatch.chdir(inner)

    root = find_project_root()
    captured = capsys.readouterr()

    # inner の git root が返り、外の .lociaction/ は無視される
    assert root == inner
    assert "parent directory" not in captured.err


def test_find_project_root_non_git_does_not_walk_parent(
    tmp_path, monkeypatch, capsys
):
    """git 外のサブディレクトリでは親探索しない"""
    (tmp_path / ".lociaction").mkdir()
    sub = tmp_path / "sub"
    sub.mkdir()

    _mock_git_root(monkeypatch, None)
    monkeypatch.chdir(sub)

    root = find_project_root()
    captured = capsys.readouterr()

    # cwd を返す（親の .lociaction/ は拾わない）
    assert root == sub
    assert captured.err == ""


def test_resolve_grok_sessions_path_percent_encodes_project_root(
    tmp_path: Path, monkeypatch
) -> None:
    """grok は cwd の絶対パスを percent-encode（`/` も `%2F`）したディレクトリ名を使う。"""
    from urllib.parse import quote

    from lociaction.paths import resolve_grok_sessions_path

    home = tmp_path / "home"
    project_root = tmp_path / "work" / "myrepo"
    session_dir = home / ".grok" / "sessions" / quote(str(project_root), safe="")
    (session_dir / "019f-abcd").mkdir(parents=True)
    (session_dir / "019f-abcd" / "updates.jsonl").write_text("{}\n")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert resolve_grok_sessions_path(project_root) == session_dir


def test_resolve_grok_sessions_path_returns_none_for_unknown_project(
    tmp_path: Path, monkeypatch
) -> None:
    """セッションが無いプロジェクトでは None を返す（誤って別プロジェクトを拾わない）。"""
    from lociaction.paths import resolve_grok_sessions_path

    home = tmp_path / "home"
    (home / ".grok" / "sessions").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert resolve_grok_sessions_path(tmp_path / "work" / "other") is None


def test_find_project_root_resolves_symlinked_cwd_before_comparing_to_git_root(
    tmp_path, monkeypatch, capsys
):
    """symlink 配下の cwd でも resolve() してから git_root() と比較するため、
    break 条件 `p == root` が成立し、リポジトリ外の `.lociaction/` を拾わない。

    実 OS の os.getcwd() は通常シンボリックリンクを解決済みで返すため、ここでは
    バグを意図的に再現するために Path.cwd() を未解決のシンボリックリンクパスに
    差し替える（issue #27）。
    """
    # 別プロジェクト（git リポジトリ外）の .lociaction/
    (tmp_path / ".lociaction").mkdir()

    real_repo = tmp_path / "real_repo"
    real_repo.mkdir()
    symlinked_cwd = tmp_path / "link_repo"
    symlinked_cwd.symlink_to(real_repo)

    _mock_git_root(monkeypatch, real_repo)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: symlinked_cwd))

    root = find_project_root()
    captured = capsys.readouterr()

    assert root == real_repo
    assert "parent directory" not in captured.err


def test_resolve_claude_projects_path_folds_non_alnum_like_claude_does(
    tmp_path: Path, monkeypatch
) -> None:
    """Claude Code は "/" だけでなく "." など英数字以外の文字全般を "-" へ畳んだ
    ディレクトリ名を使う。project_root に "." を含む場合でも実セッション
    ディレクトリを見つけられる（issue #27）。

    期待値は実装と同じ非英数字置換ルールで組み立てる。tmp_path の絶対パス自体に
    "_" などの記号が含まれる環境依存の値であっても、テストが環境非依存に成立する
    ようにするため（"/" のみの単純な置換では tmp_path 由来の "_" を考慮できず、
    このテスト環境では一致しない）。
    """
    import re

    from lociaction.paths import resolve_claude_projects_path

    claude_projects = tmp_path / "claude_projects"
    project_root = tmp_path / "work" / "my.repo.v1"
    project_root.mkdir(parents=True)

    encoded_name = re.sub(r"[^a-zA-Z0-9]", "-", str(project_root))
    session_dir = claude_projects / encoded_name
    session_dir.mkdir(parents=True)
    (session_dir / "session.jsonl").write_text(
        json.dumps({"cwd": str(project_root)}) + "\n"
    )

    monkeypatch.setattr("lociaction.paths.CLAUDE_PROJECTS_DIR", claude_projects)

    assert resolve_claude_projects_path(project_root) == session_dir

    # "/" のみを置換する旧実装ではヒットしないことを明示（回帰確認）
    naive_encoded_name = str(project_root).replace("/", "-")
    assert naive_encoded_name != encoded_name


def test_resolve_claude_projects_path_rejects_colliding_foreign_session_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """slug 衝突した候補でも、記録済み cwd が別 root のログは採用しない。"""
    import re

    from lociaction.paths import resolve_claude_projects_path

    project_root = tmp_path / "work" / "a-b"
    foreign_root = tmp_path / "work" / "a" / "b"
    project_root.mkdir(parents=True)
    foreign_root.mkdir(parents=True)
    session_dir = tmp_path / "claude_projects" / re.sub(
        r"[^a-zA-Z0-9]", "-", str(project_root)
    )
    session_dir.mkdir(parents=True)
    (session_dir / "foreign.jsonl").write_text(
        json.dumps({"cwd": str(foreign_root)}) + "\n"
    )
    monkeypatch.setattr("lociaction.paths.CLAUDE_PROJECTS_DIR", session_dir.parent)

    assert resolve_claude_projects_path(project_root) is None


def test_resolve_omp_sessions_path_rejects_colliding_foreign_session_dir(
    tmp_path: Path, monkeypatch
) -> None:
    """OMP の slug 衝突でも session envelope の cwd と一致しなければ採用しない。"""
    from lociaction.paths import resolve_omp_pi_sessions_path

    home = tmp_path / "home"
    project_root = home / "work" / "a-b"
    foreign_root = home / "work" / "a" / "b"
    project_root.mkdir(parents=True)
    foreign_root.mkdir(parents=True)
    session_dir = home / ".omp" / "agent" / "sessions" / "-work-a-b"
    session_dir.mkdir(parents=True)
    (session_dir / "foreign.jsonl").write_text(
        json.dumps({"type": "session", "cwd": str(foreign_root)}) + "\n"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert resolve_omp_pi_sessions_path(project_root) is None


def test_session_file_matches_project_root_bounds_oversized_line_reads(
    tmp_path: Path,
) -> None:
    """改行の無い巨大な1行があっても、読み取りは1行あたりの上限で打ち切る
    (LOCI-SESSION-READLINE-UNBOUNDED)。"""
    from lociaction.paths import (
        MAX_SESSION_METADATA_LINE_BYTES,
        session_file_matches_project_root,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    session_path = tmp_path / "huge.jsonl"
    oversized_line = "x" * (MAX_SESSION_METADATA_LINE_BYTES * 40)
    session_path.write_text(oversized_line)

    assert session_file_matches_project_root(session_path, project_root) is False


def test_session_file_matches_project_root_finds_cwd_after_oversized_line(
    tmp_path: Path,
) -> None:
    """打ち切られた巨大行の直後に正しい cwd 行があれば、それは検出できる。"""
    from lociaction.paths import (
        MAX_SESSION_METADATA_LINE_BYTES,
        session_file_matches_project_root,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    session_path = tmp_path / "session.jsonl"
    oversized_line = "x" * (MAX_SESSION_METADATA_LINE_BYTES * 2)
    session_path.write_text(
        oversized_line + "\n" + json.dumps({"cwd": str(project_root)}) + "\n"
    )

    assert session_file_matches_project_root(session_path, project_root) is True


def test_session_file_matches_project_root_skips_fifo_without_blocking(
    tmp_path: Path,
) -> None:
    """FIFO を仕込まれても open() でブロックせず、即座に非一致として扱う
    (LOCI-PATHS-SESSIONOPEN-BLOCK-01)。"""
    import os as os_module

    from lociaction.paths import session_file_matches_project_root

    project_root = tmp_path / "project"
    project_root.mkdir()
    fifo_path = tmp_path / "planted.jsonl"
    os_module.mkfifo(fifo_path)

    assert session_file_matches_project_root(fifo_path, project_root) is False


def test_session_file_matches_project_root_rejects_fifo_swapped_after_stat(
    tmp_path: Path, monkeypatch
) -> None:
    """stat 後に FIFO へ差し替えられても、descriptor の fstat が検出して
    block せず非一致にする（LOCI-PATHS-SESSION-STAT-OPEN-TOCTOU-01）。"""
    import os as os_module

    import lociaction.paths as paths_mod

    project_root = tmp_path / "project"
    project_root.mkdir()
    regular_file = tmp_path / "regular.jsonl"
    regular_file.write_text("{}\n")
    fifo_path = tmp_path / "swapped.jsonl"
    os_module.mkfifo(fifo_path)
    regular_stat = regular_file.stat()
    original_stat = Path.stat

    monkeypatch.setattr(
        Path,
        "stat",
        lambda self: regular_stat if self == fifo_path else original_stat(self),
    )

    assert paths_mod.session_file_matches_project_root(fifo_path, project_root) is False


def test_session_file_matches_project_root_skips_deeply_nested_json(
    tmp_path: Path,
) -> None:
    """小さくても深くネストした JSON metadata で session discovery を落とさない
    （LOCI-PATHS-SESSION-JSON-NESTING-DOS）。"""
    from lociaction.paths import session_file_matches_project_root

    project_root = tmp_path / "project"
    project_root.mkdir()
    session_path = tmp_path / "nested.jsonl"
    session_path.write_text("[" * 4_000 + "]" * 4_000 + "\n")

    assert session_file_matches_project_root(session_path, project_root) is False


def test_session_file_matches_project_root_skips_symlink_loop_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    """attacker-controlled cwd の path resolution が失敗しても session discovery を
    止めず、非一致として扱う（CWE-248）。"""
    from lociaction.paths import session_file_matches_project_root

    project_root = tmp_path / "project"
    project_root.mkdir()
    loop = tmp_path / "loop"
    loop.symlink_to(loop.name)
    session_path = tmp_path / "session.jsonl"
    session_path.write_text(json.dumps({"cwd": str(loop)}) + "\n")
    original_resolve = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda self: (
            (_ for _ in ()).throw(RuntimeError("Symlink loop"))
            if self == loop
            else original_resolve(self)
        ),
    )

    assert session_file_matches_project_root(session_path, project_root) is False


def test_resolve_opencode_db_path_rejects_fifo_and_symlink(tmp_path: Path, monkeypatch) -> None:
    """fixed OpenCode DB path が FIFO/symlink なら SQLite へ渡さない
    （LOCI-PATHS-OPENCODE-DB-SPECIALFILE-01）。"""
    import os as os_module

    import lociaction.paths as paths_mod

    db_dir = tmp_path / ".local" / "share" / "opencode"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "opencode.db"
    os_module.mkfifo(db_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert paths_mod.resolve_opencode_db_path() is None

    db_path.unlink()
    target = tmp_path / "outside.db"
    target.write_text("not a database")
    db_path.symlink_to(target)

    assert paths_mod.resolve_opencode_db_path() is None


def test_session_files_for_project_filters_via_bounded_rglob(
    tmp_path: Path, monkeypatch
) -> None:
    """session_files_for_project は `_bounded_rglob` が返した候補だけを検証する
    （実際のエントリ数上限は `_bounded_rglob` 自体が担う。
    LOCI-PATHS-SESSIONSCAN-TREEWALK-UNBOUNDED）。"""
    import lociaction.paths as paths_mod

    project_root = tmp_path / "project"
    project_root.mkdir()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    decoy = session_dir / "decoy.jsonl"
    decoy.write_text("{}\n")
    matching = session_dir / "matching.jsonl"
    matching.write_text(json.dumps({"cwd": str(project_root)}) + "\n")

    # _bounded_rglob が decoy しか返さない（cap に達して matching へ届かなかった
    # 状況を模す）場合、呼び出し側はそれ以上を探しに行かない。
    monkeypatch.setattr(
        paths_mod, "_bounded_rglob", lambda directory, pattern: iter((decoy,))
    )

    result = paths_mod.session_files_for_project(session_dir, project_root)

    assert result == []


def test_has_project_session_filters_via_bounded_rglob(
    tmp_path: Path, monkeypatch
) -> None:
    """_has_project_session も `_bounded_rglob` が返した候補だけを検証する。"""
    import lociaction.paths as paths_mod

    project_root = tmp_path / "project"
    project_root.mkdir()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()

    decoy = session_dir / "decoy.jsonl"
    decoy.write_text("{}\n")

    monkeypatch.setattr(
        paths_mod, "_bounded_rglob", lambda directory, pattern: iter((decoy,))
    )

    assert paths_mod._has_project_session(session_dir, project_root) is False


def test_bounded_rglob_caps_total_entries_visited_not_just_matches(
    tmp_path: Path,
) -> None:
    """マッチがほとんど無い巨大なツリーでも、訪問エントリ総数の上限で打ち切る
    （マッチ数だけを絞る itertools.islice ではこのケースを防げなかった。
    LOCI-PATHS-SESSIONSCAN-TREEWALK-UNBOUNDED）。"""
    import lociaction.paths as paths_mod

    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    # cap を大きく超える数の非マッチ空ディレクトリを作る。
    for i in range(50):
        (session_dir / f"empty-{i}").mkdir()
    # マッチするファイルは無い。

    results = list(paths_mod._bounded_rglob(session_dir, "*.jsonl", max_entries=10))

    assert results == []

def test_loci_bin_prefers_venv_binary_when_present(
    tmp_path: Path, monkeypatch
) -> None:
    """venv 配下に loci が存在する場合はそれを優先する（PATH 非依存の従来動作を維持）。"""
    from lociaction.paths import loci_bin

    fake_python = tmp_path / "venv" / "bin" / "python3"
    fake_python.parent.mkdir(parents=True)
    venv_loci = fake_python.parent / "loci"
    venv_loci.write_text("#!/bin/sh\n")

    monkeypatch.setattr("lociaction.paths.sys.executable", str(fake_python))
    monkeypatch.setattr(
        "lociaction.paths.shutil.which", lambda name: "/should/not/be/used"
    )

    assert loci_bin() == str(venv_loci)


def test_loci_bin_falls_back_to_which_under_pipx_install(
    tmp_path: Path, monkeypatch
) -> None:
    """venv 配下に loci が無い場合（pipx/global インストール）、
    shutil.which("loci") にフォールバックする（issue #27）。
    """
    from lociaction.paths import loci_bin

    fake_python = tmp_path / "some_venv" / "bin" / "python3"
    fake_python.parent.mkdir(parents=True)
    global_loci = tmp_path / "usr_local_bin" / "loci"
    global_loci.parent.mkdir(parents=True)
    global_loci.write_text("#!/bin/sh\n")

    monkeypatch.setattr("lociaction.paths.sys.executable", str(fake_python))
    monkeypatch.setattr(
        "lociaction.paths.shutil.which",
        lambda name: str(global_loci) if name == "loci" else None,
    )

    assert loci_bin() == str(global_loci)


def test_loci_bin_normalizes_relative_which_result_to_absolute(
    tmp_path: Path, monkeypatch
) -> None:
    """shutil.which("loci") が PATH の "." や空要素起因で相対パス
    （例: "loci", "./loci"）を返しても、絶対パスへ正規化してから返す。

    この戻り値はグローバル Claude 設定の hook command へそのまま永続化される
    ため、相対パスのままだと後で別の cwd から実行された際に解決先が変わる、
    または解決できず失敗する（issue #27 レビュー指摘）。
    """
    from lociaction.paths import loci_bin

    fake_python = tmp_path / "some_venv" / "bin" / "python3"
    fake_python.parent.mkdir(parents=True)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    real_loci = project_dir / "loci"
    real_loci.write_text("#!/bin/sh\n")

    monkeypatch.setattr("lociaction.paths.sys.executable", str(fake_python))
    # PATH に "." が含まれる場合の shutil.which の典型的な戻り値を模倣する
    monkeypatch.setattr("lociaction.paths.shutil.which", lambda name: "loci")
    monkeypatch.chdir(project_dir)

    result = loci_bin()

    assert Path(result).is_absolute()
    assert result == str(real_loci.resolve())


def test_loci_bin_warns_when_unresolved(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """venv にも PATH にも loci が見つからない場合、stderr に警告しつつ
    従来の venv パスをフォールバックとして返す（issue #27）。
    """
    from lociaction.paths import loci_bin

    fake_python = tmp_path / "some_venv" / "bin" / "python3"
    fake_python.parent.mkdir(parents=True)

    monkeypatch.setattr("lociaction.paths.sys.executable", str(fake_python))
    monkeypatch.setattr("lociaction.paths.shutil.which", lambda name: None)

    result = loci_bin()
    captured = capsys.readouterr()

    assert result == str(fake_python.parent / "loci")
    assert "Warning" in captured.err
