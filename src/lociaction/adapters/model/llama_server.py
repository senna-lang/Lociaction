"""llama-server の起動引数組み立てと ephemeral プロセス lifecycle。

Ollama の DRAFT Modelfile は safetensors/MTP 限定で、このリポジトリの
GGUF FT モデルでは classic speculative decoding に使えない。
`loci distill` 1 実行のあいだだけ llama-server を起動し、`--model-draft`
で draft モデルを載せる。常駐デーモンや PID ファイルは持たない。
embedder_server は Unix socket 常駐だが、llama-server は TCP 必須かつ
モデルロードが重いのでバッチ単位の所有が安全。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from lociaction.config import (
    LLAMACPP_DRAFT_GPU_LAYERS_ENV,
    LLAMACPP_DRAFT_MAX,
    LLAMACPP_DRAFT_MAX_ENV,
    LLAMACPP_DRAFT_MODEL,
    LLAMACPP_DRAFT_MODEL_ENV,
    LLAMACPP_GPU_LAYERS_ENV,
    LLAMACPP_HEALTH_TIMEOUT,
    LLAMACPP_HEALTH_TIMEOUT_ENV,
    LLAMACPP_SERVER_BINARY_ENV,
    LOCAL_DISTILL_MODEL,
)

LOOPBACK_HOST = "127.0.0.1"
_STOP_WAIT_SECONDS = 5.0
_HEALTH_POLL_SECONDS = 0.05
_LOG_TAIL_BYTES = 4096


class LlamaServerError(RuntimeError):
    """llama-server の起動・health check・停止に失敗した。"""


@dataclass(frozen=True)
class LlamaServerSpec:
    """llama-server 1 プロセス分の起動パラメータ。"""

    binary: Path
    model: Path
    draft_model: Path | None
    draft_max: int = LLAMACPP_DRAFT_MAX
    gpu_layers: int | None = None
    draft_gpu_layers: int | None = None
    host: str = LOOPBACK_HOST
    health_timeout: float = LLAMACPP_HEALTH_TIMEOUT


def find_llama_server_binary() -> Path | None:
    """`LOCI_LLAMACPP_SERVER` または PATH 上の llama-server を返す。"""
    raw = os.environ.get(LLAMACPP_SERVER_BINARY_ENV, "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path
        return None
    found = shutil.which("llama-server")
    return Path(found) if found else None


def configured_draft_model() -> str | None:
    """draft モデルタグ。空の env は明示 opt-out。未設定ならデフォルト。"""
    if LLAMACPP_DRAFT_MODEL_ENV in os.environ:
        raw = os.environ[LLAMACPP_DRAFT_MODEL_ENV].strip()
        return raw or None
    return LLAMACPP_DRAFT_MODEL


def spec_for_model(model_tag: str | None) -> LlamaServerSpec:
    """環境変数と Ollama blob から起動 spec を組む。draft 解決失敗は黙殺しない。"""
    binary = find_llama_server_binary()
    if binary is None:
        raise LlamaServerError(
            "llama-server binary not found. Install llama.cpp and put "
            "llama-server on PATH, or set "
            f"{LLAMACPP_SERVER_BINARY_ENV}."
        )
    tag = model_tag or LOCAL_DISTILL_MODEL
    from lociaction.adapters.model.ollama_blobs import (
        OllamaBlobNotFound,
        resolve_model_blob,
    )

    try:
        model = resolve_model_blob(tag)
    except OllamaBlobNotFound as exc:
        raise LlamaServerError(f"base model is not available: {exc}") from exc

    draft_tag = configured_draft_model()
    draft_model: Path | None = None
    if draft_tag is not None:
        try:
            draft_model = resolve_model_blob(draft_tag)
        except OllamaBlobNotFound as exc:
            raise LlamaServerError(
                f"draft model {draft_tag!r} is not pulled ({exc}). "
                f"Run `ollama pull {draft_tag}`, or unset "
                f"{LLAMACPP_DRAFT_MODEL_ENV} to disable speculative decoding."
            ) from exc

    return LlamaServerSpec(
        binary=binary,
        model=model,
        draft_model=draft_model,
        draft_max=_int_env(LLAMACPP_DRAFT_MAX_ENV, LLAMACPP_DRAFT_MAX, minimum=1),
        gpu_layers=_optional_int_env(LLAMACPP_GPU_LAYERS_ENV, minimum=0),
        draft_gpu_layers=_optional_int_env(
            LLAMACPP_DRAFT_GPU_LAYERS_ENV, minimum=0
        ),
        health_timeout=float(
            _int_env(
                LLAMACPP_HEALTH_TIMEOUT_ENV,
                int(LLAMACPP_HEALTH_TIMEOUT),
                minimum=1,
            )
        ),
    )


def build_llama_server_args(spec: LlamaServerSpec, *, port: int) -> list[str]:
    """llama-server の argv を組む。gpu layers 未設定なら -ngl を付けない。"""
    if spec.host != LOOPBACK_HOST:
        raise LlamaServerError("llama-server must bind to 127.0.0.1")
    if not 1 <= port <= 65535:
        raise LlamaServerError(f"invalid port: {port}")
    if spec.draft_max < 1:
        raise LlamaServerError(f"invalid draft_max: {spec.draft_max}")

    args = [
        str(spec.binary),
        "-m",
        str(spec.model),
        "--host",
        spec.host,
        "--port",
        str(port),
    ]
    if spec.draft_model is not None:
        args.extend(
            ["-md", str(spec.draft_model), "--draft-max", str(spec.draft_max)]
        )
    if spec.gpu_layers is not None:
        args.extend(["-ngl", str(spec.gpu_layers)])
    if spec.draft_gpu_layers is not None:
        args.extend(["-ngld", str(spec.draft_gpu_layers)])
    return args


class LlamaServerProcess:
    """llama-server を 1 distill バッチのあいだだけ所有する context manager。"""

    def __init__(
        self, spec: LlamaServerSpec, *, log_path: Path | None = None
    ) -> None:
        self.spec = spec
        self.log_path = log_path
        self.port: int | None = None
        self.base_url: str | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_file: object | None = None

    @property
    def pid(self) -> int | None:
        return None if self._proc is None else self._proc.pid

    def poll(self) -> int | None:
        if self._proc is None:
            return 0
        return self._proc.poll()

    def __enter__(self) -> LlamaServerProcess:
        port = _ephemeral_port(self.spec.host)
        args = build_llama_server_args(self.spec, port=port)
        stdout: object
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(self.log_path, "ab")
            stdout = self._log_file
        else:
            stdout = subprocess.DEVNULL
        try:
            self._proc = subprocess.Popen(
                args,
                stdout=stdout,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            self._close_log()
            raise LlamaServerError(f"failed to start llama-server: {exc}") from exc
        try:
            self._wait_healthy(port)
        except BaseException:
            self._stop()
            raise
        self.port = port
        self.base_url = f"http://{self.spec.host}:{port}/v1"
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop()

    def _wait_healthy(self, port: int) -> None:
        assert self._proc is not None
        deadline = time.monotonic() + self.spec.health_timeout
        url = f"http://{self.spec.host}:{port}/health"
        while time.monotonic() < deadline:
            code = self._proc.poll()
            if code is not None:
                raise LlamaServerError(
                    f"llama-server exited {code} before becoming healthy"
                    f"{self._log_suffix()}"
                )
            try:
                with urllib.request.urlopen(url, timeout=0.5) as resp:
                    if 200 <= getattr(resp, "status", 200) < 300:
                        return
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(_HEALTH_POLL_SECONDS)
        raise LlamaServerError(
            f"llama-server health check timed out after {self.spec.health_timeout}s"
            f"{self._log_suffix()}"
        )

    def _stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=_STOP_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=_STOP_WAIT_SECONDS)
        self._close_log()

    def _close_log(self) -> None:
        log_file = self._log_file
        self._log_file = None
        if log_file is not None:
            close = getattr(log_file, "close", None)
            if close is not None:
                close()

    def _log_suffix(self) -> str:
        if self.log_path is None or not self.log_path.is_file():
            return ""
        try:
            data = self.log_path.read_bytes()[-_LOG_TAIL_BYTES:]
            text = data.decode("utf-8", errors="replace").strip()
        except OSError:
            return ""
        if not text:
            return ""
        return f"\n--- llama-server log ---\n{text}"


def _ephemeral_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        port = sock.getsockname()[1]
    if not isinstance(port, int):
        raise LlamaServerError("failed to allocate loopback port")
    return port


def _int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise LlamaServerError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise LlamaServerError(f"{name} must be >= {minimum}, got {value}")
    return value


def _optional_int_env(name: str, *, minimum: int) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise LlamaServerError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise LlamaServerError(f"{name} must be >= {minimum}, got {value}")
    return value
