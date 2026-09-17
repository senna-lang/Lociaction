"""Render bounded distillation progress for terminal commands.

Successful exchanges rewrite one stderr line so long-running distillation does
not fill the terminal. Failed exchanges retain a sanitized diagnostic on their
own line; the next progress update resumes the transient counter.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from lociaction.utils import sanitize_terminal_text


@dataclass
class DistillationProgress:
    """Track a single distillation run's transient counter and failures."""

    failures: int = 0
    _rendered: bool = False

    def update(self, current: int, total: int, error: str | None = None) -> None:
        """Render one exchange result without appending successful progress rows."""
        if error is not None:
            self.failures += 1
        line = f"Distilling {current}/{total}"
        if self.failures:
            line += f" ({self.failures} failed)"

        if error is not None:
            typer.echo(f"\r{line}", err=True)
            typer.echo(f"  error: {sanitize_terminal_text(error)}", err=True)
            self._rendered = False
            return

        typer.echo(f"\r{line}", nl=False, err=True)
        self._rendered = True

    def finish(self) -> None:
        """Terminate a transient progress line before subsequent CLI output."""
        if self._rendered:
            typer.echo("", err=True)
            self._rendered = False
