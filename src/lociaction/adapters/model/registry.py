"""蒸留 ModelClient の discover/setup/resolve。

v1 必須 client: llamacpp-ft, claude-cli。openai-compat は config 明示時のみ
resolve 対象になる（自動検出しない — 汎用エンドポイントを推測すると誤検出のリスクが高い）。

silent fallback 禁止: discover() は「今 Ready なもの」だけを返す。呼び出し側
（cli/init, distill --setup, runtime reselect）が Ready 一覧から選ばせる。
"""

from __future__ import annotations

import shutil
import subprocess

from lociaction.adapters.model.types import ClientStatus, ModelClient
from lociaction.config import (
    LOCAL_DISTILL_MODEL,
    MAX_CONFIG_FILE_BYTES,
)

DISCOVERABLE_CLIENT_IDS = (
    "llamacpp-ft",
    "claude-cli",
    "codex-cli",
    "gemini-cli",
    "grok-cli",
    "opencode-cli",
    "omp-cli",
)

_LLAMACPP_FT_LABEL = "llama.cpp (local FT + speculative decoding)"


def detect_llamacpp_ft() -> ClientStatus:
    """llama-server + FT/draft GGUF blob の有無を確認する。

    binary 欠如も setupable（選択後に brew / pull で揃える）。一覧から消さない。
    """
    from lociaction.adapters.model.llama_server import (
        configured_draft_model,
        find_llama_server_binary,
    )
    from lociaction.adapters.model.ollama_blobs import (
        OllamaBlobNotFound,
        resolve_model_blob,
    )

    if find_llama_server_binary() is None:
        return ClientStatus(
            id="llamacpp-ft",
            label=_LLAMACPP_FT_LABEL,
            state="setupable",
            reason="llama-server binary not found",
        )
    try:
        resolve_model_blob(LOCAL_DISTILL_MODEL)
    except OllamaBlobNotFound:
        return ClientStatus(
            id="llamacpp-ft",
            label=_LLAMACPP_FT_LABEL,
            state="setupable",
            reason=f"model not pulled: {LOCAL_DISTILL_MODEL}",
        )
    draft = configured_draft_model()
    if draft is not None:
        try:
            resolve_model_blob(draft)
        except OllamaBlobNotFound:
            return ClientStatus(
                id="llamacpp-ft",
                label=_LLAMACPP_FT_LABEL,
                state="setupable",
                reason=f"draft model not pulled: {draft}",
            )
    return ClientStatus(
        id="llamacpp-ft",
        label=_LLAMACPP_FT_LABEL,
        state="ready",
        reason="ready",
        client=ModelClient(
            id="llamacpp-ft",
            provider="openai",
            model=LOCAL_DISTILL_MODEL,
            base_url=None,
            label=_LLAMACPP_FT_LABEL,
        ),
    )


def detect_claude_cli() -> ClientStatus:
    """claude CLI の PATH 有無のみ確認する（login probe はしない — D7）"""
    from lociaction.config import DEFAULT_DISTILL_MODEL

    if shutil.which("claude") is None:
        return ClientStatus(
            id="claude-cli",
            label="Claude CLI",
            state="unavailable",
            reason="claude CLI not found in PATH",
        )
    return ClientStatus(
        id="claude-cli",
        label="Claude CLI",
        state="ready",
        reason="ready",
        client=ModelClient(
            id="claude-cli",
            provider="claude",
            model=DEFAULT_DISTILL_MODEL,
            base_url=None,
            label="Claude CLI",
        ),
    )


def detect_codex_cli() -> ClientStatus:
    """codex CLI の PATH 有無のみ確認する（login probe はしない — claude-cli と同方針、D7）"""
    if shutil.which("codex") is None:
        return ClientStatus(
            id="codex-cli",
            label="Codex CLI",
            state="unavailable",
            reason="codex CLI not found in PATH",
        )
    return ClientStatus(
        id="codex-cli",
        label="Codex CLI",
        state="ready",
        reason="ready",
        client=ModelClient(
            id="codex-cli",
            provider="codex",
            model=None,
            base_url=None,
            label="Codex CLI",
        ),
    )


def detect_gemini_cli() -> ClientStatus:
    """gemini CLI の PATH 有無のみ確認する（login probe はしない — claude-cli と同方針、D7）"""
    if shutil.which("gemini") is None:
        return ClientStatus(
            id="gemini-cli",
            label="Gemini CLI",
            state="unavailable",
            reason="gemini CLI not found in PATH",
        )
    return ClientStatus(
        id="gemini-cli",
        label="Gemini CLI",
        state="ready",
        reason="ready",
        client=ModelClient(
            id="gemini-cli",
            provider="gemini",
            model=None,
            base_url=None,
            label="Gemini CLI",
        ),
    )


def detect_grok_cli() -> ClientStatus:
    """grok CLI の PATH 有無のみ確認する（login probe はしない — claude-cli と同方針、D7）"""
    if shutil.which("grok") is None:
        return ClientStatus(
            id="grok-cli",
            label="Grok CLI",
            state="unavailable",
            reason="grok CLI not found in PATH",
        )
    return ClientStatus(
        id="grok-cli",
        label="Grok CLI",
        state="ready",
        reason="ready",
        client=ModelClient(
            id="grok-cli",
            provider="grok",
            model=None,
            base_url=None,
            label="Grok CLI",
        ),
    )


def detect_opencode_cli() -> ClientStatus:
    """opencode CLI の PATH 有無のみ確認する（login probe はしない — claude-cli と同方針、D7）"""
    if shutil.which("opencode") is None:
        return ClientStatus(
            id="opencode-cli",
            label="OpenCode CLI",
            state="unavailable",
            reason="opencode CLI not found in PATH",
        )
    return ClientStatus(
        id="opencode-cli",
        label="OpenCode CLI",
        state="ready",
        reason="ready",
        client=ModelClient(
            id="opencode-cli",
            provider="opencode",
            model=None,
            base_url=None,
            label="OpenCode CLI",
        ),
    )


def detect_omp_cli() -> ClientStatus:
    """omp CLI の PATH 有無のみ確認する（login probe はしない — claude-cli と同方針、D7）"""
    if shutil.which("omp") is None:
        return ClientStatus(
            id="omp-cli",
            label="Oh My Pi CLI",
            state="unavailable",
            reason="omp CLI not found in PATH",
        )
    return ClientStatus(
        id="omp-cli",
        label="Oh My Pi CLI",
        state="ready",
        reason="ready",
        client=ModelClient(
            id="omp-cli",
            provider="omp",
            model=None,
            base_url=None,
            label="Oh My Pi CLI",
        ),
    )


_DETECTORS = {
    "llamacpp-ft": detect_llamacpp_ft,
    "claude-cli": detect_claude_cli,
    "codex-cli": detect_codex_cli,
    "gemini-cli": detect_gemini_cli,
    "grok-cli": detect_grok_cli,
    "opencode-cli": detect_opencode_cli,
    "omp-cli": detect_omp_cli,
}


def discover() -> list[ClientStatus]:
    """DISCOVERABLE_CLIENT_IDS 順（llamacpp-ft, claude-cli, ...）で返す"""
    return [_DETECTORS[client_id]() for client_id in DISCOVERABLE_CLIENT_IDS]


def ready_clients(statuses: list[ClientStatus]) -> list[ClientStatus]:
    return [s for s in statuses if s.state == "ready"]


def selectable_clients(
    statuses: list[ClientStatus], *, include_setupable: bool = True
) -> list[ClientStatus]:
    """選択リスト: Ready に加え、opt-in なら setupable も出す。"""
    out: list[ClientStatus] = []
    for status in statuses:
        if status.state == "ready":
            out.append(status)
        elif include_setupable and status.state == "setupable":
            out.append(status)
    return out


def recommended_id(statuses: list[ClientStatus]) -> str | None:
    """llamacpp-ft が ready/setupable ならそれを推奨。なければ最初の Ready。"""
    for status in statuses:
        if status.id == "llamacpp-ft" and status.state in ("ready", "setupable"):
            return status.id
    ready = ready_clients(statuses)
    if not ready:
        return None
    return ready[0].id


def setup(client_id: str) -> tuple[bool, str]:
    """setupable な client を Ready にする。

    llamacpp-ft は llama-server を探し、無ければ `brew install llama.cpp`、
    続けて FT/draft を `ollama pull` する。
    """
    if client_id != "llamacpp-ft":
        return False, f"no automated setup for {client_id}"
    return _setup_llamacpp_ft()


def _pull_ollama_model(model: str) -> tuple[bool, str]:
    if shutil.which("ollama") is None:
        return False, (
            "ollama binary not found — install from https://ollama.com then retry"
        )
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"ollama pull failed: {e}"
    if result.returncode != 0:
        return False, f"ollama pull failed: {result.stderr.strip()}"
    return True, f"pulled {model}"


def _setup_llamacpp_ft() -> tuple[bool, str]:
    from lociaction.adapters.model.llama_server import (
        configured_draft_model,
        ensure_llama_server_binary,
    )
    from lociaction.adapters.model.ollama_blobs import (
        OllamaBlobNotFound,
        resolve_model_blob,
    )

    if ensure_llama_server_binary() is None:
        return False, (
            "llama-server not found. Install llama.cpp "
            "(e.g. `brew install llama.cpp`) and retry."
        )
    pulled: list[str] = []
    try:
        resolve_model_blob(LOCAL_DISTILL_MODEL)
    except OllamaBlobNotFound:
        ok, msg = _pull_ollama_model(LOCAL_DISTILL_MODEL)
        if not ok:
            return False, msg
        pulled.append(msg)
    draft = configured_draft_model()
    if draft is not None:
        try:
            resolve_model_blob(draft)
        except OllamaBlobNotFound:
            ok, msg = _pull_ollama_model(draft)
            if not ok:
                return False, msg
            pulled.append(msg)
    if not pulled:
        return True, "ready"
    return True, "; ".join(pulled)


def resolve_client(client_id: str, cfg) -> ModelClient:
    """config の distill_client id から ModelClient を組み立てる
    （detect はしない — 呼び出し側の責務）"""
    from lociaction.config import DEFAULT_DISTILL_MODEL

    if client_id == "claude-cli":
        return ModelClient(
            id="claude-cli",
            provider="claude",
            model=cfg.distill_model or DEFAULT_DISTILL_MODEL,
            base_url=None,
            label="Claude CLI",
        )
    if client_id == "llamacpp-ft":
        return ModelClient(
            id="llamacpp-ft",
            provider="openai",
            model=cfg.distill_model or LOCAL_DISTILL_MODEL,
            base_url=None,
            label=_LLAMACPP_FT_LABEL,
        )
    if client_id == "codex-cli":
        return ModelClient(
            id="codex-cli",
            provider="codex",
            model=cfg.distill_model,
            base_url=None,
            label="Codex CLI",
        )
    if client_id == "gemini-cli":
        return ModelClient(
            id="gemini-cli",
            provider="gemini",
            model=cfg.distill_model,
            base_url=None,
            label="Gemini CLI",
        )
    if client_id == "grok-cli":
        return ModelClient(
            id="grok-cli",
            provider="grok",
            model=cfg.distill_model,
            base_url=None,
            label="Grok CLI",
        )
    if client_id == "opencode-cli":
        return ModelClient(
            id="opencode-cli",
            provider="opencode",
            model=cfg.distill_model,
            base_url=None,
            label="OpenCode CLI",
        )
    if client_id == "omp-cli":
        return ModelClient(
            id="omp-cli",
            provider="omp",
            model=cfg.distill_model,
            base_url=None,
            label="Oh My Pi CLI",
        )
    if client_id == "openai-compat":
        if not cfg.distill_base_url:
            raise ValueError("openai-compat client requires distill.base_url")
        if not cfg.distill_model:
            raise ValueError("openai-compat client requires distill.model")
        return ModelClient(
            id="openai-compat",
            provider="openai",
            model=cfg.distill_model,
            base_url=cfg.distill_base_url,
            label="OpenAI-compatible endpoint",
        )
    raise ValueError(f"unknown distill client id: {client_id}")


def check_ready(client_id: str) -> ClientStatus:
    """単一 client の現在の Ready 状態を再確認する（runtime reselect 用）"""
    detector = _DETECTORS.get(client_id)
    if detector is None:
        # openai-compat は自動検出対象外。config の base_url が設定されていれば
        # Ready 扱い（実際の疎通は distill 実行時に確認される）。
        return ClientStatus(
            id=client_id,
            label=client_id,
            state="unavailable",
            reason=f"no detector for {client_id}",
        )
    return detector()


def write_client_config(
    config_path, client: ModelClient, *, index_min_chars: int | None = None
) -> None:
    """Write ``[distill]`` while preserving other config sections.

    ``index_min_chars`` lets interactive init persist its explicit index
    threshold; ordinary setup preserves an existing valid ``[index]`` value.
    Values are TOML-serialized, and all leaf access uses
    ``open_dir_relative()`` to reject symlink replacement races.
    """
    import errno
    import os
    import stat
    import tomllib

    import tomli_w

    from lociaction.paths import open_dir_relative

    existing: dict = {}
    try:
        read_fd = open_dir_relative(
            config_path.parent, config_path.name, os.O_RDONLY | os.O_NONBLOCK
        )
    except FileNotFoundError:
        read_fd = None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"refusing symlinked config file: {config_path}") from exc
        raise
    if read_fd is not None:
        try:
            st = os.fstat(read_fd)
            if not stat.S_ISREG(st.st_mode):
                raise ValueError(f"refusing non-regular config file: {config_path}")
            if st.st_size > MAX_CONFIG_FILE_BYTES:
                raise ValueError(
                    f"refusing config file that exceeds {MAX_CONFIG_FILE_BYTES} bytes: "
                    f"{config_path}"
                )
            with os.fdopen(read_fd, "rb") as f:
                read_fd = -1
                try:
                    existing = tomllib.load(f)
                except (
                    tomllib.TOMLDecodeError,
                    RecursionError,
                    MemoryError,
                ) as exc:
                    raise ValueError(
                        f"refusing malformed config file: {config_path}"
                    ) from exc
        finally:
            if read_fd != -1:
                os.close(read_fd)

    # [distill]/[index] は攻撃者制御の repo が出荷しうる config.toml から
    # そのまま tomllib.load() された未検証の値なので、load_config() と同じく
    # テーブル（dict）であることを確認してから使う。省略すると `distill = "x"`
    # のような scalar 代入で dict()/.get() が例外を投げてクラッシュする
    # (LOCI-REGISTRY-MALFORMED-SECTION-CRASH-01)。
    raw_distill = existing.get("distill", {})
    distill = dict(raw_distill) if isinstance(raw_distill, dict) else {}
    distill.pop("provider", None)
    distill["client"] = client.id
    if client.model:
        distill["model"] = client.model
    else:
        distill.pop("model", None)
    if client.base_url:
        distill["base_url"] = client.base_url
    else:
        distill.pop("base_url", None)

    distill_out = {
        key: distill[key]
        for key in ("client", "model", "base_url", "batch_limit", "min_chars")
        if key in distill
    }

    lines = ["# Lociaction configuration", "", "[distill]"]
    lines.append(tomli_w.dumps(distill_out).rstrip("\n"))
    lines.append("")
    lines.append("[index]")
    # existing は未検証の tomllib.load() 結果なので、load_config() と同じ型検証を
    # 経ずに手書き f-string へ埋め込むと TOML injection になる
    # (LOCI-REGISTRY-TOML-INJECT-INDEX)。[distill] と同様 tomli_w でシリアライズする。
    raw_index = existing.get("index", {})
    existing_index_min_chars = (
        raw_index.get("min_chars") if isinstance(raw_index, dict) else None
    )
    if index_min_chars is not None:
        if isinstance(index_min_chars, bool) or index_min_chars < 1:
            raise ValueError("index_min_chars must be a positive integer")
        output_index_min_chars = index_min_chars
    elif isinstance(existing_index_min_chars, int) and not isinstance(
        existing_index_min_chars, bool
    ):
        output_index_min_chars = existing_index_min_chars
    else:
        output_index_min_chars = None
    if output_index_min_chars is not None:
        lines.append(tomli_w.dumps({"min_chars": output_index_min_chars}).rstrip("\n"))
    else:
        lines.append("# min_chars = 50   # trivial フィルタ閾値（文字数）")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_fd = open_dir_relative(
            config_path.parent,
            config_path.name,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o644,
        )
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"refusing symlinked config file: {config_path}") from exc
        raise
    with os.fdopen(write_fd, "w") as f:
        f.write("\n".join(lines))
