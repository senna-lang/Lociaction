"""対話プロンプトの共通ヘルパー（issue: 番号入力を矢印キートグルに変更）。

対話端末（stdin/stdout が共に TTY）では矢印キー + Enter のトグルメニュー
（questionary）を表示する。非対話（パイプ入力・pytest の CliRunner・エージェント
による `loci init` 自動化実行）では既存の番号入力プロンプトにフォールバックする
——エージェントが `input="1\\n3\\n1\\n"` のように答えをパイプで渡す運用、および
既存のテストスイートを変更せずに動かし続けるため。
"""

from __future__ import annotations

import sys

import typer

_STYLE = None  # 遅延構築（questionary の import コストを非対話パスで避ける）


def is_interactive() -> bool:
    """stdin/stdout が両方 TTY かどうか（テストで monkeypatch する用の切り出し）"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _brand_style():
    global _STYLE
    if _STYLE is None:
        import questionary

        _STYLE = questionary.Style(
            [
                ("qmark", "fg:#5BE9D6 bold"),
                ("question", "bold"),
                ("pointer", "fg:#A371F7 bold"),
                ("highlighted", "fg:#A371F7 bold"),
                ("selected", "fg:#5BE9D6"),
            ]
        )
    return _STYLE


def select_index(
    message: str,
    labels: list[str],
    *,
    default: int = 0,
    prompt_label: str = "Choice",
    numbering: str = "bracket",
    aliases: dict[str, int] | None = None,
    invalid_message: str | None = None,
) -> int:
    """`message` の下に `labels` を提示し、選ばれた 0-based index を返す。

    対話端末: questionary の矢印キートグルメニュー。Ctrl+C/Ctrl+D は
    `typer.Abort` として伝播する（既存の Abort ハンドリングと揃える）。
    非対話: `numbering` に応じて "[N] label"（"bracket"）または
    "N. label"（"dot"）で列挙し、`prompt_label` を使って番号入力を求める。
    `aliases`（例: {"y": 1, "yes": 1, "n": 0, "no": 0}）は非対話フォールバック
    でのみ、番号に加えて受け付ける小文字テキスト入力。無効な入力は再プロンプト
    する。`invalid_message` を指定すると、その固定文言でエラーを表示する。
    """
    if is_interactive():
        import questionary

        choices = [
            questionary.Choice(title=label, value=i) for i, label in enumerate(labels)
        ]
        answer = questionary.select(
            message,
            choices=choices,
            default=choices[default],
            style=_brand_style(),
        ).ask()
        if answer is None:
            raise typer.Abort()
        return answer

    typer.echo(message)
    for i, label in enumerate(labels, start=1):
        if numbering == "dot":
            typer.echo(f"  {i}. {label}")
        else:
            typer.echo(f"  [{i}] {label}")

    count = len(labels)
    alias_map = {k.lower(): v for k, v in (aliases or {}).items()}
    while True:
        raw = typer.prompt(prompt_label, default=str(default + 1)).strip()
        if raw.isdigit() and 1 <= int(raw) <= count:
            return int(raw) - 1
        if raw.lower() in alias_map:
            return alias_map[raw.lower()]
        if invalid_message is not None:
            typer.echo(invalid_message)
        elif numbering == "dot":
            typer.echo(f"  Invalid choice. Please enter one of: 1-{count}.")
        else:
            sorted_valid = sorted(
                (str(v) for v in range(1, count + 1)), key=lambda s: (len(s), s)
            )
            typer.echo(
                f"  Invalid choice. Please enter one of: {', '.join(sorted_valid)}"
            )


def prompt_text(message: str, *, prompt_label: str = "Value") -> str:
    """自由入力を受け付け、空入力は再プロンプトする。

    対話端末: questionary の text プロンプト。非対話: `typer.prompt`。
    セッション履歴に一度も現れていないモデルID（例: そのCLIの軽量tier）を
    手入力できるようにするための汎用ヘルパー。
    """
    if is_interactive():
        import questionary

        while True:
            answer = questionary.text(message, style=_brand_style()).ask()
            if answer is None:
                raise typer.Abort()
            answer = answer.strip()
            if answer:
                return answer
            typer.echo("  Must not be empty.")

    typer.echo(message)
    while True:
        raw = typer.prompt(prompt_label).strip()
        if raw:
            return raw
        typer.echo("  Must not be empty.")
