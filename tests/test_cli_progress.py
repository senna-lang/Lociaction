"""Terminal rendering contract for distillation progress."""

from __future__ import annotations

from lociaction.cli.progress import DistillationProgress


def test_progress_rewrites_one_terminal_line(capsys) -> None:
    """Successful exchanges update one counter instead of appending rows."""
    progress = DistillationProgress()

    progress.update(1, 3)
    progress.update(2, 3)
    progress.update(3, 3)
    progress.finish()

    assert capsys.readouterr().err == (
        "\rDistilling 1/3\rDistilling 2/3\rDistilling 3/3\n"
    )


def test_progress_preserves_sanitized_error_details(capsys) -> None:
    """A failure ends the transient line before emitting its safe diagnostic."""
    progress = DistillationProgress()

    progress.update(1, 2, "boom \x1b]8;;https://evil.test\x07")
    progress.update(2, 2)
    progress.finish()

    output = capsys.readouterr().err
    assert "\x1b" not in output
    assert "error: boom" in output
    assert "Distilling 2/2 (1 failed)" in output
