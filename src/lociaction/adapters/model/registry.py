"""蒸留 ModelClient の discover/setup/resolve。

v1 必須 client: ollama-ft, claude-cli。openai-compat は config 明示時のみ resolve
対象になる（自動検出しない — 汎用エンドポイントを推測すると誤検出のリスクが高い）。

silent fallback 禁止: discover() は「今 Ready なもの」だけを返す。呼び出し側
（cli/init, distill --setup, runtime reselect）が Ready 一覧から選ばせる。
"""

from __future__ import annotations

import shutil
import subprocess

from lociaction.adapters.model.types import ClientStatus, ModelClient
from lociaction.config import LOCAL_DISTILL_BASE_URL, LOCAL_DISTILL_MODEL

# v1 で discover() が調べる client id（表示順 = recommended 優先度）
DISCOVERABLE_CLIENT_IDS = (
    "ollama-ft",
    "claude-cli",
    "codex-cli",
    "gemini-cli",
    "grok-cli",
    "opencode-cli",
    "omp-cli",
)


def _ollama_model_pulled(model: str) -> bool:
    """`ollama list` の NAME 列が model と完全一致する行があるか確認する。

    部分一致だと `qwen2.5-7b` が `qwen2.5-7b-instruct` に誤ヒットするため、
    各行の先頭列（NAME、空白区切り）のみを比較する。1行目はヘッダなのでスキップ。
    """
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10
        )
    except (subprocess.SubprocessError, OSError):
        return False
    if result.returncode != 0:
        return False
    lines = result.stdout.splitlines()[1:]  # ヘッダ行 "NAME ..." を除く
    names = {line.split()[0] for line in lines if line.split()}
    return model in names


def detect_ollama_ft() -> ClientStatus:
    """Ollama binary + FT model の pull 状態を確認する"""
    if shutil.which("ollama") is None:
        return ClientStatus(
            id="ollama-ft",
            label="Ollama (local FT model)",
            state="unavailable",
            reason="ollama binary not found in PATH",
        )
    if not _ollama_model_pulled(LOCAL_DISTILL_MODEL):
        return ClientStatus(
            id="ollama-ft",
            label="Ollama (local FT model)",
            state="setupable",
            reason=f"model not pulled: {LOCAL_DISTILL_MODEL}",
        )
    return ClientStatus(
        id="ollama-ft",
        label="Ollama (local FT model)",
        state="ready",
        reason="ready",
        client=ModelClient(
            id="ollama-ft",
            provider="openai",
            model=LOCAL_DISTILL_MODEL,
            base_url=LOCAL_DISTILL_BASE_URL,
            label="Ollama (local FT model)",
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
    "ollama-ft": detect_ollama_ft,
    "claude-cli": detect_claude_cli,
    "codex-cli": detect_codex_cli,
    "gemini-cli": detect_gemini_cli,
    "grok-cli": detect_grok_cli,
    "opencode-cli": detect_opencode_cli,
    "omp-cli": detect_omp_cli,
}


def discover() -> list[ClientStatus]:
    """v1 必須 client を検出順（ollama-ft, claude-cli, codex-cli, gemini-cli）で返す"""
    return [_DETECTORS[client_id]() for client_id in DISCOVERABLE_CLIENT_IDS]


def ready_clients(statuses: list[ClientStatus]) -> list[ClientStatus]:
    return [s for s in statuses if s.state == "ready"]


def recommended_id(statuses: list[ClientStatus]) -> str | None:
    """Ready なら ollama-ft を推奨、なければ最初の Ready、なければ None"""
    ready = ready_clients(statuses)
    if not ready:
        return None
    for s in ready:
        if s.id == "ollama-ft":
            return s.id
    return ready[0].id


def setup(client_id: str) -> tuple[bool, str]:
    """setupable な client を Ready にする（今は ollama-ft の `ollama pull` のみ）。

    binary 自体のインストールは実行しない — 案内のみ（D6）。
    """
    if client_id != "ollama-ft":
        return False, f"no automated setup for {client_id}"
    if shutil.which("ollama") is None:
        return False, (
            "ollama binary not found — install from "
            "https://ollama.com then retry"
        )
    try:
        result = subprocess.run(
            ["ollama", "pull", LOCAL_DISTILL_MODEL],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"ollama pull failed: {e}"
    if result.returncode != 0:
        return False, f"ollama pull failed: {result.stderr.strip()}"
    return True, f"pulled {LOCAL_DISTILL_MODEL}"


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
    if client_id == "ollama-ft":
        return ModelClient(
            id="ollama-ft",
            provider="openai",
            model=cfg.distill_model or LOCAL_DISTILL_MODEL,
            base_url=cfg.distill_base_url or LOCAL_DISTILL_BASE_URL,
            label="Ollama (local FT model)",
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


def write_client_config(config_path, client: ModelClient) -> None:
    """config.toml の [distill] を client/model/base_url で上書きする（他セクションは保持、
    legacy `provider` キーは書かない）。init と `loci distill --setup` の共通実装。

    値は tomli_w でシリアライズする（手書き f-string 組み立てだと base_url/model に
    `"` や `\\` が含まれた際に config.toml が壊れ、次回起動のパースが失敗するため）。
    """
    import tomllib

    import tomli_w

    existing: dict = {}
    if config_path.exists():
        with config_path.open("rb") as f:
            existing = tomllib.load(f)

    distill = dict(existing.get("distill", {}))
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
    index_min_chars = existing.get("index", {}).get("min_chars")
    if index_min_chars is not None:
        lines.append(f"min_chars = {index_min_chars}")
    else:
        lines.append("# min_chars = 50   # trivial フィルタ閾値（文字数）")
    lines.append("")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines))
