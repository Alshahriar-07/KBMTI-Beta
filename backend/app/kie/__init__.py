"""KIE — KBMTI Intelligence Engine.

Phase A (shipped): the in-process llama.cpp runtime — GGUF loading, Vulkan/CPU backend
selection, measurement. Phase B (shipped): the engine-neutral foundation — contracts,
model manager with memory budgeting and a single-flight queue, reasoning/planner/workflow
modules, tool registry and engine, run persistence and the ``/api/v1/kie`` namespace.

Higher-level behaviour (the KBMTI tool adapters, the real multi-step planner and the UI)
belongs to later phases; see ``docs/KIE_INTEGRATION_PLAN.md`` and
``docs/KIE_PHASE_B_RESULTS.md``.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.2.0-phase-b"
