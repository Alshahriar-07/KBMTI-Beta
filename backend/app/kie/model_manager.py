"""Model lifecycle and the single-flight inference slot.

One model, one context, one generation at a time. The manager owns:

* **backend selection** — Vulkan first, CPU as a documented fallback, with the
  fallback reason recorded so the API can never present CPU speed as GPU speed;
* **memory accounting** — the sum of the model / KV / compute buffers llama.cpp
  reports at load time, checked against the configured budget. If the GPU does not
  fit, the manager retries with fewer offloaded layers; if it still does not fit, it
  unloads and fails instead of paging;
* **the queue** — an explicit single-flight slot with a bounded wait, because two
  concurrent generations on 8 GB of VRAM are not a goal.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.kie.config import KieConfig
from app.kie.contracts import EnginePort, MemoryBudget, ModelState
from app.kie.errors import (
    KieBusyError,
    KieMemoryBudgetError,
    ModelLoadFailedError,
    ModelLoadingError,
    ModelNotLoadedError,
)
from app.kie.runtime.manifest import KieManifest, load_manifest, resolve_model

logger = logging.getLogger(__name__)

# Lines look like: "load_tensors:      Vulkan0 model buffer size =  2375.91 MiB"
_BUFFER_RE = re.compile(
    r"(?P<device>[A-Za-z0-9_]+)\s+(?P<kind>model|KV|compute|output) buffer size\s*=\s*(?P<mib>[\d.]+)\s*MiB"
)
_OFFLOAD_RE = re.compile(r"offloaded (?P<done>\d+)/(?P<total>\d+) layers to GPU")
_DEFAULT_TOTAL_LAYERS = 37  # Qwen3-4B: 36 transformer layers + output layer


@dataclass(frozen=True)
class BufferTotals:
    """Buffers llama.cpp reported for one load, split by device class."""

    vram_model_mb: float = 0.0
    vram_kv_mb: float = 0.0
    vram_compute_mb: float = 0.0
    ram_model_mb: float = 0.0
    ram_kv_mb: float = 0.0
    ram_compute_mb: float = 0.0

    @property
    def vram_total_mb(self) -> float:
        return self.vram_model_mb + self.vram_kv_mb + self.vram_compute_mb

    @property
    def ram_total_mb(self) -> float:
        return self.ram_model_mb + self.ram_kv_mb + self.ram_compute_mb


def parse_buffers(lines: list[str]) -> BufferTotals:
    """Sum ``... buffer size = N MiB`` lines into VRAM and RAM totals.

    Device names are ``Vulkan0`` / ``Vulkan_Host`` / ``CPU`` / ``CPU_Mapped``:
    ``Vulkan_Host`` and the ``CPU`` devices are host memory, everything else is VRAM.
    """

    vram = {"model": 0.0, "KV": 0.0, "compute": 0.0}
    ram = {"model": 0.0, "KV": 0.0, "compute": 0.0}
    for line in lines:
        match = _BUFFER_RE.search(line or "")
        if not match:
            continue
        kind = match.group("kind")
        if kind == "output":
            continue
        device = match.group("device").upper()
        target = ram if device.startswith(("CPU", "VULKAN_HOST")) else vram
        target[kind] += float(match.group("mib"))
    return BufferTotals(
        vram_model_mb=vram["model"],
        vram_kv_mb=vram["KV"],
        vram_compute_mb=vram["compute"],
        ram_model_mb=ram["model"],
        ram_kv_mb=ram["KV"],
        ram_compute_mb=ram["compute"],
    )


def parse_offloaded_layers(lines: list[str]) -> tuple[int, int]:
    for line in lines:
        match = _OFFLOAD_RE.search(line or "")
        if match:
            return int(match.group("done")), int(match.group("total"))
    return 0, _DEFAULT_TOTAL_LAYERS


@dataclass
class LoadOutcome:
    backend: str
    load_seconds: float
    model: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    identity: dict[str, Any] = field(default_factory=dict)
    buffers: BufferTotals = field(default_factory=BufferTotals)
    memory: MemoryBudget | None = None
    fallback_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "loaded": True,
            "backend": self.backend,
            "load_seconds": round(self.load_seconds, 3),
            "model": self.model,
            "context": self.context,
            "memory": self.memory.as_dict() if self.memory else None,
            "fallback_reason": self.fallback_reason,
            "warnings": self.warnings,
            "attempts": self.attempts,
        }


class SingleFlight:
    """One active holder, a bounded waiting queue, and honest depth counters."""

    def __init__(self, max_queue: int, wait_seconds: float) -> None:
        self._condition = threading.Condition()
        self._active = False
        self._queue = deque[float]()
        self._max_queue = max(0, int(max_queue))
        self._wait_seconds = max(0.0, float(wait_seconds))
        self._served = 0

    @property
    def stats(self) -> dict[str, int]:
        with self._condition:
            return {
                "active": 1 if self._active else 0,
                "queued": len(self._queue),
                "max_queue": self._max_queue,
                "served": self._served,
            }

    def acquire(self) -> None:
        with self._condition:
            if not self._active:
                self._active = True
                self._served += 1
                return
            if len(self._queue) >= self._max_queue:
                raise KieBusyError(
                    "KIE is busy with another request and the queue is full.",
                    queue_depth=len(self._queue),
                    max_queue=self._max_queue,
                )
            ticket = time.monotonic() + self._wait_seconds
            self._queue.append(ticket)
            try:
                while self._active:
                    remaining = ticket - time.monotonic()
                    if remaining <= 0:
                        raise KieBusyError(
                            "Timed out waiting for the KIE inference slot.",
                            queue_depth=len(self._queue),
                            max_queue=self._max_queue,
                        )
                    self._condition.wait(timeout=min(remaining, 0.5))
                self._active = True
            finally:
                if ticket in self._queue:
                    self._queue.remove(ticket)
            self._served += 1

    def release(self) -> None:
        with self._condition:
            self._active = False
            self._condition.notify_all()


class ModelManager:
    """Loads, unloads and serialises access to the embedded model."""

    def __init__(
        self,
        config: KieConfig,
        *,
        engine_factory: Callable[[str, KieConfig, int], EnginePort] | None = None,
        manifest: KieManifest | None = None,
    ) -> None:
        self.config = config
        self._engine_factory = engine_factory or self._default_engine
        self._manifest = manifest

        self._lock = threading.RLock()
        self._load_condition = threading.Condition(self._lock)
        self._slot = SingleFlight(config.queue_max, config.queue_wait_seconds)

        self._engine: EnginePort | None = None
        self._state = ModelState.DISABLED if not config.enabled else ModelState.UNLOADED
        self._backend: str | None = None
        self._outcome: LoadOutcome | None = None
        self._last_error: str | None = None
        self._fallback_reason: str | None = None
        self._loading_since: float | None = None

    # ---------------------------------------------------------------- lifecycle
    @property
    def state(self) -> ModelState:
        with self._lock:
            return self._state

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._state is ModelState.READY and self._engine is not None

    @property
    def backend(self) -> str | None:
        with self._lock:
            return self._backend

    @property
    def backend_identity(self) -> dict[str, Any]:
        with self._lock:
            engine = self._engine
        if engine is None:
            return {}
        return dict(engine.backend_identity() or {})

    def _candidates(self) -> list[str]:
        return list(self.config.backends)

    def _default_engine(self, backend: str, config: KieConfig, n_gpu_layers: int) -> EnginePort:
        from app.kie.runtime.llama import LlamaRuntime

        manifest = self._manifest or load_manifest()
        model_path = resolve_model(manifest)
        variant = manifest.runtime(backend)
        return LlamaRuntime(
            model_path=model_path,
            runtime_dir=variant.path,
            n_gpu_layers=n_gpu_layers,
            n_ctx=config.n_ctx,
            n_batch=config.n_batch,
        )

    def load(self) -> LoadOutcome:
        """Load the model, trying each configured backend and enforcing the budget."""

        with self._lock:
            if not self.config.enabled:
                from app.kie.errors import KieDisabledError

                raise KieDisabledError()
            if self._state is ModelState.READY and self._outcome is not None:
                return self._outcome
            if self._state is ModelState.LOADING:
                deadline = time.monotonic() + self.config.load_timeout_seconds
                while self._state is ModelState.LOADING:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ModelLoadingError("The model load is taking longer than expected.", remaining)
                    self._load_condition.wait(timeout=min(remaining, 0.5))
                if self._state is ModelState.READY and self._outcome is not None:
                    return self._outcome
                raise ModelLoadingError("A concurrent model load failed; see /api/v1/kie/status.")
            self._state = ModelState.LOADING
            self._loading_since = time.monotonic()
            self._last_error = None
            self._fallback_reason = None

        outcome: LoadOutcome | None = None
        error: Exception | None = None
        attempts: list[dict[str, Any]] = []
        try:
            for backend in self._candidates():
                try:
                    outcome = self._load_backend(backend, attempts)
                    break
                except Exception as exc:  # noqa: BLE001 - every backend failure is a fallback reason
                    logger.warning("KIE %s backend failed: %s", backend, exc)
                    attempts.append({"backend": backend, "error": str(exc)})
                    error = exc
        finally:
            with self._lock:
                if outcome is not None:
                    self._state = ModelState.READY
                    self._outcome = outcome
                    self._last_error = None
                else:
                    self._state = ModelState.ERROR
                    self._last_error = str(error) if error else "no backend could load the model"
                self._loading_since = None
                self._load_condition.notify_all()

        if outcome is None:
            raise ModelLoadFailedError(
                "KIE could not load the model on any configured backend.",
                {"attempts": attempts, "backends": self._candidates()},
            )
        outcome.attempts = attempts
        return outcome

    def _load_backend(self, backend: str, attempts: list[dict[str, Any]]) -> LoadOutcome:
        gpu_layers = 0 if backend == "cpu" else self.config.n_gpu_layers
        engine = self._engine_factory(backend, self.config, gpu_layers)
        started = time.perf_counter()
        report = engine.load()
        load_seconds = time.perf_counter() - started

        lines = list(getattr(report, "backend_log", []) or [])
        buffers = parse_buffers(lines)
        offloaded, total_layers = parse_offloaded_layers(lines)
        identity = dict(engine.backend_identity() or {})
        backend_report = dict(getattr(report, "backend", {}) or {})
        if backend != "cpu" and not backend_report.get("gpu_device_present", False):
            engine.unload()
            raise ModelLoadFailedError(
                f"The {backend} runtime loaded without a GPU device; refusing to call this GPU inference.",
                {"backend": backend},
            )

        budget_mb = self.config.vram_budget_mb if backend != "cpu" else self.config.ram_budget_mb
        measured_mb = buffers.vram_total_mb if backend != "cpu" else buffers.ram_total_mb

        if measured_mb > budget_mb and backend != "cpu" and offloaded > 0:
            # Fit the budget by offloading fewer layers, using the measured per-layer cost
            # instead of a guess. Anything beyond that is a real budget failure.
            per_layer = buffers.vram_model_mb / max(offloaded, 1)
            fixed = buffers.vram_kv_mb + buffers.vram_compute_mb
            allowed = int(max(0.0, budget_mb - fixed) // max(per_layer, 1e-6))
            attempts.append(
                {
                    "backend": backend,
                    "stage": "budget",
                    "measured_mb": round(measured_mb, 1),
                    "budget_mb": budget_mb,
                    "per_layer_mb": round(per_layer, 2),
                    "retry_layers": allowed,
                }
            )
            engine.unload()
            if allowed <= 0:
                raise KieMemoryBudgetError(
                    "The KV cache and compute buffers alone exceed the VRAM budget; "
                    "reduce KBMTI_KIE_CTX or raise KBMTI_KIE_VRAM_BUDGET_MB.",
                    {"measured_mb": round(measured_mb, 1), "budget_mb": budget_mb},
                )
            engine = self._engine_factory(backend, self.config, allowed)
            started = time.perf_counter()
            report = engine.load()
            load_seconds = time.perf_counter() - started
            lines = list(getattr(report, "backend_log", []) or [])
            buffers = parse_buffers(lines)
            offloaded, total_layers = parse_offloaded_layers(lines)
            identity = dict(engine.backend_identity() or {})
            backend_report = dict(getattr(report, "backend", {}) or {})
            measured_mb = buffers.vram_total_mb
            if measured_mb > budget_mb:
                engine.unload()
                raise KieMemoryBudgetError(
                    "The model does not fit the configured VRAM budget even with fewer GPU layers.",
                    {
                        "measured_mb": round(measured_mb, 1),
                        "budget_mb": budget_mb,
                        "offloaded_layers": offloaded,
                    },
                )

        if backend == "cpu" and measured_mb > budget_mb:
            engine.unload()
            raise KieMemoryBudgetError(
                "The CPU fallback does not fit the configured RAM budget.",
                {"measured_mb": round(measured_mb, 1), "budget_mb": budget_mb},
            )

        memory = MemoryBudget(
            budget_mb=budget_mb,
            measured_mb=measured_mb,
            model_mb=buffers.vram_model_mb if backend != "cpu" else buffers.ram_model_mb,
            kv_mb=buffers.vram_kv_mb if backend != "cpu" else buffers.ram_kv_mb,
            compute_mb=buffers.vram_compute_mb if backend != "cpu" else buffers.ram_compute_mb,
            offloaded_layers=offloaded,
            total_layers=total_layers or _DEFAULT_TOTAL_LAYERS,
            within_budget=measured_mb <= budget_mb,
            residual_mb=self.config.vulkan_residual_mb if backend != "cpu" else 0.0,
        )

        first_failure = next((entry for entry in attempts if entry.get("error")), None)
        fallback_reason = (
            f"{first_failure['backend']} unavailable: {first_failure['error']}" if first_failure else None
        )
        with self._lock:
            self._engine = engine
            self._backend = backend
            self._fallback_reason = fallback_reason

        return LoadOutcome(
            backend=backend,
            load_seconds=load_seconds,
            model=dict(getattr(report, "model", {}) or {}),
            context=dict(getattr(report, "context", {}) or {}),
            identity=identity,
            buffers=buffers,
            memory=memory,
            fallback_reason=self._fallback_reason,
            warnings=list(getattr(report, "warnings", []) or []),
        )

    def unload(self) -> None:
        with self._lock:
            engine = self._engine
            if engine is None:
                self._engine = None
                self._backend = None
                self._outcome = None
                if self.config.enabled:
                    self._state = ModelState.UNLOADED
                return
            self._state = ModelState.UNLOADING
        try:
            engine.unload()
        except Exception as exc:  # noqa: BLE001 - report but never leave the manager stuck
            logger.warning("KIE unload failed: %s", exc)
            with self._lock:
                self._last_error = str(exc)
        finally:
            with self._lock:
                self._engine = None
                self._outcome = None
                self._backend = None
                self._state = ModelState.UNLOADED if self.config.enabled else ModelState.DISABLED

    def shutdown(self) -> None:
        with self._lock:
            engine = self._engine
        if engine is not None:
            try:
                engine.shutdown()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.warning("KIE engine shutdown failed: %s", exc)
        with self._lock:
            self._engine = None
            self._outcome = None
            self._backend = None
            self._state = ModelState.DISABLED if not self.config.enabled else ModelState.UNLOADED

    # ---------------------------------------------------------------- inference
    @property
    def queue(self) -> dict[str, int]:
        return self._slot.stats

    def generate(self, **kwargs: Any) -> Any:
        """Run one generation in the single-flight slot.

        Raises ``ModelNotLoadedError`` when the model is not ready and ``KieBusyError``
        when the slot and the bounded queue are both full.
        """

        with self._lock:
            engine = self._engine
            state = self._state
        if engine is None or state is not ModelState.READY:
            raise ModelNotLoadedError()
        self._slot.acquire()
        try:
            with self._lock:
                if self._engine is not engine or self._state is not ModelState.READY:
                    raise ModelNotLoadedError("The model was unloaded while this request was queued.")
            return engine.generate(**kwargs)
        finally:
            self._slot.release()

    def count_tokens(self, text: str) -> int | None:
        with self._lock:
            engine = self._engine
        if engine is None:
            return None
        try:
            return int(engine.count_tokens(text))
        except Exception:  # noqa: BLE001 - token accounting is advisory
            return None

    # ---------------------------------------------------------------- reporting
    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
            backend = self._backend
            outcome = self._outcome
            last_error = self._last_error
            fallback = self._fallback_reason
            loading_since = self._loading_since
        identity: dict[str, Any] = {}
        if outcome is not None:
            identity = {
                "runtime_tag": outcome.identity.get("runtime_tag"),
                "llama_version": outcome.identity.get("llama_version"),
                "devices": outcome.identity.get("vulkan_devices") or [],
                "gpu_offload": bool((outcome.identity.get("backend_load") or {}).get("gpu_offload")),
            }
        return {
            "enabled": self.config.enabled,
            "state": str(state),
            "ready": state is ModelState.READY,
            "backend": backend,
            "accelerated": bool(backend and backend != "cpu"),
            "identity": identity,
            "model": (outcome.model if outcome else None),
            "context": (outcome.context if outcome else None),
            "memory": outcome.memory.as_dict() if outcome and outcome.memory else None,
            "fallback_reason": fallback,
            "last_error": last_error,
            "load_seconds": round(outcome.load_seconds, 3) if outcome else None,
            "loading_seconds": round(time.monotonic() - loading_since, 1) if loading_since else None,
            "queue": self.queue,
            "config": self.config.as_dict(),
        }
