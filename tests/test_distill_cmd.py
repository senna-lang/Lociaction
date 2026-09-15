"""loci distill コマンドの client 解決フローのテスト

unconfigured / not-ready 時の TTY 再選択・非対話 skip・silent fallback 禁止・
`--setup` の config 保存を検証する。distill_all 自体は distiller_all をモックして
「どの backend で呼ばれたか」だけを見る。
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from lociaction.adapters.model.types import ClientStatus, ModelClient
from lociaction.cli import app
from lociaction.db import init_db

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_ollama_drafter_upgrade_by_default(monkeypatch):
    """upgrade_ollama_ft_drafter_if_missing() が実機の ollama を検知して
    real subprocess を呼ばないよう、既定で「何もしない」に固定する。
    drafter 自動追加そのものを検証するテストは個別に monkeypatch する。
    """
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.upgrade_ollama_ft_drafter_if_missing",
        lambda: None,
    )


_CLAUDE_CLIENT = ModelClient(
    id="claude-cli",
    provider="claude",
    model="claude-haiku-4-5-20251001",
    base_url=None,
    label="Claude CLI",
)
_OLLAMA_CLIENT = ModelClient(
    id="ollama-ft",
    provider="openai",
    model="ft-model",
    base_url="http://localhost:11434/v1",
    label="Ollama (local FT model)",
)


def _init_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    lociaction_dir = tmp_path / ".lociaction"
    lociaction_dir.mkdir()
    init_db(lociaction_dir / "memory.db")
    return lociaction_dir


def _write_config(lociaction_dir, body: str) -> None:
    (lociaction_dir / "config.toml").write_text(body)


def _stub_distill_all(monkeypatch, calls: list):
    def _fake(db, **kwargs):
        calls.append(kwargs.get("backend"))
        return (0, 0)

    monkeypatch.setattr("lociaction.distiller.distill_all", _fake)


# ---- unconfigured ----


def test_distill_unconfigured_non_tty_skips_without_error(
    tmp_path, monkeypatch
) -> None:
    """unconfigured かつ非対話なら暗黙 client を作らず warn+exit0 する"""
    _init_project(tmp_path, monkeypatch)
    calls: list = []
    _stub_distill_all(monkeypatch, calls)
    monkeypatch.setattr("lociaction.cli.distill_cmd._is_interactive", lambda: False)

    result = runner.invoke(app, ["distill"])

    assert result.exit_code == 0
    assert "not configured" in result.output
    assert calls == []


def test_distill_unconfigured_tty_prompts_and_uses_selection_once(
    tmp_path, monkeypatch
) -> None:
    """unconfigured かつ対話なら Ready 一覧から再選択できる（config は保存しない）"""
    lociaction_dir = _init_project(tmp_path, monkeypatch)
    calls: list = []
    _stub_distill_all(monkeypatch, calls)
    monkeypatch.setattr("lociaction.cli.distill_cmd._is_interactive", lambda: True)
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.discover",
        lambda: [
            ClientStatus(
                id="claude-cli",
                label="Claude CLI",
                state="ready",
                reason="ready",
                client=_CLAUDE_CLIENT,
            )
        ],
    )

    result = runner.invoke(app, ["distill"], input="1\n")

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].provider == "claude"
    # once のみ: config は書き換わらない
    assert not (lociaction_dir / "config.toml").exists()


# ---- configured but not ready ----


def test_distill_configured_not_ready_non_tty_does_not_autoswitch(
    tmp_path, monkeypatch
) -> None:
    """configured client が Ready でないとき、非対話では別 client に自動切替しない"""
    lociaction_dir = _init_project(tmp_path, monkeypatch)
    _write_config(lociaction_dir, '[distill]\nclient = "ollama-ft"\n')
    calls: list = []
    _stub_distill_all(monkeypatch, calls)
    monkeypatch.setattr("lociaction.cli.distill_cmd._is_interactive", lambda: False)
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.check_ready",
        lambda client_id: ClientStatus(
            id="ollama-ft",
            label="Ollama (local FT model)",
            state="unavailable",
            reason="ollama binary not found in PATH",
        ),
    )

    result = runner.invoke(app, ["distill"])

    assert result.exit_code == 0
    assert "Not switching automatically" in result.output
    assert "loci docs show distillation" in result.output
    assert calls == []


def test_distill_configured_ready_uses_it_without_prompting(
    tmp_path, monkeypatch
) -> None:
    """configured client が Ready ならそのまま使い、discover/prompt は起きない"""
    lociaction_dir = _init_project(tmp_path, monkeypatch)
    _write_config(
        lociaction_dir,
        '[distill]\nclient = "claude-cli"\nmodel = "claude-haiku-4-5-20251001"\n',
    )
    monkeypatch.setenv("LOCIACTION_REMOTE_DISTILL_CLIENTS", "claude-cli")
    calls: list = []
    _stub_distill_all(monkeypatch, calls)
    monkeypatch.setattr("lociaction.cli.distill_cmd._is_interactive", lambda: False)
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.check_ready",
        lambda client_id: ClientStatus(
            id="claude-cli",
            label="Claude CLI",
            state="ready",
            reason="ready",
            client=_CLAUDE_CLIENT,
        ),
    )

    result = runner.invoke(app, ["distill"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].provider == "claude"



def test_distill_configured_ready_ollama_ft_tty_auto_upgrades_to_drafter(
    tmp_path, monkeypatch
) -> None:
    """既存ユーザーが生の FT モデルのまま ready かつ対話実行なら、drafter を
    自動で追加し config.toml も書き換え、その回の蒸留から使う。"""
    from lociaction.config import LOCAL_DISTILL_MODEL

    lociaction_dir = _init_project(tmp_path, monkeypatch)
    _write_config(
        lociaction_dir,
        f'[distill]\nclient = "ollama-ft"\nmodel = "{LOCAL_DISTILL_MODEL}"\n'
        'base_url = "http://localhost:11434/v1"\n',
    )
    calls: list = []
    _stub_distill_all(monkeypatch, calls)
    monkeypatch.setattr("lociaction.cli.distill_cmd._is_interactive", lambda: True)

    raw_status = ClientStatus(
        id="ollama-ft",
        label="Ollama (local FT model)",
        state="ready",
        reason="ready (no speculative-decoding drafter)",
        client=_OLLAMA_CLIENT,  # model="ft-model"、_write_config の値とは無関係
    )
    drafter_client = ModelClient(
        id="ollama-ft",
        provider="openai",
        model="loci-distiller",
        base_url="http://localhost:11434/v1",
        label="Ollama (local FT model)",
    )
    check_ready_calls: list[str] = []

    def _fake_check_ready(client_id: str) -> ClientStatus:
        check_ready_calls.append(client_id)
        if len(check_ready_calls) == 1:
            return raw_status
        return ClientStatus(
            id="ollama-ft",
            label="Ollama (local FT model)",
            state="ready",
            reason="ready",
            client=drafter_client,
        )

    monkeypatch.setattr(
        "lociaction.adapters.model.registry.check_ready", _fake_check_ready
    )
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.upgrade_ollama_ft_drafter_if_missing",
        lambda: (True, "created loci-distiller (drafter: qwen2.5:0.5b)"),
    )

    result = runner.invoke(app, ["distill"])

    assert result.exit_code == 0
    assert "created loci-distiller" in result.output
    assert len(calls) == 1
    assert calls[0].model == "loci-distiller"
    config = (lociaction_dir / "config.toml").read_text()
    assert 'model = "loci-distiller"' in config


def test_distill_configured_ready_ollama_ft_non_tty_does_not_auto_upgrade(
    tmp_path, monkeypatch
) -> None:
    """非対話（hook 実行）では drafter 自動追加を一切試みない
    （ネットワーク越しの ollama pull を無言の自動化から起こさないため）。"""
    from lociaction.config import LOCAL_DISTILL_MODEL

    lociaction_dir = _init_project(tmp_path, monkeypatch)
    _write_config(
        lociaction_dir,
        f'[distill]\nclient = "ollama-ft"\nmodel = "{LOCAL_DISTILL_MODEL}"\n'
        'base_url = "http://localhost:11434/v1"\n',
    )
    calls: list = []
    _stub_distill_all(monkeypatch, calls)
    monkeypatch.setattr("lociaction.cli.distill_cmd._is_interactive", lambda: False)
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.check_ready",
        lambda client_id: ClientStatus(
            id="ollama-ft",
            label="Ollama (local FT model)",
            state="ready",
            reason="ready",
            client=ModelClient(
                id="ollama-ft",
                provider="openai",
                model=LOCAL_DISTILL_MODEL,
                base_url="http://localhost:11434/v1",
                label="Ollama (local FT model)",
            ),
        ),
    )
    upgrade_calls: list = []
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.upgrade_ollama_ft_drafter_if_missing",
        lambda: upgrade_calls.append(1),
    )

    result = runner.invoke(app, ["distill"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].model == LOCAL_DISTILL_MODEL
    assert upgrade_calls == []
    config = (lociaction_dir / "config.toml").read_text()
    assert LOCAL_DISTILL_MODEL in config


def test_distill_rejects_symlinked_lock_file(tmp_path, monkeypatch) -> None:
    """distill.lock が symlink の場合、O_NOFOLLOW open で拒否して外部ファイルを
    開かない (LOCI-DISTILL-LOCK-SYMLINK)。"""
    lociaction_dir = _init_project(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCIACTION_REMOTE_DISTILL_CLIENTS", "claude-cli")
    _write_config(lociaction_dir, '[distill]\nclient = "claude-cli"\n')
    outside = tmp_path / "outside.lock"
    outside.write_text("must remain unchanged")
    (lociaction_dir / "distill.lock").symlink_to(outside)

    result = runner.invoke(app, ["distill"])

    assert result.exit_code == 1
    assert "symlinked lock file" in result.output
    assert outside.read_text() == "must remain unchanged"



def test_distill_error_progress_sanitizes_terminal_output(tmp_path, monkeypatch) -> None:
    """distill_all の on_progress error callback は蒸留失敗テキストに含まれうる
    端末制御シーケンスを出力へ残さない (LOCI-DISTILL-ERROR-ESCAPE-01)。"""
    lociaction_dir = _init_project(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCIACTION_REMOTE_DISTILL_CLIENTS", "claude-cli")
    _write_config(lociaction_dir, '[distill]\nclient = "claude-cli"\n')
    monkeypatch.setattr("lociaction.cli.distill_cmd._is_interactive", lambda: False)
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.check_ready",
        lambda client_id: ClientStatus(
            id="claude-cli",
            label="Claude CLI",
            state="ready",
            reason="ready",
            client=_CLAUDE_CLIENT,
        ),
    )

    def _fake_distill_all(db, **kwargs):
        kwargs["on_progress"](1, 1, "boom \x1b]8;;https://evil.test\x1b\\x")
        return (0, 1)

    monkeypatch.setattr("lociaction.distiller.distill_all", _fake_distill_all)

    result = runner.invoke(app, ["distill"])

    assert "\x1b" not in result.output
# ---- --setup ----


def test_distill_setup_saves_selection_to_config(tmp_path, monkeypatch) -> None:
    """`loci distill --setup` は選んだ client を config.toml に保存する"""
    lociaction_dir = _init_project(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "lociaction.adapters.model.registry.discover",
        lambda: [
            ClientStatus(
                id="ollama-ft",
                label="Ollama (local FT model)",
                state="ready",
                reason="ready",
                client=_OLLAMA_CLIENT,
            ),
            ClientStatus(
                id="claude-cli",
                label="Claude CLI",
                state="ready",
                reason="ready",
                client=_CLAUDE_CLIENT,
            ),
        ],
    )

    result = runner.invoke(app, ["distill", "--setup"], input="2\n")

    assert result.exit_code == 0
    config = (lociaction_dir / "config.toml").read_text()
    assert 'client = "claude-cli"' in config


def test_distill_setup_no_ready_client_exits_nonzero(tmp_path, monkeypatch) -> None:
    """--setup 時に Ready client が無ければエラー終了する"""
    lociaction_dir = _init_project(tmp_path, monkeypatch)
    monkeypatch.setattr("lociaction.adapters.model.registry.discover", lambda: [])

    result = runner.invoke(app, ["distill", "--setup"])

    assert result.exit_code != 0
    assert not (lociaction_dir / "config.toml").exists()


# ---- not initialized ----


def test_distill_not_initialized_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["distill"])
    assert result.exit_code == 1
    assert "loci init" in result.output
