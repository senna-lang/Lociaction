"""lociaction.adapters.model.registry のユニットテスト"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lociaction.adapters.model.registry import (
    _ollama_model_pulled,
    check_ready,
    detect_claude_cli,
    detect_codex_cli,
    detect_gemini_cli,
    detect_grok_cli,
    detect_ollama_ft,
    detect_omp_cli,
    detect_opencode_cli,
    discover,
    ready_clients,
    recommended_id,
    resolve_client,
    setup,
    write_client_config,
)
from lociaction.adapters.model.types import ClientStatus
from lociaction.config import LOCAL_DISTILL_BASE_URL, LOCAL_DISTILL_MODEL

# ---- detect_ollama_ft ----


def test_detect_ollama_ft_binary_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = detect_ollama_ft()
    assert status.state == "unavailable"
    assert status.client is None


def test_detect_ollama_ft_model_not_pulled(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="NAME\nother-model:latest\n"),
    )
    status = detect_ollama_ft()
    assert status.state == "setupable"
    assert status.client is None
    assert LOCAL_DISTILL_MODEL in status.reason


def test_detect_ollama_ft_base_pulled_no_drafter_still_ready_for_backward_compat(
    monkeypatch,
) -> None:
    """FT本体は pull 済みだが drafter (loci-distiller) が未作成でも ready のまま。
    既存 config.toml が生の FT モデル名を明示している既存ユーザーの
    `loci distill`（特に非対話の hook 実行）を「not ready」で止めてはならない
    ——drafter は新規セットアップ時にだけ優先される任意の高速化。"""
    from lociaction.config import LOCAL_DISTILL_DRAFTER_MODEL

    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout=f"NAME\n{LOCAL_DISTILL_MODEL}\n"),
    )
    status = detect_ollama_ft()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.model == LOCAL_DISTILL_MODEL
    assert LOCAL_DISTILL_DRAFTER_MODEL not in (status.client.model or "")


def test_detect_ollama_ft_ready(monkeypatch) -> None:
    """drafter (loci-distiller) が作成済みなら ready で、client.model は
    生の FT 本体名ではなく drafter モデル名を指す。"""
    from lociaction.config import LOCAL_DISTILL_DRAFTER_MODEL

    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0, stdout=f"NAME\n{LOCAL_DISTILL_DRAFTER_MODEL}\n"
        ),
    )
    status = detect_ollama_ft()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.id == "ollama-ft"
    assert status.client.model == LOCAL_DISTILL_DRAFTER_MODEL
    assert status.client.base_url == LOCAL_DISTILL_BASE_URL


def test_detect_ollama_ft_list_command_fails(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: MagicMock(returncode=1, stdout="")
    )
    status = detect_ollama_ft()
    assert status.state == "setupable"

# ---- detect_claude_cli ----


def test_detect_claude_cli_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = detect_claude_cli()
    assert status.state == "unavailable"
    assert status.client is None


def test_detect_claude_cli_ready(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
    status = detect_claude_cli()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.id == "claude-cli"
    assert status.client.provider == "claude"



# ---- detect_codex_cli ----


def test_detect_codex_cli_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = detect_codex_cli()
    assert status.state == "unavailable"
    assert status.client is None


def test_detect_codex_cli_ready(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/codex")
    status = detect_codex_cli()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.id == "codex-cli"
    assert status.client.provider == "codex"
    assert status.client.model is None


# ---- detect_gemini_cli ----


def test_detect_gemini_cli_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = detect_gemini_cli()
    assert status.state == "unavailable"
    assert status.client is None


def test_detect_gemini_cli_ready(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/gemini")
    status = detect_gemini_cli()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.id == "gemini-cli"
    assert status.client.provider == "gemini"
    assert status.client.model is None


# ---- detect_grok_cli ----


def test_detect_grok_cli_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = detect_grok_cli()
    assert status.state == "unavailable"
    assert status.client is None


def test_detect_grok_cli_ready(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/grok")
    status = detect_grok_cli()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.id == "grok-cli"
    assert status.client.provider == "grok"
    assert status.client.model is None


# ---- detect_opencode_cli ----


def test_detect_opencode_cli_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = detect_opencode_cli()
    assert status.state == "unavailable"
    assert status.client is None


def test_detect_opencode_cli_ready(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/opencode")
    status = detect_opencode_cli()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.id == "opencode-cli"
    assert status.client.provider == "opencode"
    assert status.client.model is None


# ---- detect_omp_cli ----


def test_detect_omp_cli_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = detect_omp_cli()
    assert status.state == "unavailable"
    assert status.client is None


def test_detect_omp_cli_ready(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/omp")
    status = detect_omp_cli()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.id == "omp-cli"
    assert status.client.provider == "omp"
    assert status.client.model is None

# ---- discover / ready_clients / recommended_id ----


def test_discover_returns_ollama_then_claude_order(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    statuses = discover()
    assert [s.id for s in statuses] == [
        "ollama-ft",
        "claude-cli",
        "codex-cli",
        "gemini-cli",
        "grok-cli",
        "opencode-cli",
        "omp-cli",
    ]


def test_ready_clients_filters_by_state() -> None:
    statuses = [
        ClientStatus(id="a", label="A", state="ready", reason="ready"),
        ClientStatus(id="b", label="B", state="unavailable", reason="no"),
        ClientStatus(id="c", label="C", state="setupable", reason="setup"),
    ]
    assert [s.id for s in ready_clients(statuses)] == ["a"]


def test_recommended_id_prefers_ollama_ft() -> None:
    statuses = [
        ClientStatus(id="claude-cli", label="Claude CLI", state="ready", reason="ready"),
        ClientStatus(id="ollama-ft", label="Ollama", state="ready", reason="ready"),
    ]
    assert recommended_id(statuses) == "ollama-ft"


def test_recommended_id_falls_back_to_first_ready_when_ollama_not_ready() -> None:
    statuses = [
        ClientStatus(id="claude-cli", label="Claude CLI", state="ready", reason="ready"),
    ]
    assert recommended_id(statuses) == "claude-cli"


def test_recommended_id_none_when_no_ready() -> None:
    statuses = [ClientStatus(id="a", label="A", state="unavailable", reason="no")]
    assert recommended_id(statuses) is None


# ---- setup ----


def test_setup_ollama_ft_binary_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    ok, msg = setup("ollama-ft")
    assert ok is False
    assert "ollama binary not found" in msg


def _ollama_command_dispatcher(
    pulled_models: list[str],
    *,
    pull_returncode: int = 0,
    create_returncode: int = 0,
    pull_stderr: str = "",
    create_stderr: str = "",
):
    """`ollama list`/`pull`/`create` それぞれに妥当な応答を返す subprocess.run
    差し替え。呼び出されたコマンド列も記録して検証に使う。"""
    calls: list[list[str]] = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["ollama", "list"]:
            names = "\n".join(pulled_models)
            return MagicMock(returncode=0, stdout=f"NAME\n{names}\n")
        if cmd[:2] == ["ollama", "pull"]:
            return MagicMock(returncode=pull_returncode, stdout="", stderr=pull_stderr)
        if cmd[:2] == ["ollama", "create"]:
            return MagicMock(
                returncode=create_returncode, stdout="", stderr=create_stderr
            )
        raise AssertionError(f"unexpected subprocess.run call: {cmd}")

    return _run, calls


def test_setup_ollama_ft_full_flow_pulls_both_models_and_creates_drafter(
    monkeypatch,
) -> None:
    """何も pull されていない状態から、FT本体・drafterモデルの両方を pull し、
    結合した drafter-enabled モデルを ollama create する。"""
    from lociaction.config import LOCAL_DISTILL_DRAFT_MODEL, LOCAL_DISTILL_DRAFTER_MODEL

    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    run, calls = _ollama_command_dispatcher(pulled_models=[])
    monkeypatch.setattr("subprocess.run", run)

    ok, msg = setup("ollama-ft")

    assert ok is True
    assert LOCAL_DISTILL_DRAFTER_MODEL in msg
    assert LOCAL_DISTILL_DRAFT_MODEL in msg
    pull_targets = [c[2] for c in calls if c[:2] == ["ollama", "pull"]]
    assert pull_targets == [LOCAL_DISTILL_MODEL, LOCAL_DISTILL_DRAFT_MODEL]
    create_calls = [c for c in calls if c[:2] == ["ollama", "create"]]
    assert len(create_calls) == 1
    assert create_calls[0][2] == LOCAL_DISTILL_DRAFTER_MODEL


def test_setup_ollama_ft_skips_pull_for_already_pulled_models(monkeypatch) -> None:
    """FT本体・drafterモデルどちらも既に pull 済みなら、pull は呼ばず
    ollama create だけ実行する。"""
    from lociaction.config import LOCAL_DISTILL_DRAFT_MODEL, LOCAL_DISTILL_DRAFTER_MODEL

    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    run, calls = _ollama_command_dispatcher(
        pulled_models=[LOCAL_DISTILL_MODEL, LOCAL_DISTILL_DRAFT_MODEL]
    )
    monkeypatch.setattr("subprocess.run", run)

    ok, msg = setup("ollama-ft")

    assert ok is True
    assert LOCAL_DISTILL_DRAFTER_MODEL in msg
    assert not [c for c in calls if c[:2] == ["ollama", "pull"]]
    assert len([c for c in calls if c[:2] == ["ollama", "create"]]) == 1


def test_setup_ollama_ft_base_pull_fails_does_not_pull_draft_or_create(
    monkeypatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    run, calls = _ollama_command_dispatcher(
        pulled_models=[], pull_returncode=1, pull_stderr="boom"
    )
    monkeypatch.setattr("subprocess.run", run)

    ok, msg = setup("ollama-ft")

    assert ok is False
    assert "failed" in msg
    assert LOCAL_DISTILL_MODEL in msg
    assert not [c for c in calls if c[:2] == ["ollama", "create"]]


def test_setup_ollama_ft_create_fails(monkeypatch) -> None:
    """pull は両方成功しても `ollama create` が失敗すれば setup 全体を失敗にする。"""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    run, calls = _ollama_command_dispatcher(
        pulled_models=[], create_returncode=1, create_stderr="create boom"
    )
    monkeypatch.setattr("subprocess.run", run)

    ok, msg = setup("ollama-ft")

    assert ok is False
    assert "ollama create failed" in msg
    assert "create boom" in msg


def test_setup_unsupported_client_id() -> None:
    ok, msg = setup("claude-cli")
    assert ok is False
    assert "no automated setup" in msg


# ---- upgrade_ollama_ft_drafter_if_missing ----


def test_upgrade_ollama_ft_drafter_if_missing_upgrades_raw_model(monkeypatch) -> None:
    """生の FT 本体のまま ready な既存ユーザーには、drafter を追加する
    (setup と同じ pull+create シーケンス) を実行する。"""
    from lociaction.adapters.model.registry import upgrade_ollama_ft_drafter_if_missing
    from lociaction.config import LOCAL_DISTILL_DRAFT_MODEL, LOCAL_DISTILL_DRAFTER_MODEL

    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    run, calls = _ollama_command_dispatcher(pulled_models=[LOCAL_DISTILL_MODEL])
    monkeypatch.setattr("subprocess.run", run)

    result = upgrade_ollama_ft_drafter_if_missing()

    assert result is not None
    ok, msg = result
    assert ok is True
    assert LOCAL_DISTILL_DRAFTER_MODEL in msg
    pull_targets = [c[2] for c in calls if c[:2] == ["ollama", "pull"]]
    assert pull_targets == [LOCAL_DISTILL_DRAFT_MODEL]
    assert len([c for c in calls if c[:2] == ["ollama", "create"]]) == 1


def test_upgrade_ollama_ft_drafter_if_missing_noop_when_already_has_drafter(
    monkeypatch,
) -> None:
    """drafter が既に作成済みなら何もしない（None）。"""
    from lociaction.adapters.model.registry import upgrade_ollama_ft_drafter_if_missing
    from lociaction.config import LOCAL_DISTILL_DRAFTER_MODEL

    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    run, calls = _ollama_command_dispatcher(pulled_models=[LOCAL_DISTILL_DRAFTER_MODEL])
    monkeypatch.setattr("subprocess.run", run)

    result = upgrade_ollama_ft_drafter_if_missing()

    assert result is None
    assert not [c for c in calls if c[:2] in (["ollama", "pull"], ["ollama", "create"])]


def test_upgrade_ollama_ft_drafter_if_missing_noop_when_not_ready(monkeypatch) -> None:
    """ollama-ft がそもそも ready でなければ何もしない（None）。"""
    from lociaction.adapters.model.registry import upgrade_ollama_ft_drafter_if_missing

    monkeypatch.setattr("shutil.which", lambda name: None)

    assert upgrade_ollama_ft_drafter_if_missing() is None


# ---- resolve_client ----


def test_resolve_client_claude_cli(monkeypatch) -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="claude-haiku-4-5-20251001")
    client = resolve_client("claude-cli", cfg)
    assert client.provider == "claude"
    assert client.base_url is None


def test_resolve_client_ollama_ft_uses_config_overrides() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="custom-ft-model", distill_base_url="http://x:1/v1")
    client = resolve_client("ollama-ft", cfg)
    assert client.model == "custom-ft-model"
    assert client.base_url == "http://x:1/v1"


def test_resolve_client_codex_cli_passes_through_configured_model() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="gpt-5-codex")
    client = resolve_client("codex-cli", cfg)
    assert client.provider == "codex"
    assert client.model == "gpt-5-codex"
    assert client.base_url is None


def test_resolve_client_codex_cli_model_none_when_unconfigured() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model=None)
    client = resolve_client("codex-cli", cfg)
    assert client.model is None


def test_resolve_client_gemini_cli_passes_through_configured_model() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="gemini-2.5-pro")
    client = resolve_client("gemini-cli", cfg)
    assert client.provider == "gemini"
    assert client.model == "gemini-2.5-pro"
    assert client.base_url is None


def test_resolve_client_gemini_cli_model_none_when_unconfigured() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model=None)
    client = resolve_client("gemini-cli", cfg)
    assert client.model is None


def test_resolve_client_grok_cli_passes_through_configured_model() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="grok-4.6")
    client = resolve_client("grok-cli", cfg)
    assert client.provider == "grok"
    assert client.model == "grok-4.6"
    assert client.base_url is None


def test_resolve_client_grok_cli_model_none_when_unconfigured() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model=None)
    client = resolve_client("grok-cli", cfg)
    assert client.model is None


def test_resolve_client_opencode_cli_passes_through_configured_model() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="opencode/big-pickle")
    client = resolve_client("opencode-cli", cfg)
    assert client.provider == "opencode"
    assert client.model == "opencode/big-pickle"
    assert client.base_url is None


def test_resolve_client_opencode_cli_model_none_when_unconfigured() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model=None)
    client = resolve_client("opencode-cli", cfg)
    assert client.model is None


def test_resolve_client_omp_cli_passes_through_configured_model() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="haiku")
    client = resolve_client("omp-cli", cfg)
    assert client.provider == "omp"
    assert client.model == "haiku"
    assert client.base_url is None


def test_resolve_client_omp_cli_model_none_when_unconfigured() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model=None)
    client = resolve_client("omp-cli", cfg)
    assert client.model is None


def test_resolve_client_openai_compat_requires_base_url() -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="m", distill_base_url=None)
    try:
        resolve_client("openai-compat", cfg)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_resolve_client_unknown_id_raises() -> None:
    from lociaction.config import Config

    try:
        resolve_client("bogus", Config())
        raised = False
    except ValueError:
        raised = True
    assert raised


# ---- check_ready ----


def test_check_ready_dispatches_to_detector(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = check_ready("claude-cli")
    assert status.state == "unavailable"


def test_check_ready_unknown_client_is_unavailable() -> None:
    status = check_ready("openai-compat")
    assert status.state == "unavailable"


# ---- write_client_config ----


def test_write_client_config_writes_client_model_base_url(tmp_path) -> None:
    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    client = ModelClient(
        id="ollama-ft",
        provider="openai",
        model=LOCAL_DISTILL_MODEL,
        base_url=LOCAL_DISTILL_BASE_URL,
        label="Ollama (local FT model)",
    )
    write_client_config(config_path, client)
    content = config_path.read_text()
    assert 'client = "ollama-ft"' in content
    assert f'model = "{LOCAL_DISTILL_MODEL}"' in content
    assert f'base_url = "{LOCAL_DISTILL_BASE_URL}"' in content
    assert "provider" not in content


def test_write_client_config_rejects_symlinked_config_file(tmp_path) -> None:
    """setup が project state 内の leaf symlink target を上書きしない。"""
    from lociaction.adapters.model.types import ModelClient

    target = tmp_path / "outside.toml"
    target.write_text("sentinel\n")
    config_path = tmp_path / "config.toml"
    config_path.symlink_to(target)
    client = ModelClient(
        id="ollama-ft",
        provider="openai",
        model="model",
        base_url="http://localhost:11434/v1",
        label="Ollama",
    )

    try:
        write_client_config(config_path, client)
    except ValueError:
        pass
    else:
        raise AssertionError("expected symlinked config to be rejected")

    assert target.read_text() == "sentinel\n"


def test_write_client_config_rejects_oversized_existing_config(tmp_path) -> None:
    """setup は既存の attacker-controlled config を無制限に tomllib へ渡さない
    （LOCI-REGISTRY-UNBOUNDED-CONFIG-01）。"""
    from lociaction.adapters.model.types import ModelClient
    from lociaction.config import MAX_CONFIG_FILE_BYTES

    config_path = tmp_path / "config.toml"
    original = b"x" * (MAX_CONFIG_FILE_BYTES + 1)
    config_path.write_bytes(original)
    client = ModelClient(
        id="ollama-ft",
        provider="openai",
        model="model",
        base_url="http://localhost:11434/v1",
        label="Ollama",
    )

    with pytest.raises(ValueError, match="exceeds"):
        write_client_config(config_path, client)

    assert config_path.read_bytes() == original


def test_write_client_config_omits_model_key_when_none(tmp_path) -> None:
    """codex-cli/gemini-cli は model=None を許容する — TOML に `model = None` を
    書こうとすると tomli_w が壊れるので、鍵ごと省略されることを確認する。"""
    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    client = ModelClient(
        id="codex-cli",
        provider="codex",
        model=None,
        base_url=None,
        label="Codex CLI",
    )
    write_client_config(config_path, client)
    content = config_path.read_text()
    assert 'client = "codex-cli"' in content
    assert "model" not in content


def test_write_client_config_removes_stale_model_when_switching_to_none(
    tmp_path,
) -> None:
    """既存 config に model が残っていても、新しい client が model=None なら
    古い値を引きずらず削除する。"""
    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    config_path.write_text('[distill]\nclient = "claude-cli"\nmodel = "old-model"\n')
    client = ModelClient(
        id="gemini-cli",
        provider="gemini",
        model=None,
        base_url=None,
        label="Gemini CLI",
    )
    write_client_config(config_path, client)
    content = config_path.read_text()
    assert 'client = "gemini-cli"' in content
    assert "old-model" not in content
    assert "model" not in content


def test_write_client_config_drops_legacy_provider_key(tmp_path) -> None:
    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    config_path.write_text('[distill]\nprovider = "claude"\nbatch_limit = 5\n')
    client = ModelClient(
        id="claude-cli",
        provider="claude",
        model="claude-haiku-4-5-20251001",
        base_url=None,
        label="Claude CLI",
    )
    write_client_config(config_path, client)
    content = config_path.read_text()
    assert 'client = "claude-cli"' in content
    assert 'provider = "claude"' not in content
    assert "batch_limit = 5" in content
    assert "base_url" not in content


def test_write_client_config_preserves_index_min_chars(tmp_path) -> None:
    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    config_path.write_text('[distill]\nprovider = "claude"\n\n[index]\nmin_chars = 200\n')
    client = ModelClient(
        id="claude-cli",
        provider="claude",
        model="claude-haiku-4-5-20251001",
        base_url=None,
        label="Claude CLI",
    )
    write_client_config(config_path, client)
    content = config_path.read_text()
    assert "min_chars = 200" in content


def test_write_client_config_rejects_non_integer_index_min_chars(tmp_path) -> None:
    """[index].min_chars が未検証の TOML 由来の場合、tomli_w に通らない値は
    そのまま f-string へ埋め込まず、コメントアウトされたデフォルトへ落とす
    (LOCI-REGISTRY-TOML-INJECT-INDEX)。"""
    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[distill]\nprovider = "claude"\n\n[index]\n'
        'min_chars = """\\ninjected = "evil"\\n"""\n'
    )
    client = ModelClient(
        id="claude-cli",
        provider="claude",
        model="claude-haiku-4-5-20251001",
        base_url=None,
        label="Claude CLI",
    )

    write_client_config(config_path, client)

    content = config_path.read_text()
    assert "injected" not in content
    import tomllib

    parsed = tomllib.loads(content)
    assert "injected" not in parsed




def test_write_client_config_ignores_malformed_distill_section(tmp_path) -> None:
    """[distill] が scalar/array のような非テーブル値でもクラッシュしない
    (LOCI-REGISTRY-MALFORMED-SECTION-CRASH-01)。"""
    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    config_path.write_text('distill = "not-a-table"\n')
    client = ModelClient(
        id="claude-cli",
        provider="claude",
        model="claude-haiku-4-5-20251001",
        base_url=None,
        label="Claude CLI",
    )

    write_client_config(config_path, client)

    assert 'client = "claude-cli"' in config_path.read_text()


def test_write_client_config_ignores_malformed_index_section(tmp_path) -> None:
    """[index] が scalar/array のような非テーブル値でもクラッシュしない
    (LOCI-REGISTRY-MALFORMED-SECTION-CRASH-01)。"""
    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    config_path.write_text('index = ["not", "a", "table"]\n')
    client = ModelClient(
        id="claude-cli",
        provider="claude",
        model="claude-haiku-4-5-20251001",
        base_url=None,
        label="Claude CLI",
    )

    write_client_config(config_path, client)

    content = config_path.read_text()
    assert 'client = "claude-cli"' in content
    assert "min_chars = 50" in content

# ---- _ollama_model_pulled: NAME 列の完全一致 (#26) ----


def test_ollama_model_pulled_exact_match(monkeypatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0, stdout="NAME              ID       SIZE   MODIFIED\nqwen2.5-7b:latest abc123   4.7 GB 2 days ago\n"
        ),
    )
    assert _ollama_model_pulled("qwen2.5-7b:latest") is True


def test_ollama_model_pulled_rejects_substring_false_match(monkeypatch) -> None:
    """'qwen2.5-7b' が pull 済みの 'qwen2.5-7b-instruct' に部分一致で誤ヒットしない
    （#26: 以前は `model in line` の部分一致判定だった）"""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0,
            stdout="NAME                        ID       SIZE   MODIFIED\n"
            "qwen2.5-7b-instruct:latest  abc123   4.7 GB 2 days ago\n",
        ),
    )
    assert _ollama_model_pulled("qwen2.5-7b") is False


def test_ollama_model_pulled_no_match_when_not_pulled(monkeypatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(returncode=0, stdout="NAME\nother-model:latest\n"),
    )
    assert _ollama_model_pulled("qwen2.5-7b") is False


def test_ollama_model_pulled_matches_implicit_latest_tag_for_untagged_name(
    monkeypatch,
) -> None:
    """`ollama create loci-distiller` はタグ無しだと `loci-distiller:latest`
    として `ollama list` に現れる。タグ無し参照はこの暗黙タグを認識できないと
    常に setupable のまま誤判定する。"""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0, stdout="NAME\nloci-distiller:latest\n"
        ),
    )
    assert _ollama_model_pulled("loci-distiller") is True


def test_ollama_model_pulled_untagged_lookup_does_not_fuzzy_match_other_names(
    monkeypatch,
) -> None:
    """暗黙 `:latest` 補完は完全一致の代替であって部分一致ではない。"""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0, stdout="NAME\nloci-distiller-variant:latest\n"
        ),
    )
    assert _ollama_model_pulled("loci-distiller") is False


def test_detect_ollama_ft_superstring_pull_is_not_ready(monkeypatch) -> None:
    """LOCAL_DISTILL_MODEL の superstring がリストに存在しても ready にしない
    （完全一致のみ ready 扱い）"""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0, stdout=f"NAME\n{LOCAL_DISTILL_MODEL}-variant\n"
        ),
    )
    status = detect_ollama_ft()
    assert status.state == "setupable"
    assert status.client is None


# ---- write_client_config: TOML エスケープ (#26) ----


def test_write_client_config_escapes_quotes_and_backslashes(tmp_path) -> None:
    """model/base_url に `"` や `\\` を含んでいても壊れない TOML を書き、
    再パースすると元の値が復元される（#26: 以前は f'{key} = "{val}"' で手書き
    しており、次回起動時のパースが壊れていた）"""
    import tomllib

    from lociaction.adapters.model.types import ModelClient

    config_path = tmp_path / "config.toml"
    tricky_model = 'weird"model\\name'
    tricky_base_url = 'http://example.com/v1?q="x"\\y'
    client = ModelClient(
        id="openai-compat",
        provider="openai",
        model=tricky_model,
        base_url=tricky_base_url,
        label="OpenAI-compatible endpoint",
    )
    write_client_config(config_path, client)

    with config_path.open("rb") as f:
        parsed = tomllib.load(f)
    assert parsed["distill"]["model"] == tricky_model
    assert parsed["distill"]["base_url"] == tricky_base_url