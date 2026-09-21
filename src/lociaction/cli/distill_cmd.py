"""loci distill コマンド — client registry 経由で ModelClient を解決して蒸留する"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import typer

from lociaction.adapters.model.types import ClientStatus, ModelClient
from lociaction.utils import sanitize_terminal_text

if TYPE_CHECKING:
    from lociaction.adapters.harness.model_catalog import HarnessModelCatalog


def _is_interactive() -> bool:
    """stdin/stdout が両方 TTY かどうか（テストで monkeypatch する用の切り出し）"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _select_harness_model(catalog: HarnessModelCatalog) -> str | None:
    """Select a live catalog when the harness exposes one, else its history.

    Claude has no documented noninteractive availability catalog.  Codex,
    Grok, OpenCode, and Oh My Pi expose one through their authenticated CLI or
    backend; a failed lookup falls back to project-local recorded model IDs.
    """
    from lociaction.adapters.harness.model_catalog import (
        discover_available_harness_models,
    )
    from lociaction.cli.interactive import prompt_text, select_index

    available_models = discover_available_harness_models(catalog.harness_id)
    if available_models is None:
        models = catalog.models
        heading = f"Models previously used by {catalog.label} in this project:"
        if catalog.harness_id != "claude":
            typer.echo(
                f"  Could not query the current {catalog.label} model catalog. "
                "Showing this project's recorded history instead."
            )
    else:
        models = available_models
        heading = f"Models currently available to this {catalog.label} account:"

    choices: list[tuple[str, str | None]] = [(model, model) for model in models]
    choices.append(("Harness default", None))
    labels = [label for label, _model in choices]
    labels.append("Custom — type a model ID")
    custom_idx = len(labels) - 1
    default = len(models)

    idx = select_index(
        (
            f"{heading}\n"
            "  Distillation is a small per-exchange task — "
            "a lower-cost model is recommended."
        ),
        labels,
        default=default,
        prompt_label="Select model",
        numbering="dot",
    )
    if idx == custom_idx:
        return prompt_text("Model ID:", prompt_label="Model ID")
    return choices[idx][1]


def _warn_if_remote_grant_missing(client_id: str) -> None:
    """Interactive selection here is explicit consent, so this run still uses
    ``client_id``. But every non-interactive invocation (hook-triggered
    `loci distill`, `loci status --check`) re-reads config.toml from disk and
    applies the same LOCIACTION_REMOTE_DISTILL_CLIENTS grant check — without it,
    those runs silently treat distillation as unconfigured (config.py)."""
    from lociaction.config import (
        REMOTE_DISTILL_CLIENTS_ENV,
        remote_client_grant_missing,
    )

    if remote_client_grant_missing(client_id):
        typer.echo(
            f"Note: '{client_id}' sends exchange text to an external CLI provider.\n"
            "This run will still use it, but background hooks (Claude Code Stop/"
            "SessionStart, etc.) re-read the saved config and treat it as "
            "unconfigured until you grant it in the environment those hooks run in:\n"
            f"  export {REMOTE_DISTILL_CLIENTS_ENV}={client_id}\n"
            "Add that to the shell profile / login environment the hook process "
            "inherits — not just this terminal session.",
            err=True,
        )


def prompt_client_selection(
    root, *, include_setupable: bool = True
) -> ModelClient | None:
    """Select a local distiller or project harness and then its model.

    A harness appears only when it has sessions for ``root`` and its matching
    distillation CLI is ready. After selection, a harness-specific live
    catalog is preferred when supported; local session history is an explicit
    fallback.
    """
    from lociaction.adapters.harness.model_catalog import (
        HarnessModelCatalog,
        discover_project_harness_models,
    )
    from lociaction.adapters.model.registry import (
        check_ready,
        discover,
        resolve_client,
        selectable_clients,
        setup,
    )
    from lociaction.cli.interactive import select_index
    from lociaction.config import load_config

    statuses = discover()
    selectable = selectable_clients(statuses, include_setupable=include_setupable)
    local_choices = [status for status in selectable if status.id == "llamacpp-ft"]
    ready_by_client = {
        status.id: status
        for status in statuses
        if status.state == "ready" and status.client is not None
    }
    harness_choices = [
        catalog
        for catalog in discover_project_harness_models(root)
        if catalog.client_id in ready_by_client
    ]
    choices: list[tuple[str, object]] = [
        *((("local", status)) for status in local_choices)
    ]
    choices.extend(("harness", catalog) for catalog in harness_choices)
    if not choices:
        typer.echo(
            "No local FT model or ready harness session was found for this project."
        )
        return None

    labels = []
    for kind, choice in choices:
        if kind == "local":
            status = cast(ClientStatus, choice)
            marks = " (needs setup)" if status.state == "setupable" else ""
            labels.append(f"{status.label} [{status.id}]{marks}")
        else:
            catalog = cast(HarnessModelCatalog, choice)
            labels.append(f"{catalog.label} [{catalog.harness_id}]")

    local_default = next(
        (i for i, (kind, _choice) in enumerate(choices) if kind == "local"),
        0,
    )
    kind, choice = choices[
        select_index(
            "Available distillation sources:",
            labels,
            default=local_default,
            prompt_label="Select source",
            numbering="dot",
        )
    ]
    if kind == "harness":
        catalog = cast(HarnessModelCatalog, choice)
        status = ready_by_client[catalog.client_id]
        client = status.client or resolve_client(status.id, load_config(root))
        client = replace(client, model=_select_harness_model(catalog))
    else:
        status = cast(ClientStatus, choice)
        if status.state == "setupable":
            ok, msg = setup(status.id)
            typer.echo(msg)
            if not ok:
                return None
            status = check_ready(status.id)
            if status.state != "ready":
                typer.echo(f"Setup did not make {status.id} ready: {status.reason}")
                return None
        client = status.client or resolve_client(status.id, load_config(root))

    _warn_if_remote_grant_missing(client.id)
    return client


def _setup_and_save(root) -> None:
    """`loci distill --setup`: 選んだ client を config.toml に書き込む"""
    from lociaction.adapters.model.registry import write_client_config
    from lociaction.paths import lociaction_dir

    client = prompt_client_selection(root)
    if client is None:
        raise typer.Exit(1)

    config_path = lociaction_dir(root) / "config.toml"
    write_client_config(config_path, client)
    typer.echo(f"Saved distill.client = {client.id}")


def _resolve_backend(cfg, root, is_tty: bool):
    """cfg から DistillBackend を解決する。

    unconfigured/not-ready のとき: TTY なら一度限りの再選択（config は書かない）、
    非対話なら None を返し呼び出し側が warn+skip する（silent auto-switch 禁止）。
    """
    from lociaction.adapters.model.registry import check_ready
    from lociaction.llm import DistillBackend, DistillUnconfiguredError

    def _from_client(client: ModelClient) -> DistillBackend:
        return DistillBackend(
            provider=client.provider,
            model=client.model,
            base_url=client.base_url,
            client_id=client.id,
        )

    try:
        backend = DistillBackend.from_config(cfg)
    except DistillUnconfiguredError:
        if not is_tty:
            from lociaction.cli.errors import DISTILLATION_DOCS

            typer.echo(
                "Distill client is not configured. Run `loci distill --setup`.",
                err=True,
            )
            typer.echo(DISTILLATION_DOCS, err=True)
            return None
        typer.echo("Distill client is not configured.")
        client = prompt_client_selection(root)
        return _from_client(client) if client else None

    assert cfg.distill_client is not None  # from_config succeeded => configured
    status = check_ready(cfg.distill_client)
    if status.state == "ready":
        return backend

    if not is_tty:
        from lociaction.cli.errors import DISTILLATION_DOCS

        typer.echo(
            f"Configured distill client '{cfg.distill_client}' is not ready "
            f"({status.reason}). Not switching automatically — run "
            "`loci distill --setup` or `loci distill` interactively.",
            err=True,
        )
        typer.echo(DISTILLATION_DOCS, err=True)
        return None

    typer.echo(
        f"Configured client '{cfg.distill_client}' is not ready: {status.reason}"
    )
    client = prompt_client_selection(root)
    return _from_client(client) if client else None


@contextmanager
def bind_runtime_backend(backend, project_root: Path) -> Iterator:
    """llamacpp-ft なら ephemeral llama-server を起動して base_url を差し替える。

    他 client は no-op。選択/セットアップの TTY ゲートとは独立 — 既設定なら
    hook 経由でもローカルプロセスの起動/停止だけを行う。
    """
    if backend.client_id != "llamacpp-ft":
        yield backend
        return
    from lociaction.adapters.model.llama_server import (
        LlamaServerProcess,
        llamacpp_concurrency_slot,
        spec_for_model,
    )
    from lociaction.llm import DistillBackend
    from lociaction.paths import lociaction_dir

    log_path = lociaction_dir(project_root) / "logs" / "llama-server.log"
    with (
        llamacpp_concurrency_slot(),
        LlamaServerProcess(spec_for_model(backend.model), log_path=log_path) as proc,
    ):
        yield DistillBackend(
            provider="openai",
            model=backend.model,
            base_url=proc.base_url,
            client_id="llamacpp-ft",
        )


def distill(
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit", "-n", help="Maximum exchanges to process (default: all)"
        ),
    ] = None,
    setup: Annotated[
        bool,
        typer.Option(
            "--setup",
            help="Discover, select, and save a distill client to config",
        ),
    ] = False,
) -> None:
    """Distill undistilled exchanges into palace objects."""
    import errno
    import fcntl
    import os

    from lociaction.config import load_config
    from lociaction.distiller import distill_all
    from lociaction.paths import db_path, find_project_root

    root = find_project_root()
    db = db_path(root)

    if not db.exists():
        from lociaction.cli.errors import abort_not_initialized

        abort_not_initialized()

    if setup:
        _setup_and_save(root)
        return

    cfg = load_config(root)
    is_tty = _is_interactive()

    lock_path = db.parent / "distill.lock"

    # ロック取得: fcntl.flock で排他ロック（LOCK_NB: 非ブロッキング）。
    # open_dir_relative（openat 相当）: .lociaction/ 配下は repo が書き込める
    # 領域なので、distill.lock 自体の symlink（config.toml に既にある同種の
    # ガード）だけでなく、親 `.lociaction/` を後から symlink にすり替える
    # レースも構造的に閉じる (LOCI-REGISTRY-CONFIGDIR-TOCTOU-01)。
    from lociaction.paths import open_dir_relative

    try:
        fd = open_dir_relative(
            lock_path.parent, lock_path.name, os.O_CREAT | os.O_RDWR, 0o600
        )
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            typer.echo(f"Refusing symlinked lock file: {lock_path}", err=True)
            raise typer.Exit(1) from None
        raise
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        typer.echo("loci distill is already running. Exiting.", err=True)
        raise typer.Exit(1)

    backend = _resolve_backend(cfg, root, is_tty)
    if backend is None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        raise typer.Exit(0 if not is_tty else 1)

    from lociaction.cli.progress import DistillationProgress

    progress = DistillationProgress()

    def _on_progress(cur: int, tot: int, error: str | None = None) -> None:
        progress.update(cur, tot, error)

    try:
        from lociaction.db import check_drift

        drifts = check_drift(db)
        for key, recorded, current in drifts:
            typer.echo(
                f"[warn] {key} changed ({recorded} -> {current}). Re-index recommended.",
                err=True,
            )

        from lociaction.adapters.model.llama_server import LlamaServerError
        from lociaction.distiller import has_pending_work

        try:
            if has_pending_work(
                db, limit=limit, distill_min_chars=cfg.distill_min_chars
            ):
                with bind_runtime_backend(backend, root) as bound:
                    count, err_count = distill_all(
                        db,
                        limit=limit,
                        backend=bound,
                        on_progress=_on_progress,
                        project_root=str(root),
                        distill_min_chars=cfg.distill_min_chars,
                    )
            else:
                count, err_count = distill_all(
                    db,
                    limit=limit,
                    backend=backend,
                    on_progress=_on_progress,
                    project_root=str(root),
                    distill_min_chars=cfg.distill_min_chars,
                )
        except LlamaServerError as exc:
            typer.echo(sanitize_terminal_text(str(exc)), err=True)
            raise typer.Exit(1) from None
        progress.finish()
        typer.echo(f"Distilled {count} exchange(s).")
        if err_count > 0:
            typer.echo(f"{err_count} exchange(s) failed — see errors above.", err=True)
    finally:
        progress.finish()
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
