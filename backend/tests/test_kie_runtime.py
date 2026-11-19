"""Phase A guard rails for the embedded llama.cpp runtime.

These tests never load the 2.5 GB model: they cover the parts that break silently when the
pinned runtime is upgraded or the manifest drifts (struct layout, DLL presence, the
thinking switch, offload-log parsing).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.kie.runtime import bindings
from app.kie.runtime.llama import LlamaRuntime
from app.kie.runtime.manifest import MANIFEST_PATH, ManifestError, load_manifest

MODELS_ROOT = Path(__file__).resolve().parents[1] / "models" / "kie"


def test_manifest_pins_runtime_and_model() -> None:
    if not MANIFEST_PATH.is_file():
        pytest.skip("runtime artifacts not installed (run scripts/kie_fetch_runtime.py)")
    manifest = load_manifest()
    assert manifest.tag == bindings.RUNTIME_TAG
    assert set(manifest.variants) == {"vulkan", "cpu"}
    for variant in manifest.variants.values():
        assert len(variant.archive_sha256) == 64
        assert variant.archive_sha256 == variant.archive_sha256.lower()
    assert manifest.model.quant == "Q4_K_M"
    assert manifest.model.license == "Apache-2.0"
    assert len(manifest.model.sha256) == 64


def test_manifest_rejects_missing_backend() -> None:
    if not MANIFEST_PATH.is_file():
        pytest.skip("runtime artifacts not installed")
    manifest = load_manifest()
    with pytest.raises(ManifestError):
        manifest.runtime("cuda")


def test_struct_layout_matches_pinned_abi() -> None:
    # Transcribed from include/llama.h at tag b12503. If llama.cpp is upgraded these change
    # and every ctypes call becomes undefined behaviour, so the sizes are asserted here.
    assert bindings.RUNTIME_TAG == "b12503"
    assert bindings.ctypes.sizeof(bindings.LlamaModelParams) == 80
    assert bindings.ctypes.sizeof(bindings.LlamaContextParams) == 176
    assert bindings.ctypes.sizeof(bindings.LlamaBatch) == 56
    assert bindings.ctypes.sizeof(bindings.LlamaChatMessage) == 16


def test_thinking_switch_uses_soft_switch() -> None:
    messages = [{"role": "system", "content": "You are KIE."}, {"role": "user", "content": "hi"}]
    fast = LlamaRuntime.apply_thinking_switch(messages, thinking=False)
    assert fast[0]["content"].endswith("/no_think")
    assert messages[0]["content"] == "You are KIE."  # input is not mutated

    no_system = LlamaRuntime.apply_thinking_switch([{"role": "user", "content": "hi"}], thinking=False)
    assert no_system[0] == {"role": "system", "content": "/no_think"}

    thinking = LlamaRuntime.apply_thinking_switch(messages, thinking=True)
    assert thinking == messages


def test_strip_empty_thinking_only_touches_empty_blocks() -> None:
    # This GGUF renders the tags as  thinking / </think>; both spellings are handled.
    assert LlamaRuntime.strip_empty_thinking(" thinking\n\n</think>\n\nKIE runtime online.") == "KIE runtime online."
    assert LlamaRuntime.strip_empty_thinking(" thinking\n\n</think>\n\nDone") == "Done"
    reasoning = " thinking\nThe user wants one line.\n</think>\n\nDone."
    assert LlamaRuntime.strip_empty_thinking(reasoning) == reasoning
    assert LlamaRuntime.strip_empty_thinking(" thinking\nTwo checks.\n</think>\n\nDone.") == " thinking\nTwo checks.\n</think>\n\nDone."
    assert LlamaRuntime.strip_empty_thinking("plain answer") == "plain answer"
    assert LlamaRuntime.strip_empty_thinking("</think> orphan") == "</think> orphan"


def test_batch_builder_marks_last_token_for_logits() -> None:
    api = bindings.LlamaApi.__new__(bindings.LlamaApi)  # no DLL needed for make_batch
    batch, keepalive = api.make_batch([1, 2, 3], pos_start=5)
    assert batch.n_tokens == 3
    assert [batch.pos[i] for i in range(3)] == [5, 6, 7]
    assert [batch.logits[i] for i in range(3)] == [0, 0, 1]
    assert batch.n_seq_id[2] == 1 and batch.seq_id[0][0] == 0
    assert keepalive  # buffers outlive the call because the caller holds this list


def test_runtime_reports_unloaded_state() -> None:
    rt = LlamaRuntime(MODELS_ROOT / "models" / "Qwen3-4B-Q4_K_M.gguf", MODELS_ROOT / "runtime" / "b12503-cpu")
    assert rt.loaded is False
    assert rt.abi() == {}
