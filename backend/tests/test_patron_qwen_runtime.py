"""Opt-in real-runtime proof that PATRON's PyTorch and Qwen can coexist.

Run alone (fresh process, real AMD Vulkan runtime):

    .venv/Scripts/python.exe -m pytest -m kie_runtime tests/test_patron_qwen_runtime.py

The original 502 happened when the server loaded PATRON (PyTorch/libiomp5md.dll)
and then the pinned llama.cpp runtime (libomp.dll) in the same process. This test
loads them in exactly that order, performs a real Qwen generation, and verifies the
process stays alive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.kie_runtime


def test_torch_then_qwen_real_vulkan_generation(tmp_path: Path) -> None:
    # Importing torch initializes Intel's OpenMP runtime. The next import must not
    # abort when llama.cpp initializes LLVM's OpenMP runtime.
    import torch  # noqa: F401

    from app.kie.config import KieConfig
    from app.kie.runtime.manifest import MANIFEST_PATH, ManifestError, load_manifest, resolve_model
    from app.kie.runtime.openmp_compat import configure_windows_openmp_compat
    from app.kie.service import KieService, parse_run_request
    from app.persistence.db import Database

    if not MANIFEST_PATH.is_file():
        pytest.skip("manifest missing (run scripts/kie_fetch_runtime.py)")
    try:
        manifest = load_manifest()
        resolve_model(manifest)
        manifest.runtime("vulkan")
    except ManifestError as exc:
        pytest.skip(str(exc))

    # This is the production guard called by create_app; setting it here keeps the
    # test about the runtime order rather than the app factory.
    configure_windows_openmp_compat()

    db = Database(tmp_path / "patron-qwen.db")
    db.initialize()
    service = KieService(config=KieConfig(n_ctx=2048, vram_budget_mb=4096, queue_max=1), db=db)
    try:
        service.load()
        status = service.status()
        assert status["backend"] == "vulkan"
        assert status["accelerated"] is True
        assert status["offloaded_layers"] > 0
        assert status["gpu_name"]
        result = service.chat(
            parse_run_request(
                message="Reply with exactly: PATRON and Qwen coexist.",
                mode="fast",
                max_tokens=16,
                temperature=0.0,
            )
        )
        assert result["backend"] == "vulkan"
        assert result["stats"]["completion_tokens"] > 0
        assert result["text"].strip()
    finally:
        service.shutdown()
