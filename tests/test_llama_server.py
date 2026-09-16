"""lociaction.adapters.model.llama_server のユニットテスト

build_llama_server_args は純関数。LlamaServerProcess は
tests/fixtures/fake_llama_server.py を実プロセスとして起動し、
start/health/stop と孤児プロセスが残らないことを検証する。
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lociaction.adapters.model.llama_server import (
    LlamaServerError,
    LlamaServerProcess,
    LlamaServerSpec,
    build_llama_server_args,
    configured_draft_model,
    default_gpu_layers,
    find_llama_server_binary,
)

FAKE = Path(__file__).parent / "fixtures" / "fake_llama_server.py"


@pytest.fixture
def fake_binary() -> Path:
    FAKE.chmod(FAKE.stat().st_mode | 0o111)
    return FAKE


def _spec(
    fake_binary: Path,
    tmp_path: Path,
    *,
    draft: bool = True,
    gpu_layers: int | None = None,
    draft_gpu_layers: int | None = None,
    draft_max: int = 4,
    health_timeout: float = 5.0,
) -> LlamaServerSpec:
    model = tmp_path / "base.gguf"
    model.write_bytes(b"GGUF")
    draft_path = None
    if draft:
        draft_path = tmp_path / "draft.gguf"
        draft_path.write_bytes(b"GGUF")
    return LlamaServerSpec(
        binary=fake_binary,
        model=model,
        draft_model=draft_path,
        draft_max=draft_max,
        gpu_layers=gpu_layers,
        draft_gpu_layers=draft_gpu_layers,
        health_timeout=health_timeout,
    )


# ---- build_llama_server_args ----


def test_args_include_model_host_port(fake_binary: Path, tmp_path: Path) -> None:
    spec = _spec(fake_binary, tmp_path, draft=False)
    args = build_llama_server_args(spec, port=18081)
    assert args[0] == str(fake_binary)
    assert args[args.index("-m") + 1] == str(spec.model)
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--port") + 1] == "18081"
    assert "-md" not in args
    assert "--draft-max" not in args
    assert "-ngl" not in args
    assert "-ngld" not in args


def test_args_include_draft_when_set(fake_binary: Path, tmp_path: Path) -> None:
    spec = _spec(fake_binary, tmp_path, draft=True, draft_max=4)
    args = build_llama_server_args(spec, port=9)
    assert args[args.index("-md") + 1] == str(spec.draft_model)
    assert args[args.index("--draft-max") + 1] == "4"


def test_args_include_gpu_layers_only_when_set(
    fake_binary: Path, tmp_path: Path
) -> None:
    spec = _spec(
        fake_binary, tmp_path, draft=True, gpu_layers=99, draft_gpu_layers=99
    )
    args = build_llama_server_args(spec, port=9)
    assert args[args.index("-ngl") + 1] == "99"
    assert args[args.index("-ngld") + 1] == "99"


def test_args_zero_gpu_layers_is_explicit(fake_binary: Path, tmp_path: Path) -> None:
    spec = _spec(fake_binary, tmp_path, draft=False, gpu_layers=0)
    args = build_llama_server_args(spec, port=9)
    assert args[args.index("-ngl") + 1] == "0"


def test_args_reject_invalid_port(fake_binary: Path, tmp_path: Path) -> None:
    spec = _spec(fake_binary, tmp_path, draft=False)
    with pytest.raises(LlamaServerError, match="port"):
        build_llama_server_args(spec, port=0)


def test_args_reject_non_positive_draft_max(
    fake_binary: Path, tmp_path: Path
) -> None:
    spec = _spec(fake_binary, tmp_path, draft=True, draft_max=0)
    with pytest.raises(LlamaServerError, match="draft"):
        build_llama_server_args(spec, port=9)


# ---- find_llama_server_binary / configured_draft_model ----


def test_find_binary_env_override(fake_binary: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCI_LLAMACPP_SERVER", str(fake_binary))
    assert find_llama_server_binary() == fake_binary


def test_find_binary_env_missing_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCI_LLAMACPP_SERVER", str(tmp_path / "nope"))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/llama-server")
    assert find_llama_server_binary() is None


def test_find_binary_falls_back_to_which(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "llama-server"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.delenv("LOCI_LLAMACPP_SERVER", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: str(binary) if name == "llama-server" else None)
    assert find_llama_server_binary() == binary


def test_find_binary_none_when_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LOCI_LLAMACPP_SERVER", raising=False)
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.shutil.which", lambda name: None
    )
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.Path.home",
        lambda *a, **k: tmp_path,
    )
    assert find_llama_server_binary() is None


def test_find_binary_home_llama_cpp_build(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "llama.cpp" / "build" / "bin" / "llama-server"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.delenv("LOCI_LLAMACPP_SERVER", raising=False)
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.shutil.which", lambda name: None
    )
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.Path.home",
        lambda *a, **k: tmp_path,
    )
    assert find_llama_server_binary() == binary


def test_default_gpu_layers_apple_silicon(monkeypatch) -> None:
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.sys.platform", "darwin"
    )
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.platform.machine",
        lambda: "arm64",
    )
    assert default_gpu_layers() == 99


def test_default_gpu_layers_non_darwin(monkeypatch) -> None:
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.sys.platform", "linux"
    )
    monkeypatch.setattr(
        "lociaction.adapters.model.llama_server.platform.machine",
        lambda: "x86_64",
    )
    assert default_gpu_layers() is None


def test_configured_draft_model_default(monkeypatch) -> None:
    monkeypatch.delenv("LOCI_LLAMACPP_DRAFT_MODEL", raising=False)
    assert configured_draft_model() == "qwen2.5:0.5b"


def test_configured_draft_model_empty_is_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("LOCI_LLAMACPP_DRAFT_MODEL", "  ")
    assert configured_draft_model() is None


def test_configured_draft_model_override(monkeypatch) -> None:
    monkeypatch.setenv("LOCI_LLAMACPP_DRAFT_MODEL", "phi3:latest")
    assert configured_draft_model() == "phi3:latest"


# ---- LlamaServerProcess ----


def test_process_ready_then_stops(fake_binary: Path, tmp_path: Path) -> None:
    spec = _spec(fake_binary, tmp_path)
    log_path = tmp_path / "llama-server.log"
    with LlamaServerProcess(spec, log_path=log_path) as proc:
        assert proc.port is not None
        assert proc.base_url == f"http://127.0.0.1:{proc.port}/v1"
        with urllib.request.urlopen(f"http://127.0.0.1:{proc.port}/health") as resp:
            assert resp.status == 200
        assert proc.poll() is None
    assert proc.poll() is not None
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(f"http://127.0.0.1:{proc.port}/health", timeout=0.5)


def test_process_stops_after_body_exception(
    fake_binary: Path, tmp_path: Path
) -> None:
    spec = _spec(fake_binary, tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        with LlamaServerProcess(spec, log_path=tmp_path / "x.log") as proc:
            raise RuntimeError("boom")
    assert proc.poll() is not None

def test_process_die_before_health_raises(
    fake_binary: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_LLAMA_MODE", "die")
    spec = _spec(fake_binary, tmp_path, health_timeout=2.0)
    log_path = tmp_path / "die.log"
    with pytest.raises(LlamaServerError, match="exited"):
        with LlamaServerProcess(spec, log_path=log_path):
            raise AssertionError("must not enter")
    # ログに dying メッセージが残る
    assert "dying" in log_path.read_text()


def test_process_health_timeout_kills_hanging_binary(
    fake_binary: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_LLAMA_MODE", "hang")
    spec = _spec(fake_binary, tmp_path, health_timeout=0.4)
    with pytest.raises(LlamaServerError, match="timed out"):
        with LlamaServerProcess(spec, log_path=tmp_path / "hang.log"):
            raise AssertionError("must not enter")


def test_process_missing_binary_raises(tmp_path: Path) -> None:
    spec = LlamaServerSpec(
        binary=tmp_path / "missing-llama-server",
        model=tmp_path / "base.gguf",
        draft_model=None,
        health_timeout=0.2,
    )
    (tmp_path / "base.gguf").write_bytes(b"GGUF")
    with pytest.raises(LlamaServerError, match="failed to start"):
        with LlamaServerProcess(spec):
            raise AssertionError("must not enter")
