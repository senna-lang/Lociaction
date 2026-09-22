"""lifecycle_commands() の正規定義を検証する（design doc §4.1・issue #40）。

harness ごとに「どのイベントで何を実行するか」を再定義していた重複
（旧 ClaudeHooks/CodexHooks の別々のコマンド構築）を1箇所へ集約したことを、
harness を変えても on_turn_end に `--harness {harness}` だけが変わり、
残りのコマンド構造は共有される、という契約として確認する。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from lociaction.adapters.harness.lifecycle import lifecycle_commands


def test_on_turn_end_scopes_index_to_the_calling_harness() -> None:
    codex_cmds = lifecycle_commands("codex", batch_limit=20)
    omp_cmds = lifecycle_commands("omp-pi", batch_limit=20)

    assert "index --harness codex" in codex_cmds.on_turn_end
    assert "index --harness omp-pi" in omp_cmds.on_turn_end
    # コマンドの構造自体（binary 呼び出し部分）は共通
    assert codex_cmds.on_turn_end.replace("codex", "omp-pi") == omp_cmds.on_turn_end


def test_on_session_start_returns_server_distill_prime_in_order() -> None:
    cmds = lifecycle_commands("grok", batch_limit=42)
    server_cmd, distill_cmd, prime_cmd = cmds.on_session_start

    assert "server start" in server_cmd
    assert "nohup " in server_cmd
    assert "&" in server_cmd

    assert "distill" in distill_cmd
    assert "--limit 42" in distill_cmd
    assert "nohup " in distill_cmd
    assert "&" in distill_cmd

    assert prime_cmd.endswith("prime); fi")
    assert "nohup " not in prime_cmd


def test_on_compact_is_guarded_prime() -> None:
    cmds = lifecycle_commands("claude", batch_limit=20)
    assert cmds.on_compact.endswith("prime); fi")


def test_batch_limit_is_cast_to_int() -> None:
    cmds = lifecycle_commands("codex", batch_limit="15")  # type: ignore[arg-type]
    assert "--limit 15" in cmds.on_session_start[1]


def test_different_harnesses_share_identical_session_start_shape() -> None:
    """5つの harness 全てで on_session_start の構造（何をいつ実行するか）が同一。"""
    for harness in ("claude", "codex", "omp-pi", "opencode", "grok"):
        cmds = lifecycle_commands(harness, batch_limit=20)
        assert len(cmds.on_session_start) == 3
        server_cmd, distill_cmd, prime_cmd = cmds.on_session_start
        assert "server start" in server_cmd
        for command in (server_cmd, distill_cmd, prime_cmd):
            assert command.startswith('__loci_root="$(git rev-parse')
        assert "distill --limit 20" in distill_cmd
        assert prime_cmd.endswith("prime); fi")


def test_hooks_skip_uninitialized_project_and_run_from_git_root(
    tmp_path: Path, monkeypatch
) -> None:
    """グローバルな harness hook でも init 済みの project 以外では loci を起動しない。"""
    fake_loci = tmp_path / "loci"
    log = tmp_path / "invocations"
    fake_loci.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n")
    fake_loci.chmod(0o755)
    monkeypatch.setattr(
        "lociaction.adapters.harness.lifecycle.loci_bin", lambda: str(fake_loci)
    )

    project = tmp_path / "project"
    nested = project / "src"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    command = lifecycle_commands("omp-pi", batch_limit=20).on_turn_end

    subprocess.run(command, shell=True, cwd=nested, check=True)
    assert not log.exists()

    (project / ".lociaction").mkdir()
    subprocess.run(command, shell=True, cwd=nested, check=True)
    assert log.read_text().splitlines() == ["index --harness omp-pi"]
