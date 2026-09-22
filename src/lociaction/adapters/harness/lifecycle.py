"""lifecycle イベント → loci コマンドの正規定義（1箇所に集約）。

`ClaudeHooks`/`CodexHooks`/`GrokHooks`/`OmpPiHooks`/`OpenCodeHooks`
（`adapters/harness/hooks.py`、Claude は `lociaction.hooks.install_hooks`
経由）は、どの harness でも「ターン終了時に index」「session 開始時に
server/distill/prime」「compact 時に prime」という同一の知識を持っており、
以前は harness ごとにコマンド文字列をリテラルに再構築していた（design doc §1）。
この重複を無くし、上記5つの Hooks 実装はここが返す `LifecycleCommands` を
「どう書き込むか」だけに専念して消費する。

`lociaction.hooks.install_hooks`/`uninstall_hooks` は差分検出・自動修復を含む
Claude 固有の idempotency ロジックを保つが、コマンド文字列自体は
`lifecycle_commands("claude", batch_limit)` から取得する（実際の JSON への
書き込み・`Path.home` 解決は引き続き `lociaction.hooks` 側の責務）。
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from lociaction.paths import loci_bin


@dataclass(frozen=True)
class LifecycleCommands:
    """harness に依存しない、初期化済みプロジェクト限定の lifecycle コマンド。"""

    on_turn_end: str
    """ターン終了（Stop 相当）で実行する `loci index --harness {harness}`。"""

    on_session_start: tuple[str, str, str]
    """session 開始で実行する (server start, distill, prime) の3コマンド。
    server/distill は nohup で detach、prime のみ foreground（stdout をコンテキストへ注入）。"""

    on_compact: str
    """compact 完了（PostCompact 相当）で実行する `loci prime`。"""


_INITIALIZED_PROJECT_GUARD = (
    '__loci_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"; '
    'if [ -d "$__loci_root/.lociaction" ]; then '
)


def is_project_scoped_lifecycle_command(command: str) -> bool:
    """command が生成済みの initialized-project guard を含むか判定する。"""
    return command.startswith(_INITIALIZED_PROJECT_GUARD)


def _in_initialized_project(command: str) -> str:
    """Git root（git 外では cwd）の `.lociaction/` に限定して command を実行する。

    各 harness の hook 設定はユーザー領域に1つだけ置かれるため、導入後はすべての
    プロジェクトでイベントを受ける。hook 本体はここで初期化済みのプロジェクトだけを
    選び、git の subdirectory から起動した場合も `loci init` を実行した root で
    動かす。未初期化プロジェクトでは loci の server / distill / prime / index を
    一切起動しない。
    """
    return (
        _INITIALIZED_PROJECT_GUARD
        + f'(cd "$__loci_root" && {command}); '
        + "fi"
    )


def lifecycle_commands(harness: str, batch_limit: int) -> LifecycleCommands:
    """harness と蒸留バッチ上限から、project-scoped な loci hook を組み立てる。"""
    loci = shlex.quote(loci_bin())
    return LifecycleCommands(
        on_turn_end=_in_initialized_project(f"{loci} index --harness {harness}"),
        on_session_start=(
            _in_initialized_project(
                f"nohup {loci} server start > /dev/null 2>&1 &"
            ),
            _in_initialized_project(
                f"nohup {loci} distill --limit {int(batch_limit)} > /dev/null 2>&1 &"
            ),
            _in_initialized_project(f"{loci} prime"),
        ),
        on_compact=_in_initialized_project(f"{loci} prime"),
    )
