"""loci CLI エントリポイント — app 定義・サブコマンド登録に加え、`init` 実装（プロジェクト
初期化・AGENTS.md 注入・蒸留クライアント選択の対話プロンプト）を持つ（CLAUDE.md 構成表と一致、issue #39）。"""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from lociaction.indexer import Exchange

import typer

from lociaction.cli.distill_cmd import distill
from lociaction.cli.docs_cmd import docs_app
from lociaction.cli.eval_cmd import eval_app
from lociaction.cli.gc_cmd import gc
from lociaction.cli.hook_cmd import hook_app
from lociaction.cli.index_cmd import index
from lociaction.cli.prime_cmd import prime
from lociaction.cli.recall_cmd import recall
from lociaction.cli.search_cmd import context, search
from lociaction.cli.server_cmd import server_app
from lociaction.cli.show_cmd import dump, show
from lociaction.cli.status_cmd import status
from lociaction.utils import sanitize_terminal_text

_HELP_EPILOG = (
    "Coding agent? Run `loci docs list` to discover version-matched documentation. "
    "Use `loci docs show troubleshooting` when diagnosing an error."
)

app = typer.Typer(
    help="CLI-first memory layer for AI coding agents",
    epilog=_HELP_EPILOG,
    no_args_is_help=True,
)

DEFAULT_DISTILL_RECENT = 50

_BANNER = """██     ███   ████ █████  ███   ████ █████ █████  ███  ██  ██
██    ██ ██ ██      ██  ██ ██ ██      ██    ██  ██ ██ ███ ██
██    ██ ██ ██      ██  █████ ██      ██    ██  ██ ██ ██████
██    ██ ██ ██      ██  ██ ██ ██      ██    ██  ██ ██ ██ ███
█████  ███   ████ █████ ██ ██  ████   ██  █████  ███  ██  ██"""

_GRADIENT_BLUE = ["#7bb8ff", "#6aafff", "#4a9eff", "#2f70d0", "#1b45a8"]


def _print_banner() -> None:
    """init コマンド冒頭のバナーを Panel で表示する"""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    from lociaction import __version__

    console = Console(soft_wrap=True)

    content = Text()
    for line, color in zip(_BANNER.split("\n"), _GRADIENT_BLUE, strict=True):
        content.append(line + "\n", style=f"bold {color}")
    content.append("\n")
    content.append("● ", style="bright_cyan")
    content.append("code-aware and semantic recall for your coding agent", style="dim")
    content.append("   ")
    content.append(f"v{__version__}", style="dim cyan")

    console.print(Panel(content, border_style="blue", padding=(1, 3), expand=False))


def _cleanup_partial_lociaction_dir(lociaction_dir: Path, dir_preexisted: bool) -> None:
    """init 実行フェーズが失敗した際、今回新規作成した .lociaction/ のみ掃除する。
    ユーザーが事前に作成していたディレクトリ（dir_preexisted=True）は削除しない。
    """
    if not dir_preexisted:
        shutil.rmtree(lociaction_dir, ignore_errors=True)


def _ensure_lociaction_ignored(root: Path) -> None:
    """`.lociaction/` を root の .gitignore に、実効的に無視される状態で追加する。

    既存ファイルの改行形式と末尾改行の有無を保つため、内容を正規化せず追記する。

    symlink チェックと書き込みを1つの os.open(O_NOFOLLOW) 呼び出しへまとめる。
    別々の is_symlink() チェックと write_text()/open("a") では、その間に symlink を
    仕込まれる TOCTOU window が生まれる（LOCI-GITIGNORE-TOCTOU）。
    """
    from lociaction.ignore import MAX_IGNORE_FILE_BYTES, parse_ignore_rules

    gitignore_path = root / ".gitignore"
    try:
        fd = os.open(str(gitignore_path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(
                f"refusing symlinked .gitignore: {gitignore_path}"
            ) from exc
        raise

    with os.fdopen(fd, "r+", encoding="utf-8", newline="") as gitignore:
        # 攻撃者制御の既存 .gitignore を無制限に全文読み込まない
        # (LOCI-GITIGNORE-UNBOUNDED-READ)。上限を超える場合は既存ルールを
        # 検証しようとせず、末尾に無条件で自分のルールを追記する
        # （末尾に付けた否定なしパターンは last-match-wins で必ず勝つため、
        # 全文を読めなくても安全に正しい状態へ収束する）。
        content = gitignore.read(MAX_IGNORE_FILE_BYTES + 1)
        if len(content) > MAX_IGNORE_FILE_BYTES:
            gitignore.seek(0, os.SEEK_END)
            gitignore.write("\n.lociaction/\n")
            return

        # 実際の gitignore の優先順位規則（最後に一致した行が勝つ・否定行）で
        # 実効的に無視されているかを判定する。単純な文字列一致では、攻撃者が
        # `.lociaction/` の直後に `!.lociaction/` を仕込んで無効化できてしまう
        # (LOCI-GITIGNORE-NEGATION-BYPASS)。
        if parse_ignore_rules(content).matches(".lociaction/memory.db"):
            return

        if not content:
            suffix = ".lociaction/\n"
        elif content.endswith("\r\n"):
            suffix = ".lociaction/\r\n"
        elif content.endswith("\n"):
            suffix = ".lociaction/\n"
        elif content.endswith("\r"):
            suffix = ".lociaction/\r"
        elif "\r\n" in content:
            suffix = "\r\n.lociaction/"
        elif "\n" in content:
            suffix = "\n.lociaction/"
        elif "\r" in content:
            suffix = "\r.lociaction/"
        else:
            suffix = "\n.lociaction/"

        gitignore.write(suffix)


def _version_callback(value: bool) -> None:
    if value:
        from lociaction import __version__

        typer.echo(f"lociaction {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = False,
) -> None:
    """CLI-first memory layer for AI coding agents."""


@app.command()
def init(
    skip_existing: Annotated[
        bool,
        typer.Option("--skip-existing", help="Skip distillation of existing exchanges"),
    ] = False,
    distill_limit: Annotated[
        int | None,
        typer.Option(
            "--distill-limit",
            help="Distill only the most recent N existing exchanges",
        ),
    ] = None,
    min_chars: Annotated[
        int | None,
        typer.Option(
            "--min-chars",
            help="Index-time minimum character filter (prompted if omitted)",
        ),
    ] = None,
    no_hooks: Annotated[
        bool,
        typer.Option("--no-hooks", help="Skip automatic Claude Code hook registration"),
    ] = False,
    no_local_distiller: Annotated[
        bool,
        typer.Option(
            "--no-local-distiller",
            help="Skip the offer to pull the local distillation model",
        ),
    ] = False,
    distill_client: Annotated[
        str | None,
        typer.Option(
            "--distill-client",
            help=(
                "Select a distill client non-interactively (llamacpp-ft | "
                "claude-cli | codex-cli | gemini-cli | grok-cli | opencode-cli | "
                "omp-cli). Exits with an error if that client is not ready"
            ),
        ),
    ] = None,
) -> None:
    """Initialize `.lociaction/memory.db` in the project root."""
    from lociaction.db import get_connection, init_db
    from lociaction.indexer import index_file, parse_exchanges
    from lociaction.paths import (
        db_path,
        find_project_root,
        open_dir_relative,
        resolve_claude_projects_path,
        session_files_for_project,
    )

    _print_banner()

    root = find_project_root()
    db = db_path(root)

    if db.exists():
        typer.echo(f"Already initialized: {db}")
        return

    # 既存セッションの検出
    target_dir = resolve_claude_projects_path(root)
    jsonl_files = session_files_for_project(target_dir, root) if target_dir else []

    # --- 対話フェーズ（DB 作成前にすべての質問を完了する） ---
    resolved_min_chars = 50
    skip_count = 0
    skip_strategy = "recent"
    total_exchanges = 0
    run_distill_now = False
    parsed_exchanges_by_file: dict[Path, list[Exchange]] = {}

    if jsonl_files:
        # min_chars=0 で全ファイルを一度だけフルパースし、閾値集計・総数カウント・
        # 実インデックスの3箇所で使い回す（同一ファイルの3重パースを避ける、issue #25）
        parsed_exchanges_by_file = {
            jsonl: parse_exchanges(jsonl, min_chars=0) for jsonl in jsonl_files
        }
        all_exchanges = [ex for exs in parsed_exchanges_by_file.values() for ex in exs]

        resolved_min_chars = _resolve_min_chars(all_exchanges, min_chars)

        total_exchanges = sum(
            1
            for ex in all_exchanges
            if len(ex.user_content) + len(ex.agent_content) >= resolved_min_chars
        )

        if total_exchanges > 0:
            skip_count, skip_strategy = _resolve_skip_count(
                total_exchanges, skip_existing, distill_limit
            )

            distill_count = total_exchanges - skip_count
            if distill_count > 0:
                run_distill_now = _ask_run_distill_now(distill_count)

    chosen_client = _resolve_init_distill_client(
        root,
        no_local_distiller=no_local_distiller,
        distill_client_flag=distill_client,
    )

    # --- 実行フェーズ（ここから DB・ファイルを作成） ---
    # 失敗時は作成した .lociaction/ を掃除して次回再実行できる状態に戻す
    lociaction_dir = db.parent
    dir_preexisted = lociaction_dir.exists()
    try:
        _ensure_lociaction_ignored(root)
        init_db(db)

        config_path = lociaction_dir / "config.toml"
        # Path.exists() はダングリング symlink を「存在しない」と報告するため、
        # そのまま分岐に使うと write_text() が symlink をたどって外部ファイルへ
        # 書き込んでしまう (LOCI-INIT-CONFIGTOML-SYMLINK-TOCTOU)。O_NOFOLLOW で
        # 存在確認そのものを行い、symlink なら中身の有無に関わらず即座に拒否する。
        # open_dir_relative は親 `.lociaction/` 自体の symlink すり替えにも
        # 都度対応する (LOCI-REGISTRY-CONFIGDIR-TOCTOU-01)。
        try:
            probe_fd = open_dir_relative(
                config_path.parent, config_path.name, os.O_RDONLY
            )
        except FileNotFoundError:
            config_exists = False
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ValueError(
                    f"refusing symlinked config file: {config_path}"
                ) from exc
            raise
        else:
            os.close(probe_fd)
            config_exists = True

        if not config_exists:
            if chosen_client is not None:
                from lociaction.adapters.model.registry import write_client_config

                write_client_config(config_path, chosen_client)
                # write_client_config は既定で [distill]/[index] のみ生成する。
                # init 由来のコメント（batch_limit/min_chars 案内）を後段に追記する。
                # write_client_config は O_NOFOLLOW で作成済みだが、ここで別の
                # read_text()/write_text() で開き直すとその間に symlink を
                # 仕込まれる TOCTOU window が生まれるため、単一の
                # os.open(O_NOFOLLOW) セッションで読み書きする。
                try:
                    append_fd = open_dir_relative(
                        config_path.parent, config_path.name, os.O_RDWR
                    )
                except OSError as exc:
                    if exc.errno == errno.ELOOP:
                        raise ValueError(
                            f"refusing symlinked config file: {config_path}"
                        ) from exc
                    raise
                with os.fdopen(append_fd, "r+") as f:
                    content = f.read()
                    f.seek(0)
                    f.truncate()
                    f.write(
                        content.rstrip("\n")
                        + "\n"
                        + "# batch_limit = 20\n"
                        + "# min_chars = 100   # この文字数未満の exchange は蒸留スキップ\n"
                    )
            else:
                try:
                    create_fd = open_dir_relative(
                        config_path.parent,
                        config_path.name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o644,
                    )
                except FileExistsError:
                    pass  # probe 以降に別プロセスが作成済み: 既存 config を尊重する
                except OSError as exc:
                    if exc.errno == errno.ELOOP:
                        raise ValueError(
                            f"refusing symlinked config file: {config_path}"
                        ) from exc
                    raise
                else:
                    with os.fdopen(create_fd, "w") as f:
                        f.write(
                            "# Lociaction configuration\n"
                            "\n"
                            "[distill]\n"
                            "# distill client が未設定です。次のコマンドで選択してください:\n"
                            "#   loci distill --setup\n"
                            "#\n"
                            '# client = "llamacpp-ft"     # llama-server + speculative decoding（ローカル FT）\n'
                            '# client = "claude-cli"      # Claude CLI (claude --print)\n'
                            '# client = "codex-cli"       # Codex CLI (codex exec)\n'
                            '# client = "gemini-cli"      # Gemini CLI (gemini --prompt)\n'
                            '# client = "grok-cli"        # Grok CLI (grok -p)\n'
                            '# client = "opencode-cli"    # OpenCode (opencode run)\n'
                            '# client = "omp-cli"         # Oh My Pi (omp -p)\n'
                            '# model = "..."\n'
                            '# base_url = "..."           # loopback only; remote needs LOCIACTION_REMOTE_DISTILL_ORIGINS\n'
                            "# batch_limit = 20\n"
                            "# min_chars = 100   # この文字数未満の exchange は蒸留スキップ\n"
                            "\n"
                            "[index]\n"
                            "# min_chars = 50   # trivial フィルタ閾値（文字数）\n"
                        )

        typer.echo(f"Initialized: {db}")
    except KeyboardInterrupt:
        typer.echo("\n⚠ Interrupted. Cleaning up partial state...", err=True)
        _cleanup_partial_lociaction_dir(lociaction_dir, dir_preexisted)
        raise typer.Exit(code=130) from None
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"\n⚠ init failed: {sanitize_terminal_text(str(exc))}", err=True)
        typer.echo("Cleaning up partial state...", err=True)
        _cleanup_partial_lociaction_dir(lociaction_dir, dir_preexisted)
        raise typer.Exit(code=1) from None

    # --- AGENTS.md 注入（.lociaction/ の作成成否とは独立した副作用なので、
    #     失敗しても既に作成済みの DB/config を rmtree で巻き込まない。#17）---
    from lociaction.cli.prime_cmd import inject_agents_md

    try:
        if inject_agents_md(root):
            typer.echo(f"Updated: {root / 'AGENTS.md'} (lociaction section)")
    except KeyboardInterrupt:
        typer.echo(
            "\n⚠ Interrupted while updating AGENTS.md. "
            "The database was created successfully.",
            err=True,
        )
        raise typer.Exit(code=130) from None
    except Exception as exc:  # noqa: BLE001
        typer.echo(
            f"\n⚠ AGENTS.md update failed: {sanitize_terminal_text(str(exc))}\n"
            "The database was created successfully — fix AGENTS.md manually.",
            err=True,
        )

    # --- 既存 exchange のインデックス化（失敗時は今回作成分の .lociaction/ を掃除） ---
    try:
        if total_exchanges > 0:
            actual_total = 0
            for jsonl in jsonl_files:
                try:
                    filtered = [
                        ex
                        for ex in parsed_exchanges_by_file[jsonl]
                        if len(ex.user_content) + len(ex.agent_content)
                        >= resolved_min_chars
                    ]
                    actual_total += index_file(
                        jsonl,
                        db,
                        min_chars=resolved_min_chars,
                        preparsed_exchanges=filtered,
                        project_root=root,
                    )
                except Exception as exc:  # noqa: BLE001
                    typer.echo(
                        f"  ⚠ skip {sanitize_terminal_text(jsonl.name)}: "
                        f"{sanitize_terminal_text(str(exc))}",
                        err=True,
                    )

            typer.echo(f"Indexed {actual_total} existing exchange(s).")

            if skip_count > 0:
                order_clause = (
                    "ORDER BY LENGTH(user_content) + LENGTH(agent_content) ASC"
                    if skip_strategy == "longest"
                    else "ORDER BY ply_start ASC"
                )
                con = get_connection(db)
                try:
                    con.execute(
                        f"""
                        UPDATE exchanges SET distilled_at = 'skipped', distill_status = 'skipped'
                        WHERE distilled_at IS NULL
                        AND id IN (
                            SELECT id FROM exchanges
                            WHERE distilled_at IS NULL
                            {order_clause}
                            LIMIT ?
                        )
                        """,
                        (skip_count,),
                    )
                    con.commit()
                finally:
                    con.close()
                remaining = actual_total - skip_count
                typer.echo(
                    f"Marked {skip_count} exchange(s) as skipped. "
                    f"{remaining} will be distilled."
                )
            else:
                typer.echo(f"All {actual_total} exchange(s) will be distilled.")
    except KeyboardInterrupt:
        typer.echo("\n⚠ Interrupted. Cleaning up partial state...", err=True)
        _cleanup_partial_lociaction_dir(lociaction_dir, dir_preexisted)
        raise typer.Exit(code=130) from None
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"\n⚠ init failed: {sanitize_terminal_text(str(exc))}", err=True)
        typer.echo("Cleaning up partial state...", err=True)
        _cleanup_partial_lociaction_dir(lociaction_dir, dir_preexisted)
        raise typer.Exit(code=1) from None

    # --- Hook 自動登録（opt-out 可、失敗は警告のみで続行） ---
    if not no_hooks:
        try:
            from lociaction.config import load_config
            from lociaction.hooks import install_hooks

            cfg = load_config(root)
            _changed, message = install_hooks(batch_limit=cfg.distill_batch_limit)
            typer.echo(message)
        except Exception as exc:  # noqa: BLE001
            typer.echo(
                f"\n⚠ Hook install failed: {sanitize_terminal_text(str(exc))}\n"
                "Retry later with: loci hook install",
                err=True,
            )

    # --- 蒸留フェーズ（失敗しても DB は残す: 後で loci distill で再試行可） ---
    if run_distill_now:
        from lociaction.cli.progress import DistillationProgress
        from lociaction.embedder import EmbedderSetupError
        from lociaction.llm import DistillUnconfiguredError

        progress = DistillationProgress()
        try:
            from lociaction.config import load_config
            from lociaction.distiller import distill_all
            from lociaction.llm import DistillBackend

            cfg = load_config(root)
            typer.echo("Running distillation...")

            def _on_progress(cur: int, tot: int, error: str | None = None) -> None:
                progress.update(cur, tot, error)

            backend = (
                DistillBackend(
                    provider=chosen_client.provider,
                    model=chosen_client.model,
                    base_url=chosen_client.base_url,
                    client_id=chosen_client.id,
                )
                if chosen_client is not None
                else DistillBackend.from_config(cfg)
            )
            from lociaction.adapters.model.llama_server import LlamaServerError
            from lociaction.cli.distill_cmd import bind_runtime_backend
            from lociaction.distiller import has_pending_work

            if has_pending_work(db, distill_min_chars=cfg.distill_min_chars):
                try:
                    with bind_runtime_backend(backend, root) as bound:
                        count, err_count = distill_all(
                            db,
                            backend=bound,
                            on_progress=_on_progress,
                            project_root=str(root),
                            distill_min_chars=cfg.distill_min_chars,
                        )
                except LlamaServerError as exc:
                    typer.echo(sanitize_terminal_text(str(exc)), err=True)
                    raise typer.Exit(code=1) from None
            else:
                count, err_count = distill_all(
                    db,
                    backend=backend,
                    on_progress=_on_progress,
                    project_root=str(root),
                    distill_min_chars=cfg.distill_min_chars,
                )
            progress.finish()
            typer.echo(f"Distilled {count} exchange(s).")
            if err_count > 0:
                typer.echo(
                    f"{err_count} exchange(s) failed — see errors above.", err=True
                )
        except KeyboardInterrupt:
            typer.echo(
                "\n⚠ Distillation interrupted. "
                "Indexed exchanges remain — resume with: loci distill",
                err=True,
            )
            raise typer.Exit(code=130) from None
        except DistillUnconfiguredError:
            from lociaction.cli.errors import DISTILLATION_DOCS

            typer.echo(
                "\nDistill client is not configured — skipping distillation.\n"
                "Configure and retry with: loci distill --setup\n"
                f"{DISTILLATION_DOCS}",
                err=True,
            )
        except EmbedderSetupError as exc:
            typer.echo(
                f"\n⚠ {sanitize_terminal_text(str(exc))}\n"
                "Indexed exchanges remain — retry with: loci distill "
                "after fixing the environment.",
                err=True,
            )
            raise typer.Exit(code=1) from None
        except Exception as exc:  # noqa: BLE001
            typer.echo(
                f"\n⚠ Distillation failed: {sanitize_terminal_text(str(exc))}\n"
                "Indexed exchanges remain — retry with: loci distill",
                err=True,
            )
            raise typer.Exit(code=1) from None
        finally:
            progress.finish()


_MIN_CHARS_CANDIDATES = [50, 100, 200, 500]


def _count_exchanges_by_threshold(
    exchanges: list[Exchange], thresholds: list[int]
) -> dict[int, int]:
    """各閾値ごとの exchange 件数をカウントする。呼び出し側が min_chars=0 で
    パース済みの exchange リストを渡す（同一ファイルの再パースを避けるため、issue #25）。"""
    lengths = [len(ex.user_content) + len(ex.agent_content) for ex in exchanges]
    return {t: sum(1 for length in lengths if length >= t) for t in thresholds}


def _prompt_choice(valid: set[str], default: str = "1") -> str:
    """有効な値が入力されるまで再プロンプトする"""
    sorted_valid = sorted(valid, key=lambda s: (len(s), s))
    while True:
        choice = typer.prompt("Choice", default=default).strip()
        if choice in valid:
            return choice
        typer.echo(f"  Invalid choice. Please enter one of: {', '.join(sorted_valid)}")


def _prompt_int_range(prompt: str, min_v: int, max_v: int | None = None) -> int:
    """範囲制約付きの整数プロンプト。範囲外は再入力。"""
    while True:
        n = typer.prompt(prompt, type=int)
        if n < min_v:
            typer.echo(f"  Must be ≥ {min_v}.")
            continue
        if max_v is not None and n > max_v:
            typer.echo(f"  Must be ≤ {max_v}.")
            continue
        return n


def _resolve_min_chars(exchanges: list[Exchange], min_chars_flag: int | None) -> int:
    """init 時の min_chars を決定する。フラグ指定済みならそのまま、未指定なら対話。"""
    if min_chars_flag is not None:
        return min_chars_flag

    counts = _count_exchanges_by_threshold(exchanges, _MIN_CHARS_CANDIDATES)

    # exchange が0件なら対話不要
    if counts.get(_MIN_CHARS_CANDIDATES[0], 0) == 0:
        return _MIN_CHARS_CANDIDATES[0]

    typer.echo("\nMin chars threshold for existing exchanges:")
    for i, threshold in enumerate(_MIN_CHARS_CANDIDATES, 1):
        label = " (default)" if threshold == 50 else ""
        typer.echo(f"  [{i}] {threshold} chars{label} — {counts[threshold]} exchanges")
    custom_idx = len(_MIN_CHARS_CANDIDATES) + 1
    typer.echo(f"  [{custom_idx}] Custom")

    valid = {str(i) for i in range(1, custom_idx + 1)}
    choice = _prompt_choice(valid)

    for i, threshold in enumerate(_MIN_CHARS_CANDIDATES, 1):
        if choice == str(i):
            return threshold

    # Custom
    return _prompt_int_range("Min chars threshold?", min_v=0)


def _ask_run_distill_now(distill_count: int) -> bool:
    """蒸留を今すぐ実行するか聞く。y/n/1/2 を受け付ける。"""
    typer.echo(
        f"\nStart distillation now? ({distill_count} exchanges, "
        "uses an LLM and may consume tokens)"
    )
    typer.echo("  [1] No — distill on next session start (default)")
    typer.echo("  [2] Yes — run now")

    while True:
        choice = typer.prompt("Choice", default="1").strip().lower()
        if choice in ("1", "n", "no"):
            return False
        if choice in ("2", "y", "yes"):
            return True
        typer.echo("  Invalid choice. Please enter 1/2/y/n.")


def _resolve_init_distill_client(
    root: Path, *, no_local_distiller: bool, distill_client_flag: str | None
):
    """discover → Ready+setupable 一覧 → 選択。

    Returns: 選ばれた ModelClient、または unconfigured を意味する None。
    `--distill-client` 明示指定時は Ready でなければ setup を試み、それでも
    Ready でなければエラー終了する（別 client に落とさない）。
    """
    from lociaction.adapters.model.registry import (
        DISCOVERABLE_CLIENT_IDS,
        check_ready,
        setup,
    )
    from lociaction.cli.distill_cmd import (
        _warn_if_remote_grant_missing,
        prompt_client_selection,
    )

    if distill_client_flag is not None:
        if distill_client_flag not in DISCOVERABLE_CLIENT_IDS:
            typer.echo(
                "Unknown distill client: "
                f"{sanitize_terminal_text(distill_client_flag)}",
                err=True,
            )
            raise typer.Exit(code=1)
        status = check_ready(distill_client_flag)
        if status.state == "setupable":
            ok, msg = setup(distill_client_flag)
            typer.echo(msg)
            if not ok:
                raise typer.Exit(code=1)
            status = check_ready(distill_client_flag)
        if status.state != "ready" or status.client is None:
            typer.echo(
                f"--distill-client {distill_client_flag} is not ready: {status.reason}",
                err=True,
            )
            raise typer.Exit(code=1)
        _warn_if_remote_grant_missing(status.client.id)
        return status.client

    return prompt_client_selection(root, include_setupable=not no_local_distiller)


def _ask_distill_priority() -> str:
    """蒸留対象の優先順位を選択する。"""
    typer.echo("\nDistill priority:")
    typer.echo("  [1] Recent — newest exchanges first")
    typer.echo("  [2] Longest — longest exchanges first")

    choice = _prompt_choice({"1", "2"})
    return "longest" if choice == "2" else "recent"


def _resolve_skip_count(
    total: int, skip_existing: bool, distill_limit: int | None
) -> tuple[int, str]:
    """スキップする exchange 数と優先順位を決定する。フラグ or 対話プロンプト。

    Returns: (skip_count, strategy) where strategy is "recent" or "longest"
    """
    if skip_existing:
        return total, "recent"
    if distill_limit is not None:
        skip = max(0, total - distill_limit)
        strategy = _ask_distill_priority() if skip > 0 else "recent"
        return skip, strategy

    # 対話プロンプト
    typer.echo(
        f"\nFound {total} existing exchanges from past sessions.\n"
        "Distillation uses an LLM — Claude by default, or Codex/Gemini/Grok/"
        "OpenCode/Oh My Pi/a local model if you pick one next — "
        "and may consume tokens.\n"
        "⚠ Skipped exchanges cannot be distilled later.\n"
    )
    typer.echo("How should existing exchanges be handled?")
    typer.echo("  [1] Skip all — only distill future sessions")
    typer.echo(f"  [2] Distill last {DEFAULT_DISTILL_RECENT} — recent history only")
    typer.echo(f"  [3] Distill all — {total} exchanges (token consumption)")
    typer.echo("  [4] Custom — specify how many exchanges to distill")

    choice = _prompt_choice({"1", "2", "3", "4"})

    if choice == "1":
        return total, "recent"
    if choice == "3":
        return 0, "recent"

    if choice == "2":
        skip = max(0, total - DEFAULT_DISTILL_RECENT)
    else:  # "4": Custom
        n = _prompt_int_range("How many exchanges to distill?", min_v=1, max_v=total)
        skip = max(0, total - n)

    strategy = _ask_distill_priority() if skip > 0 else "recent"
    return skip, strategy


app.command()(index)
app.command()(distill)
app.command()(search)
app.command()(gc)
app.command()(context)
app.command()(recall)
app.command()(status)
app.command()(show)
app.command()(dump)
app.command()(prime)
app.add_typer(docs_app, name="docs")
app.add_typer(hook_app, name="hook")
app.add_typer(server_app, name="server")
app.add_typer(eval_app, name="eval")
