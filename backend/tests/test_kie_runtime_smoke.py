"""Real-runtime smoke test for Phase B (opt-in).

This is the only KIE test that loads the pinned GGUF through llama.dll and touches the
GPU. It is excluded from the default run (``-m 'not kie_runtime'``) and invoked with:

    .venv/Scripts/python.exe -m pytest -m kie_runtime tests/test_kie_runtime_smoke.py

It asserts behaviour, not performance: the model loads, the backend identity is honest,
one short generation completes through the KieService, and unload releases the context.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.kie.config import KieConfig
from app.kie.runtime.manifest import MANIFEST_PATH, ManifestError, load_manifest, resolve_model
from app.kie.service import KieService, parse_run_request
from app.persistence.db import Database

pytestmark = pytest.mark.kie_runtime


def _artifacts_ready() -> tuple[bool, str]:
    if not MANIFEST_PATH.is_file():
        return False, "manifest missing (run scripts/kie_fetch_runtime.py)"
    try:
        manifest = load_manifest()
        resolve_model(manifest)
        manifest.runtime("vulkan")
    except ManifestError as exc:
        return False, str(exc)
    return True, ""


def test_real_model_loads_generates_and_unloads(tmp_path: Path) -> None:
    ready, reason = _artifacts_ready()
    if not ready:
        pytest.skip(reason)

    db = Database(tmp_path / "kie-smoke.db")
    db.initialize()
    service = KieService(
        config=KieConfig(n_ctx=2048, vram_budget_mb=4096, queue_max=1),
        db=db,
    )
    try:
        loaded = service.load()
        assert loaded["memory"]["measured_mb"] > 0
        status = service.status()
        assert status["backend"] == "vulkan"
        assert status["state"] == "ready"
        assert status["health_state"] == "READY"
        assert status["accelerated"] is True
        assert status["memory"]["offloaded_layers"] > 0
        assert status["identity"]["devices"], "Vulkan identity must name the device"
        assert status["gpu_name"], "health must name the detected GPU"
        assert status["smoke_test"]["generated_tokens"] > 0

        result = service.chat(
            parse_run_request(
                message="Reply with exactly: KIE phase B online.",
                mode="fast",
                max_tokens=24,
                temperature=0.0,
            )
        )
        assert result["text"].strip()
        assert result["backend"] == status["backend"]
        assert result["stats"]["completion_tokens"] > 0
        assert result["stats"]["prompt_tokens"] > 0
        stored = service.repository.get_run(result["run_id"])
        assert stored is not None and stored["status"] == "done"
    finally:
        service.shutdown()

    assert service.status()["state"] == "unloaded"
