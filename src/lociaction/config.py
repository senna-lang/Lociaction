"""設定ファイルの読み込み — .lociaction/config.toml

Supports distill_provider (claude/openai) and distill_base_url for provider switching."""

from __future__ import annotations

import ipaddress
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lociaction.paths import lociaction_dir
from lociaction.utils import sanitize_terminal_text

CONFIG_FILENAME = "config.toml"
# 攻撃者制御の config.toml（クローンした repo が出荷しうる）を無制限にメモリへ
# 読み込んでパースしないための上限（LOCI-CONFIG-TOML-MEMORYERROR-DOS）。
# 正当な config.toml は通常数百 byte 程度に収まる。
MAX_CONFIG_FILE_BYTES = 256 * 1024

# ---- デフォルト値 ----

DEFAULT_DISTILL_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_DISTILL_BATCH_LIMIT = 20

# tracked config が SessionStart hook を通じて自動 distill を実行する exchange 数の
# 上限。明示的な user-scoped override がない限り clone はこの budget を超えられない。
# (LOCI-CONFIG-UNBOUNDED-BATCH-01)
MAX_DISTILL_BATCH_LIMIT = 100
DEFAULT_INDEX_MIN_CHARS = 50
DEFAULT_DISTILL_MIN_CHARS = 100
DEFAULT_DISTILL_PROVIDER = "claude"
VALID_DISTILL_PROVIDERS = frozenset({"claude", "openai"})
VALID_DISTILL_CLIENT_IDS = frozenset(
    {
        "llamacpp-ft",
        "claude-cli",
        "openai-compat",
        "codex-cli",
        "gemini-cli",
        "grok-cli",
        "opencode-cli",
        "omp-cli",
    }
)

# ローカル蒸留モデル（`loci init` の対話プロンプトで opt-in した場合のデフォルト値）。
# GGUF は Ollama 経由で hf.co/<repo>:<quant> の形式で直接 pull できる。
# 推論は `llamacpp-ft`（llama-server --model-draft）が担う。
LOCAL_DISTILL_MODEL = "hf.co/sennaLLMLearner/qwen2.5-7b-memory-distiller:Q4_K_M"

# llama.cpp 直接起動（`llamacpp-ft`）。Ollama の DRAFT 経路は GGUF/非MTP では
# 使えないので、llama-server --model-draft を ephemeral プロセスとして持つ。
LLAMACPP_SERVER_BINARY_ENV = "LOCI_LLAMACPP_SERVER"
LLAMACPP_DRAFT_MODEL_ENV = "LOCI_LLAMACPP_DRAFT_MODEL"
LLAMACPP_DRAFT_MODEL = "qwen2.5:0.5b"
LLAMACPP_DRAFT_MAX_ENV = "LOCI_LLAMACPP_DRAFT_MAX"
LLAMACPP_DRAFT_MAX = 4
LLAMACPP_GPU_LAYERS_ENV = "LOCI_LLAMACPP_GPU_LAYERS"
LLAMACPP_DRAFT_GPU_LAYERS_ENV = "LOCI_LLAMACPP_DRAFT_GPU_LAYERS"
LLAMACPP_HEALTH_TIMEOUT_ENV = "LOCI_LLAMACPP_HEALTH_TIMEOUT"
LLAMACPP_HEALTH_TIMEOUT = 120.0

# 複数プロジェクトが同時に llamacpp-ft で蒸留すると、各自が独立した ephemeral
# llama-server（フル GPU offload）を起動するため GPU/unified memory が競合する
# (LOCI-LLAMACPP-CONCURRENCY-01)。マシン全体で同時に起動できる llama-server
# インスタンス数をこの閾値に制限し、超過分はいずれかの slot が空くまで直列に
# 待たせる（`adapters/model/llama_server.llamacpp_concurrency_slot`）。
LLAMACPP_MAX_CONCURRENT_ENV = "LOCI_LLAMACPP_MAX_CONCURRENT"
LLAMACPP_MAX_CONCURRENT = 1

# project-local config.toml だけでは蒸留内容の送信先をリモートへ変更できない。
# リモート OpenAI 互換 endpoint は、呼び出すユーザーが environment で origin を許可する。
REMOTE_DISTILL_ORIGINS_ENV = "LOCIACTION_REMOTE_DISTILL_ORIGINS"
# CLI backends transmit distillation input to their configured provider. A repository
# config may select them only after the invoking user's environment names the client.
REMOTE_DISTILL_CLIENTS_ENV = "LOCIACTION_REMOTE_DISTILL_CLIENTS"
REMOTE_CLI_DISTILL_CLIENT_IDS = frozenset(
    {
        "claude-cli",
        "codex-cli",
        "gemini-cli",
        "grok-cli",
        "opencode-cli",
        "omp-cli",
    }
)



@dataclass
class Config:
    """ユーザー設定"""

    distill_model: str | None = DEFAULT_DISTILL_MODEL
    distill_batch_limit: int = DEFAULT_DISTILL_BATCH_LIMIT
    index_min_chars: int = DEFAULT_INDEX_MIN_CHARS
    distill_min_chars: int = DEFAULT_DISTILL_MIN_CHARS
    distill_provider: str = "claude"
    distill_base_url: str | None = None
    distill_client: str | None = None
    distill_unconfigured: bool = True
    config_error: str | None = None
    """config.toml の読み込み自体（TOML構文エラー/OSError）が失敗した場合のエラー
    メッセージ。未設定（ファイルなし）と区別するためのフィールド — Stop/SessionStart
    hook は stderr を `> /dev/null 2>&1` に捨てるため、警告の print だけでは背景
    実行時に気づけない。`loci status` がこのフィールドを見て明示的に警告する。
    """


def load_config(project_root: Path) -> Config:
    """project_root/.lociaction/config.toml を読んで Config を返す。
    ファイルがなければデフォルト。不正な値は警告してデフォルトにフォールバック。
    """
    config_path = lociaction_dir(project_root) / CONFIG_FILENAME
    if not config_path.exists():
        return Config()

    if config_path.is_symlink() or not config_path.is_file():
        error_message = f"refusing non-regular config file: {config_path}"
        print(f"Warning: {error_message}", file=sys.stderr)
        return Config(config_error=error_message)

    try:
        if config_path.stat().st_size > MAX_CONFIG_FILE_BYTES:
            # 攻撃者制御の config.toml（クローンした repo が出荷しうる）は
            # サイズ上限を設けず tomllib.load() すると、ファイルサイズに
            # 比例したメモリを確保して MemoryError で無条件クラッシュしうる
            # (LOCI-CONFIG-TOML-MEMORYERROR-DOS)。他の壊れた config と同じく
            # デフォルトへフォールバックする。
            error_message = (
                f"failed to parse {config_path}: file exceeds "
                f"{MAX_CONFIG_FILE_BYTES} bytes"
            )
            print(f"Warning: {error_message}", file=sys.stderr)
            return Config(config_error=error_message)
    except OSError as e:
        error_message = sanitize_terminal_text(f"failed to parse {config_path}: {e}")
        print(f"Warning: {error_message}", file=sys.stderr)
        return Config(config_error=error_message)

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError) as e:
        error_message = sanitize_terminal_text(f"failed to parse {config_path}: {e}")
        print(f"Warning: {error_message}", file=sys.stderr)
        return Config(config_error=error_message)
    except (RecursionError, MemoryError):
        # tomllib は再帰下降パーサで、深くネストした配列/inline table に
        # 明示的な深さ上限を持たない。攻撃者制御の config.toml が小さいまま
        # 極端に深くネストすると RecursionError（RuntimeError のサブクラスで
        # TOMLDecodeError/OSError に含まれない）で無条件にクラッシュしうる
        # (LOCI-CONFIG-TOML-RECURSION-DOS)。MemoryError も同じ資源枯渇系
        # 例外として一緒に扱う（サイズ上限は事前チェック済みだが、大きな
        # 単一の値が展開時に増幅するケースへの多層防御。
        # LOCI-CONFIG-TOML-MEMORYERROR-DOS）。他の壊れた config と同じく
        # デフォルトへフォールバックする。
        error_message = f"failed to parse {config_path}: input too large or too deep"
        print(f"Warning: {error_message}", file=sys.stderr)
        return Config(config_error=error_message)

    raw_distill = data.get("distill", {})
    if not isinstance(raw_distill, dict):
        print("Warning: distill must be a TOML table, ignoring.", file=sys.stderr)
        raw_distill = {}
    distill: dict[str, Any] = raw_distill

    # model は TOML 未設定なら None のまま保持し、client 解決後（下部）に client
    # 種別に応じたデフォルトへ委ねる。ここで claude 専用の DEFAULT_DISTILL_MODEL
    # を先に埋めると、client="llamacpp-ft" や legacy provider="openai" でも
    # claude のモデル名をローカル/OpenAI 互換バックエンドへ送ってしまう。
    model: str | None
    if "model" in distill:
        raw_model = distill["model"]
        if not isinstance(raw_model, str) or not raw_model.strip():
            print(
                "Warning: distill.model must be a non-empty string, using default.",
                file=sys.stderr,
            )
            model = None
        else:
            model = raw_model
    else:
        model = None

    batch_limit = distill.get("batch_limit", DEFAULT_DISTILL_BATCH_LIMIT)
    if (
        not isinstance(batch_limit, int)
        or batch_limit < 1
        or batch_limit > MAX_DISTILL_BATCH_LIMIT
    ):
        print(
            "Warning: distill.batch_limit must be a positive integer no greater "
            f"than {MAX_DISTILL_BATCH_LIMIT}, using default.",
            file=sys.stderr,
        )
        batch_limit = DEFAULT_DISTILL_BATCH_LIMIT

    raw_index = data.get("index", {})
    if not isinstance(raw_index, dict):
        print("Warning: index must be a TOML table, ignoring.", file=sys.stderr)
        raw_index = {}
    index: dict[str, Any] = raw_index

    min_chars = index.get("min_chars", DEFAULT_INDEX_MIN_CHARS)
    if not isinstance(min_chars, int) or min_chars < 1:
        print(
            "Warning: index.min_chars must be a positive integer, using default.",
            file=sys.stderr,
        )
        min_chars = DEFAULT_INDEX_MIN_CHARS

    distill_min_chars = distill.get("min_chars", DEFAULT_DISTILL_MIN_CHARS)
    if not isinstance(distill_min_chars, int) or distill_min_chars < 1:
        print(
            "Warning: distill.min_chars must be a positive integer, using default.",
            file=sys.stderr,
        )
        distill_min_chars = DEFAULT_DISTILL_MIN_CHARS

    provider = distill.get("provider", DEFAULT_DISTILL_PROVIDER)
    if not isinstance(provider, str) or provider not in VALID_DISTILL_PROVIDERS:
        print(
            "Warning: distill.provider must be one of {claude, openai}, using default.",
            file=sys.stderr,
        )
        provider = DEFAULT_DISTILL_PROVIDER

    base_url = distill.get("base_url")
    if base_url is not None and not isinstance(base_url, str):
        print(
            "Warning: distill.base_url must be a string, ignoring.",
            file=sys.stderr,
        )
        base_url = None
    elif isinstance(base_url, str):
        validated = _validate_distill_base_url(
            base_url,
            allowed_remote_origins=_allowed_remote_origins(),
        )
        if validated is None:
            print(
                "Warning: distill.base_url must be a loopback http(s) URL with no "
                f"userinfo or match {REMOTE_DISTILL_ORIGINS_ENV}.",
                file=sys.stderr,
            )
            base_url = None
        else:
            base_url = validated

    if provider == "openai" and (base_url is None or not base_url.strip()):
        print(
            "Warning: distill.provider is 'openai' but base_url is not set, falling back to 'claude'.",
            file=sys.stderr,
        )
        provider = DEFAULT_DISTILL_PROVIDER
        base_url = None

    raw_client = distill.get("client")
    provider_specified = "provider" in distill

    distill_client: str | None
    distill_unconfigured: bool
    if isinstance(raw_client, str) and raw_client in VALID_DISTILL_CLIENT_IDS:
        if remote_client_grant_missing(raw_client):
            print(
                f"Warning: distill.client '{raw_client}' requires an explicit "
                f"{REMOTE_DISTILL_CLIENTS_ENV} grant, treating distill as unconfigured.",
                file=sys.stderr,
            )
            distill_client = None
            distill_unconfigured = True
        elif raw_client == "openai-compat" and base_url is None:
            print(
                "Warning: distill.client 'openai-compat' requires a valid "
                "distill.base_url, treating distill as unconfigured.",
                file=sys.stderr,
            )
            distill_client = None
            distill_unconfigured = True
        else:
            distill_client = raw_client
            distill_unconfigured = False
    elif isinstance(raw_client, str):
        print(
            f"Warning: unknown distill.client '{sanitize_terminal_text(raw_client)}', "
            "treating distill as unconfigured.",
            file=sys.stderr,
        )
        distill_client = None
        distill_unconfigured = True
    elif provider_specified:
        # provider/base_url はここまでの検証で安全な値に確定済み（例: openai だが
        # base_url 欠落は "claude" にフォールバック済み）。それを踏まえて解決する。
        candidate_client: str
        if provider == "claude":
            candidate_client = "claude-cli"
        else:
            candidate_client = "openai-compat"
        if remote_client_grant_missing(candidate_client):
            print(
                f"Warning: distill.provider resolves to remote client '{candidate_client}', "
                f"which requires an explicit {REMOTE_DISTILL_CLIENTS_ENV} grant. "
                "Treating distill as unconfigured.",
                file=sys.stderr,
            )
            distill_client = None
            distill_unconfigured = True
        else:
            distill_client = candidate_client
            distill_unconfigured = False
    else:
        distill_client = None
        distill_unconfigured = True

    # model がまだ None（TOML 未設定/不正）で、claude 系 client に着地する場合
    # のみ claude デフォルトを補う。llamacpp-ft/openai-compat は各自のデフォルト
    # 解決に委ねる（registry.resolve_client 側で LOCAL_DISTILL_MODEL を適用、
    # あるいは openai-compat のように明示指定必須ならそこでエラーにする）。
    if model is None and distill_client in (None, "claude-cli"):
        model = DEFAULT_DISTILL_MODEL

    return Config(
        distill_model=model,
        distill_batch_limit=batch_limit,
        index_min_chars=min_chars,
        distill_min_chars=distill_min_chars,
        distill_provider=provider,
        distill_base_url=base_url,
        distill_client=distill_client,
        distill_unconfigured=distill_unconfigured,
    )


def _validate_distill_base_url(
    raw: str, *, allowed_remote_origins: frozenset[str]
) -> str | None:
    """安全な distill.base_url を返す。

    project-local config は loopback endpoint だけを既定で許可する。リモート endpoint
    は、ユーザー環境が exact origin を許可した場合だけ許可する。file:// と userinfo
    付き URL は送信先差し替えに使えるため常に拒否する。
    """
    candidate = raw.strip()
    origin = _normalized_origin(candidate, allow_path=True)
    if origin is None:
        return None
    parsed = urlparse(candidate)
    if _is_loopback_host(parsed.hostname or "") or origin in allowed_remote_origins:
        return candidate
    return None


def _allowed_remote_origins() -> frozenset[str]:
    """ユーザー環境が明示した comma-separated remote origins を正規化する。"""
    raw = os.environ.get(REMOTE_DISTILL_ORIGINS_ENV, "")
    return frozenset(
        origin
        for value in raw.split(",")
        if (origin := _normalized_origin(value.strip(), allow_path=False)) is not None
    )


def _allowed_remote_clients() -> frozenset[str]:
    """ユーザー環境が明示した remote CLI client ID だけを返す。"""
    return frozenset(
        client
        for raw_client in os.environ.get(REMOTE_DISTILL_CLIENTS_ENV, "").split(",")
        if (client := raw_client.strip()) in REMOTE_CLI_DISTILL_CLIENT_IDS
    )


def _requires_remote_client_grant(client_id: str) -> bool:
    """repository config からの選択に user-environment grant が必要な client を判定する。"""
    return client_id in REMOTE_CLI_DISTILL_CLIENT_IDS


def remote_client_grant_missing(client_id: str) -> bool:
    """CLI 層（対話選択直後の警告など）が再利用する公開ヘルパー。

    client_id が remote CLI client で、かつユーザー環境が
    `LOCIACTION_REMOTE_DISTILL_CLIENTS` で明示許可していなければ True。
    """
    return _requires_remote_client_grant(client_id) and client_id not in _allowed_remote_clients()


def _normalized_origin(value: str, *, allow_path: bool) -> str | None:
    """http(s) URL を scheme/host/port の exact-comparison 用 origin に正規化する。"""
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (not allow_path and parsed.path not in {"", "/"})
        or parsed.query
        or parsed.fragment
    ):
        return None
    default_port = 80 if parsed.scheme == "http" else 443
    port_part = "" if port is None or port == default_port else f":{port}"
    return f"{parsed.scheme}://{parsed.hostname}{port_part}"


def _is_loopback_host(hostname: str) -> bool:
    """DNS を解決せず、literal loopback IP または localhost だけを許可する。"""
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
