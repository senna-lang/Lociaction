"""lociaction.adapters.model.ollama_blobs のユニットテスト

Ollama のローカル manifest から GGUF 実パスを解決する純関数のテスト。
実 Ollama ストアには依存せず、tmp_path 上に manifest/blob を組み立てる。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lociaction.adapters.model.ollama_blobs import (
    MODEL_LAYER_MEDIA_TYPE,
    OllamaBlobNotFound,
    normalize_ollama_ref,
    ollama_models_root,
    resolve_model_blob,
)

# ---- normalize_ollama_ref ----


def test_normalize_short_library_ref() -> None:
    assert normalize_ollama_ref("qwen2.5:0.5b") == (
        ("registry.ollama.ai", "library", "qwen2.5"),
        "0.5b",
    )


def test_normalize_defaults_tag_to_latest() -> None:
    assert normalize_ollama_ref("loci-distiller") == (
        ("registry.ollama.ai", "library", "loci-distiller"),
        "latest",
    )


def test_normalize_hf_three_segment_ref() -> None:
    assert normalize_ollama_ref(
        "hf.co/sennaLLMLearner/qwen2.5-7b-memory-distiller:Q4_K_M"
    ) == (("hf.co", "sennaLLMLearner", "qwen2.5-7b-memory-distiller"), "Q4_K_M")


def test_normalize_two_segment_ref_uses_default_host() -> None:
    # Ollama は `ns/name` を既定ホスト上の namespace/name として扱う
    assert normalize_ollama_ref("myns/mymodel:v1") == (
        ("registry.ollama.ai", "myns", "mymodel"),
        "v1",
    )


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "   ",
        "a/b/c/d:latest",  # 4 セグメントは Ollama の名前空間に存在しない
        "../escape:latest",
        "hf.co/../name:latest",
        "qwen2.5:../../etc/passwd",
        "qwen2.5:",
        "/qwen2.5:0.5b",
        "qwen2.5:0.5b/extra",
        "qwen\x00null:latest",
        ".:latest",
    ],
)
def test_normalize_rejects_malformed_or_traversing_refs(ref: str) -> None:
    with pytest.raises(OllamaBlobNotFound):
        normalize_ollama_ref(ref)


# ---- ollama_models_root ----


def test_models_root_honours_ollama_models_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "store"))
    assert ollama_models_root() == tmp_path / "store"


def test_models_root_defaults_to_home(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    assert ollama_models_root() == Path.home() / ".ollama" / "models"


def test_models_root_ignores_blank_env(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_MODELS", "   ")
    assert ollama_models_root() == Path.home() / ".ollama" / "models"


# ---- resolve_model_blob ----

DIGEST = "sha256:" + "a" * 64


def _write_store(
    root: Path,
    *,
    ref_path: tuple[str, ...] = ("registry.ollama.ai", "library", "qwen2.5"),
    tag: str = "0.5b",
    layers: list[dict] | None = None,
    create_blob: bool = True,
    raw: str | None = None,
) -> Path:
    manifest = root.joinpath("manifests", *ref_path) / tag
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        manifest.write_text(raw, encoding="utf-8")
    else:
        if layers is None:
            layers = [{"mediaType": MODEL_LAYER_MEDIA_TYPE, "digest": DIGEST}]
        manifest.write_text(json.dumps({"layers": layers}), encoding="utf-8")
    blob = root / "blobs" / DIGEST.replace(":", "-")
    if create_blob:
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(b"GGUF\x00\x00\x00\x00")
    return blob


def test_resolve_returns_model_layer_blob(tmp_path: Path) -> None:
    blob = _write_store(tmp_path)
    assert resolve_model_blob("qwen2.5:0.5b", root=tmp_path) == blob


def test_resolve_picks_model_layer_among_others(tmp_path: Path) -> None:
    blob = _write_store(
        tmp_path,
        layers=[
            {
                "mediaType": "application/vnd.ollama.image.template",
                "digest": "sha256:" + "b" * 64,
            },
            {"mediaType": MODEL_LAYER_MEDIA_TYPE, "digest": DIGEST},
            {
                "mediaType": "application/vnd.ollama.image.license",
                "digest": "sha256:" + "c" * 64,
            },
        ],
    )
    assert resolve_model_blob("qwen2.5:0.5b", root=tmp_path) == blob


def test_resolve_hf_ref(tmp_path: Path) -> None:
    blob = _write_store(
        tmp_path,
        ref_path=("hf.co", "sennaLLMLearner", "qwen2.5-7b-memory-distiller"),
        tag="Q4_K_M",
    )
    ref = "hf.co/sennaLLMLearner/qwen2.5-7b-memory-distiller:Q4_K_M"
    assert resolve_model_blob(ref, root=tmp_path) == blob


def test_resolve_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(OllamaBlobNotFound, match="not pulled"):
        resolve_model_blob("qwen2.5:0.5b", root=tmp_path)


def test_resolve_malformed_manifest_raises(tmp_path: Path) -> None:
    _write_store(tmp_path, raw="{not json")
    with pytest.raises(OllamaBlobNotFound, match="manifest"):
        resolve_model_blob("qwen2.5:0.5b", root=tmp_path)


def test_resolve_manifest_without_model_layer_raises(tmp_path: Path) -> None:
    _write_store(
        tmp_path,
        layers=[
            {
                "mediaType": "application/vnd.ollama.image.template",
                "digest": "sha256:" + "b" * 64,
            }
        ],
    )
    with pytest.raises(OllamaBlobNotFound, match="model layer"):
        resolve_model_blob("qwen2.5:0.5b", root=tmp_path)


def test_resolve_missing_blob_file_raises(tmp_path: Path) -> None:
    _write_store(tmp_path, create_blob=False)
    with pytest.raises(OllamaBlobNotFound, match="blob"):
        resolve_model_blob("qwen2.5:0.5b", root=tmp_path)


@pytest.mark.parametrize(
    "digest",
    [
        "sha256:../../etc/passwd",
        "sha512:" + "a" * 64,
        "sha256:" + "a" * 63,
        "sha256:" + "A" * 64,
        "",
        "deadbeef",
    ],
)
def test_resolve_rejects_untrusted_digest(tmp_path: Path, digest: str) -> None:
    _write_store(
        tmp_path,
        layers=[{"mediaType": MODEL_LAYER_MEDIA_TYPE, "digest": digest}],
    )
    with pytest.raises(OllamaBlobNotFound, match="digest"):
        resolve_model_blob("qwen2.5:0.5b", root=tmp_path)


def test_resolve_rejects_oversized_manifest(tmp_path: Path) -> None:
    _write_store(tmp_path, raw=" " * (2 * 1024 * 1024))
    with pytest.raises(OllamaBlobNotFound, match="too large"):
        resolve_model_blob("qwen2.5:0.5b", root=tmp_path)


def test_resolve_rejects_non_object_manifest(tmp_path: Path) -> None:
    _write_store(tmp_path, raw="[]")
    with pytest.raises(OllamaBlobNotFound, match="manifest"):
        resolve_model_blob("qwen2.5:0.5b", root=tmp_path)


def test_resolve_uses_env_root_when_root_omitted(monkeypatch, tmp_path: Path) -> None:
    blob = _write_store(tmp_path)
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path))
    assert resolve_model_blob("qwen2.5:0.5b") == blob
