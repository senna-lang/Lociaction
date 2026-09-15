"""蒸留 ModelClient の discover/setup/resolve。

v1 必須 client: ollama-ft, claude-cli。openai-compat は config 明示時のみ resolve
対象になる（自動検出しない — 汎用エンドポイントを推測すると誤検出のリスクが高い）。

silent fallback 禁止: discover() は「今 Ready なもの」だけを返す。呼び出し側
（cli/init, distill --setup, runtime reselect）が Ready 一覧から選ばせる。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from lociaction.adapters.model.types import ClientStatus, ModelClient
from lociaction.config import (
    LOCAL_DISTILL_BASE_URL,
    LOCAL_DISTILL_DRAFT_MODEL,
    LOCAL_DISTILL_DRAFT_NUM_PREDICT,
    LOCAL_DISTILL_DRAFTER_MODEL,
    LOCAL_DISTILL_MODEL,
    MAX_CONFIG_FILE_BYTES,
)

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

    `model` がタグ無し（`:` を含まない）場合は `ollama create`/`pull` が
    暗黙で付与する `:latest` も許可する。`loci-distiller` を `ollama create`
    すると `ollama list` には `loci-distiller:latest` として現れるため、
    タグ無し参照はこの暗黙タグを認識できないと常に setupable のまま誤判定する。
    タグ付き名（`hf.co/...:Q4_K_M` 等）は従来通り完全一致のみ。
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
    if model in names:
        return True
    if ":" not in model:
        return f"{model}:latest" in names
    return False


def detect_ollama_ft() -> ClientStatus:
    """Ollama binary + FT本体 + drafter(loci-distiller) の状態を確認する。

    drafter モデル作成済みなら ready で、以後の新規セットアップはこちらを
    優先する。FT本体だけ pull 済み（drafter 未作成）でも ready のままにする
    ——既存 config.toml が既に `model = "<生のFTモデル名>"` を明示している
    ユーザーの `loci distill` を「not ready」扱いにして自動蒸留を止めない
    ため（drafter はあくまで新規セットアップ時の任意の高速化であり、
    既存の動作する設定を壊してはならない）。どちらも無ければ setupable。
    """
    if shutil.which("ollama") is None:
        return ClientStatus(
            id="ollama-ft",
            label="Ollama (local FT model)",
            state="unavailable",
            reason="ollama binary not found in PATH",
        )
    if _ollama_model_pulled(LOCAL_DISTILL_DRAFTER_MODEL):
        return ClientStatus(
            id="ollama-ft",
            label="Ollama (local FT model)",
            state="ready",
            reason="ready",
            client=ModelClient(
                id="ollama-ft",
                provider="openai",
                model=LOCAL_DISTILL_DRAFTER_MODEL,
                base_url=LOCAL_DISTILL_BASE_URL,
                label="Ollama (local FT model)",
            ),
        )
    if _ollama_model_pulled(LOCAL_DISTILL_MODEL):
        return ClientStatus(
            id="ollama-ft",
            label="Ollama (local FT model)",
            state="ready",
            reason="ready (no speculative-decoding drafter; run "
            "`loci distill --setup` to add one)",
            client=ModelClient(
                id="ollama-ft",
                provider="openai",
                model=LOCAL_DISTILL_MODEL,
                base_url=LOCAL_DISTILL_BASE_URL,
                label="Ollama (local FT model)",
            ),
        )
    return ClientStatus(
        id="ollama-ft",
        label="Ollama (local FT model)",
        state="setupable",
        reason=f"model not pulled: {LOCAL_DISTILL_MODEL}",
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


def _ollama_pull(model: str) -> tuple[bool, str] | None:
    """`ollama pull` を実行する。既に pull 済みなら None を返し呼び出し側に
    スキップさせる（無駄な再ダウンロード確認を避ける）。"""
    if _ollama_model_pulled(model):
        return None
    try:
        result = subprocess.run(
            ["ollama", "pull", model],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"ollama pull failed ({model}): {e}"
    if result.returncode != 0:
        return False, f"ollama pull failed ({model}): {result.stderr.strip()}"
    return True, f"pulled {model}"


def _create_drafter_model() -> tuple[bool, str]:
    """FT 本体 (LOCAL_DISTILL_MODEL) + speculative decoding drafter
    (LOCAL_DISTILL_DRAFT_MODEL) を結合した LOCAL_DISTILL_DRAFTER_MODEL を
    `ollama create` で作る。drafter は本体の出力（greedy）を変えず、生成速度
    だけを上げる。"""
    modelfile = (
        f"FROM {LOCAL_DISTILL_MODEL}\n"
        f"DRAFT {LOCAL_DISTILL_DRAFT_MODEL}\n"
        f"PARAMETER draft_num_predict {LOCAL_DISTILL_DRAFT_NUM_PREDICT}\n"
    )
    fd, modelfile_path = tempfile.mkstemp(suffix=".Modelfile", text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(modelfile)
        result = subprocess.run(
            ["ollama", "create", LOCAL_DISTILL_DRAFTER_MODEL, "-f", modelfile_path],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"ollama create failed: {e}"
    finally:
        os.unlink(modelfile_path)
    if result.returncode != 0:
        return False, f"ollama create failed: {result.stderr.strip()}"
    return True, (
        f"created {LOCAL_DISTILL_DRAFTER_MODEL} "
        f"(drafter: {LOCAL_DISTILL_DRAFT_MODEL})"
    )


def setup(client_id: str) -> tuple[bool, str]:
    """setupable な client を Ready にする。ollama-ft は FT本体 + drafter を
    pull し、両者を結合した drafter-enabled モデルを `ollama create` する。

    binary 自体のインストールは実行しない — 案内のみ（D6）。
    """
    if client_id != "ollama-ft":
        return False, f"no automated setup for {client_id}"
    if shutil.which("ollama") is None:
        return False, (
            "ollama binary not found — install from "
            "https://ollama.com then retry"
        )
    for model in (LOCAL_DISTILL_MODEL, LOCAL_DISTILL_DRAFT_MODEL):
        pull_result = _ollama_pull(model)
        if pull_result is not None and not pull_result[0]:
            return pull_result
    return _create_drafter_model()


def upgrade_ollama_ft_drafter_if_missing() -> tuple[bool, str] | None:
    """既存ユーザー（`ollama-ft` が生の FT 本体のまま ready）に drafter を
    自動で追加する。ollama-ft が ready でない、または既に drafter 済みなら
    None を返し何もしない（既存 config を無条件に触らないための境界）。

    呼び出し側は interactive context（`loci init`/`loci distill --setup`/
    対話的な `loci distill`）でのみこれを呼ぶこと——ネットワーク越しの
    `ollama pull` を伴いうるため、非対話の hook 実行から呼ぶと自動化が
    無言でモデルを取得し始めてしまう。
    """
    status = detect_ollama_ft()
    if status.state != "ready" or status.client is None:
        return None
    if status.client.model != LOCAL_DISTILL_MODEL:
        return None
    return setup("ollama-ft")


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
            model=cfg.distill_model or LOCAL_DISTILL_DRAFTER_MODEL,
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

    leaf の open は `open_dir_relative()`（openat 相当）で行い、is_symlink()
    チェックと別の write_text() 呼び出しの間に symlink を仕込まれる TOCTOU
    window も、親 `.lociaction/` 自体を後から symlink にすり替えるレースも
    構造的に閉じる（`.gitignore`/`distill.lock` に既に適用済みの同じパターンを
    dir_fd 経由へ強化したもの。LOCI-REGISTRY-CONFIG-TOCTOU-01 /
    LOCI-REGISTRY-CONFIGDIR-TOCTOU-01）。
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
            raise ValueError(
                f"refusing symlinked config file: {config_path}"
            ) from exc
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
    raw_index_min_chars = raw_index.get("min_chars") if isinstance(raw_index, dict) else None
    if isinstance(raw_index_min_chars, int) and not isinstance(
        raw_index_min_chars, bool
    ):
        lines.append(tomli_w.dumps({"min_chars": raw_index_min_chars}).rstrip("\n"))
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
            raise ValueError(
                f"refusing symlinked config file: {config_path}"
            ) from exc
        raise
    with os.fdopen(write_fd, "w") as f:
        f.write("\n".join(lines))
