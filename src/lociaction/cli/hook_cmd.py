"""loci hook install コマンド"""

from __future__ import annotations

from typing import Annotated

import typer

hook_app = typer.Typer(help="Harness hook 管理")


@hook_app.command("install")
def hook_install(
    harness: Annotated[
        str, typer.Option("--harness", help="対象 harness（既定: claude）")
    ] = "claude",
) -> None:
    """Harness の lifecycle automation を設定する。"""
    from lociaction.adapters.harness.hooks import hooks_for
    from lociaction.config import load_config
    from lociaction.hooks import SettingsLoadError
    from lociaction.paths import find_project_root

    root = find_project_root()
    cfg = load_config(root)
    try:
        _changed, message = hooks_for(
            harness, batch_limit=cfg.distill_batch_limit
        ).install(root)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--harness") from exc
    except SettingsLoadError as exc:
        typer.echo(f"⚠ {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(message)


@hook_app.command("uninstall")
def hook_uninstall(
    harness: Annotated[
        str, typer.Option("--harness", help="対象 harness（既定: claude）")
    ] = "claude",
) -> None:
    """Harness の native lifecycle automation を解除する。"""
    from lociaction.adapters.harness.hooks import hooks_for
    from lociaction.hooks import SettingsLoadError

    try:
        _changed, message = hooks_for(harness).uninstall()
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--harness") from exc
    except SettingsLoadError as exc:
        typer.echo(f"⚠ {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(message)
