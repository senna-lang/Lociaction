"""Ollama ローカルストアから GGUF blob パスを解決する。

Ollama の DRAFT Modelfile は safetensors/MTP 限定で、このリポジトリの
GGUF FT モデルには使えない。llama-server --model-draft に渡す実ファイル
パスを、ユーザー向けタグ（`qwen2.5:0.5b` 等）から導く。

タグ正規化:
  - `name[:tag]`           → registry.ollama.ai/library/name/tag
  - `ns/name[:tag]`        → registry.ollama.ai/ns/name/tag
  - `host/ns/name[:tag]`   → host/ns/name/tag
  - タグ省略時は `latest`

`..` / 空セグメント / 非 sha256 digest は拒否する。Ollama ストアは
ユーザー所有だが、タグと digest は外部入力になり得る。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

MODEL_LAYER_MEDIA_TYPE = "application/vnd.ollama.image.model"
DEFAULT_OLLAMA_HOST = "registry.ollama.ai"
MAX_MANIFEST_BYTES = 256 * 1024
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_SEGMENTS = {"", ".", ".."}


class OllamaBlobNotFound(ValueError):
    """タグが解決できない（未 pull、壊れた manifest、不正な digest）。"""


def ollama_models_root() -> Path:
    """`OLLAMA_MODELS` があればそれを、なければ `~/.ollama/models` を返す。"""
    raw = os.environ.get("OLLAMA_MODELS", "").strip()
    if raw:
        return Path(raw)
    return Path.home() / ".ollama" / "models"


def normalize_ollama_ref(tag: str) -> tuple[tuple[str, str, str], str]:
    """Ollama タグを `(host, namespace, name), version` に正規化する。"""
    raw = tag.strip()
    if not raw or "\x00" in raw:
        raise OllamaBlobNotFound(f"invalid Ollama model ref: {tag!r}")
    if raw.startswith("/") or raw.endswith("/"):
        raise OllamaBlobNotFound(f"invalid Ollama model ref: {tag!r}")

    if ":" in raw:
        path, version = raw.rsplit(":", 1)
    else:
        path, version = raw, "latest"
    if not path or not version or "/" in version or "\\" in version:
        raise OllamaBlobNotFound(f"invalid Ollama model ref: {tag!r}")
    _assert_safe_segment(version, kind="tag")

    parts = path.split("/")
    if any(":" in part for part in parts):
        raise OllamaBlobNotFound(f"invalid Ollama model ref: {tag!r}")
    for part in parts:
        _assert_safe_segment(part, kind="path")

    if len(parts) == 1:
        ref = (DEFAULT_OLLAMA_HOST, "library", parts[0])
    elif len(parts) == 2:
        ref = (DEFAULT_OLLAMA_HOST, parts[0], parts[1])
    elif len(parts) == 3:
        ref = (parts[0], parts[1], parts[2])
    else:
        raise OllamaBlobNotFound(f"invalid Ollama model ref: {tag!r}")
    return ref, version


def resolve_model_blob(tag: str, root: Path | None = None) -> Path:
    """タグに対応する GGUF blob の実パスを返す。無ければ OllamaBlobNotFound。"""
    models_root = Path(root) if root is not None else ollama_models_root()
    (host, namespace, name), version = normalize_ollama_ref(tag)

    manifests_root = models_root / "manifests"
    manifest = _require_under(
        manifests_root, manifests_root / host / namespace / name / version
    )
    data = _read_manifest(manifest, tag=tag)
    digest = _model_layer_digest(data, tag=tag)

    blobs_root = models_root / "blobs"
    blob = _require_under(blobs_root, blobs_root / digest.replace(":", "-", 1))
    if not blob.is_file():
        raise OllamaBlobNotFound(f"blob missing for {tag}: {blob.name}")
    return blob


def _read_manifest(manifest: Path, *, tag: str) -> dict:
    if not manifest.is_file():
        raise OllamaBlobNotFound(f"model not pulled: {tag}")
    try:
        size = manifest.stat().st_size
    except OSError as exc:
        raise OllamaBlobNotFound(f"cannot read manifest for {tag}: {exc}") from exc
    if size > MAX_MANIFEST_BYTES:
        raise OllamaBlobNotFound(f"manifest too large for {tag}")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        MemoryError,
    ) as exc:
        raise OllamaBlobNotFound(f"invalid manifest for {tag}: {exc}") from exc
    if not isinstance(data, dict):
        raise OllamaBlobNotFound(f"invalid manifest for {tag}: expected object")
    return data


def _model_layer_digest(data: dict, *, tag: str) -> str:
    layers = data.get("layers")
    if not isinstance(layers, list):
        raise OllamaBlobNotFound(f"invalid manifest for {tag}: missing layers")
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        if layer.get("mediaType") != MODEL_LAYER_MEDIA_TYPE:
            continue
        raw_digest = layer.get("digest")
        if isinstance(raw_digest, str):
            if _SHA256_DIGEST.fullmatch(raw_digest) is None:
                raise OllamaBlobNotFound(f"untrusted digest in manifest for {tag}")
            return raw_digest
    raise OllamaBlobNotFound(f"no model layer in manifest for {tag}")


def _assert_safe_segment(value: str, *, kind: str) -> None:
    if (
        value in _FORBIDDEN_SEGMENTS
        or "\x00" in value
        or ".." in value
        or value.startswith(".")
    ):
        raise OllamaBlobNotFound(f"invalid Ollama {kind} segment: {value!r}")


def _require_under(root: Path, candidate: Path) -> Path:
    """candidate が root 配下に解決されることを保証する。"""
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve()
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise OllamaBlobNotFound(f"path escapes Ollama store: {candidate}") from exc
    return resolved
