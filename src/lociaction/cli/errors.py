"""Shared CLI abort helpers.

Recovery commands stay in the primary error line. Docs links are a second
line, only for errors whose topic is unambiguous.
"""

from __future__ import annotations

import typer

NOT_INITIALIZED = "Not initialized. Run `loci init` first."
NOT_INITIALIZED_DOCS = (
    "For non-interactive setup, see `loci docs show getting-started`."
)
DISTILLATION_DOCS = "See `loci docs show distillation`."


def abort_not_initialized() -> None:
    typer.echo(NOT_INITIALIZED, err=True)
    typer.echo(NOT_INITIALIZED_DOCS, err=True)
    raise typer.Exit(1)
