"""lociaction.adapters.model.registry のユニットテスト"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lociaction.adapters.model.registry import (
    check_ready,
    detect_claude_cli,
    detect_codex_cli,
    detect_gemini_cli,
    detect_grok_cli,
    detect_llamacpp_ft,
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
from lociaction.config import LOCAL_DISTILL_MODEL

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


def test_discover_returns_llamacpp_then_claude_order(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    statuses = discover()
    assert [s.id for s in statuses] == [
        "llamacpp-ft",
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


def test_recommended_id_prefers_llamacpp_ft() -> None:
    statuses = [
        ClientStatus(id="claude-cli", label="Claude CLI", state="ready", reason="ready"),
        ClientStatus(
            id="llamacpp-ft", label="llama.cpp", state="ready", reason="ready"
        ),
    ]
    assert recommended_id(statuses) == "llamacpp-ft"


def test_recommended_id_prefers_setupable_llamacpp_ft() -> None:
    statuses = [
        ClientStatus(id="claude-cli", label="Claude CLI", state="ready", reason="ready"),
        ClientStatus(
            id="llamacpp-ft",
            label="llama.cpp",
            state="setupable",
            reason="llama-server binary not found",
        ),
    ]
    assert recommended_id(statuses) == "llamacpp-ft"


def test_recommended_id_falls_back_to_first_ready_when_ft_not_ready() -> None:
    statuses = [
        ClientStatus(id="claude-cli", label="Claude CLI", state="ready", reason="ready"),
    ]
    assert recommended_id(statuses) == "claude-cli"


def test_recommended_id_none_when_no_ready() -> None:
    statuses = [ClientStatus(id="a", label="A", state="unavailable", reason="no")]
    assert recommended_id(statuses) is None


def test_selectable_clients_includes_setupable() -> None:
    from lociaction.adapters.model.registry import selectable_clients

    statuses = [
        ClientStatus(id="llamacpp-ft", label="L", state="setupable", reason="x"),
        ClientStatus(id="claude-cli", label="C", state="ready", reason="ready"),
        ClientStatus(id="gemini-cli", label="G", state="unavailable", reason="no"),
    ]
    assert [s.id for s in selectable_clients(statuses)] == [
        "llamacpp-ft",
        "claude-cli",
    ]
    assert [s.id for s in selectable_clients(statuses, include_setupable=False)] == [
        "claude-cli"
    ]


# ---- setup ----


def test_setup_unsupported_client_id() -> None:
    ok, msg = setup("claude-cli")
    assert ok is False
    assert "no automated setup" in msg


def test_setup_unknown_ollama_ft_id() -> None:
    ok, msg = setup("ollama-ft")
    assert ok is False
    assert "no automated setup" in msg


# ---- resolve_client ----


def test_resolve_client_claude_cli(monkeypatch) -> None:
    from lociaction.config import Config

    cfg = Config(distill_model="claude-haiku-4-5-20251001")
    client = resolve_client("claude-cli", cfg)
    assert client.provider == "claude"
    assert client.base_url is None



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
        id="openai-compat",
        provider="openai",
        model="local-model",
        base_url="http://127.0.0.1:8080/v1",
        label="OpenAI-compatible endpoint",
    )
    write_client_config(config_path, client)
    content = config_path.read_text()
    assert 'client = "openai-compat"' in content
    assert 'model = "local-model"' in content
    assert 'base_url = "http://127.0.0.1:8080/v1"' in content
    assert "provider" not in content


def test_write_client_config_rejects_symlinked_config_file(tmp_path) -> None:
    """setup が project state 内の leaf symlink target を上書きしない。"""
    from lociaction.adapters.model.types import ModelClient

    target = tmp_path / "outside.toml"
    target.write_text("sentinel\n")
    config_path = tmp_path / "config.toml"
    config_path.symlink_to(target)
    client = ModelClient(
        id="llamacpp-ft",
        provider="openai",
        model="model",
        base_url=None,
        label="llama.cpp",
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
        id="llamacpp-ft",
        provider="openai",
        model="model",
        base_url=None,
        label="llama.cpp",
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


# ---- detect_llamacpp_ft ----


def _patch_llamacpp_blobs(monkeypatch, *, binary: bool, tags: set[str]) -> None:
    from pathlib import Path

    from lociaction.adapters.model.ollama_blobs import OllamaBlobNotFound

    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.find_llama_server_binary",
        lambda: Path("/usr/bin/llama-server") if binary else None,
    )

    def _resolve(tag: str, root=None):
        if tag in tags:
            return Path("/tmp") / "blob"
        raise OllamaBlobNotFound(f"model not pulled: {tag}")

    monkeypatch.setattr(
        "lociaction.adapters.model.ollama_blobs.resolve_model_blob",
        _resolve,
    )


def test_detect_llamacpp_ft_binary_missing(monkeypatch) -> None:
    _patch_llamacpp_blobs(monkeypatch, binary=False, tags=set())
    status = detect_llamacpp_ft()
    assert status.state == "setupable"
    assert status.client is None
    assert "llama-server" in status.reason


def test_detect_llamacpp_ft_base_not_pulled(monkeypatch) -> None:
    _patch_llamacpp_blobs(monkeypatch, binary=True, tags=set())
    status = detect_llamacpp_ft()
    assert status.state == "setupable"
    assert LOCAL_DISTILL_MODEL in status.reason


def test_detect_llamacpp_ft_draft_not_pulled(monkeypatch) -> None:
    monkeypatch.delenv("LOCI_LLAMACPP_DRAFT_MODEL", raising=False)
    _patch_llamacpp_blobs(monkeypatch, binary=True, tags={LOCAL_DISTILL_MODEL})
    status = detect_llamacpp_ft()
    assert status.state == "setupable"
    assert "qwen2.5:0.5b" in status.reason


def test_detect_llamacpp_ft_ready_with_draft(monkeypatch) -> None:
    monkeypatch.delenv("LOCI_LLAMACPP_DRAFT_MODEL", raising=False)
    _patch_llamacpp_blobs(
        monkeypatch, binary=True, tags={LOCAL_DISTILL_MODEL, "qwen2.5:0.5b"}
    )
    status = detect_llamacpp_ft()
    assert status.state == "ready"
    assert status.client is not None
    assert status.client.id == "llamacpp-ft"
    assert status.client.provider == "openai"
    assert status.client.base_url is None
    assert status.client.model == LOCAL_DISTILL_MODEL


def test_detect_llamacpp_ft_ready_when_draft_opted_out(monkeypatch) -> None:
    monkeypatch.setenv("LOCI_LLAMACPP_DRAFT_MODEL", "")
    _patch_llamacpp_blobs(monkeypatch, binary=True, tags={LOCAL_DISTILL_MODEL})
    status = detect_llamacpp_ft()
    assert status.state == "ready"


def test_setup_llamacpp_ft_binary_missing(monkeypatch) -> None:
    _patch_llamacpp_blobs(monkeypatch, binary=False, tags=set())
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.shutil.which",
        lambda name: None,
    )
    ok, msg = setup("llamacpp-ft")
    assert ok is False
    assert "llama-server" in msg


def test_setup_llamacpp_ft_pulls_missing_base_and_draft(monkeypatch) -> None:
    monkeypatch.delenv("LOCI_LLAMACPP_DRAFT_MODEL", raising=False)
    _patch_llamacpp_blobs(monkeypatch, binary=True, tags=set())
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama")
    pulled: list[str] = []

    def _run(cmd, **kwargs):
        pulled.append(cmd[2])
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", _run)
    ok, msg = setup("llamacpp-ft")
    assert ok is True
    assert pulled == [LOCAL_DISTILL_MODEL, "qwen2.5:0.5b"]
    assert LOCAL_DISTILL_MODEL in msg
    assert "qwen2.5:0.5b" in msg


def test_setup_llamacpp_ft_already_ready(monkeypatch) -> None:
    monkeypatch.delenv("LOCI_LLAMACPP_DRAFT_MODEL", raising=False)
    _patch_llamacpp_blobs(
        monkeypatch, binary=True, tags={LOCAL_DISTILL_MODEL, "qwen2.5:0.5b"}
    )
    ok, msg = setup("llamacpp-ft")
    assert ok is True
    assert msg == "ready"


def test_resolve_client_llamacpp_ft_ignores_base_url() -> None:
    from lociaction.config import Config

    cfg = Config(
        distill_model="custom-ft",
        distill_base_url="http://localhost:11434/v1",
    )
    client = resolve_client("llamacpp-ft", cfg)
    assert client.id == "llamacpp-ft"
    assert client.provider == "openai"
    assert client.model == "custom-ft"
    assert client.base_url is None


def test_resolve_client_llamacpp_ft_default_model() -> None:
    from lociaction.config import Config

    client = resolve_client("llamacpp-ft", Config(distill_model=None))
    assert client.model == LOCAL_DISTILL_MODEL