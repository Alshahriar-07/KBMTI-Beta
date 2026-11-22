"""Test doubles for the KIE engine and its load reports.

These fakes implement the same surface as ``LlamaRuntime`` (``load``/``unload``/
``generate``/``backend_identity``) without touching a DLL, so the lifecycle, budget,
queueing and cancellation logic can be tested deterministically on any machine.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeLoadReport:
    model: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    backend: dict[str, Any] = field(default_factory=dict)
    backend_log: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class FakeGeneration:
    text: str
    prompt_tokens: int
    generated_tokens: int
    ttft_ms: float
    prompt_ms: float
    decode_ms: float
    total_ms: float
    prompt_tok_per_s: float
    decode_tok_per_s: float
    finish: str
    cancelled: bool
    prompt_truncated_tokens: int = 0


def buffer_lines(
    *,
    layers: int,
    total_layers: int = 37,
    model_mb_per_layer: float = 64.86,
    kv_mb: float = 576.0,
    compute_mb: float = 325.0,
    backend: str = "vulkan",
) -> list[str]:
    if backend == "cpu":
        return [
            "load_tensors: offloaded 0/37 layers to GPU",
            f"load_tensors:   CPU_Mapped model buffer size =  {model_mb_per_layer * total_layers:.2f} MiB",
            f"llama_kv_cache:        CPU KV buffer size =  {kv_mb:.2f} MiB",
            f"sched_reserve:        CPU compute buffer size =  {compute_mb:.2f} MiB",
        ]
    return [
        f"load_tensors: offloaded {layers}/{total_layers} layers to GPU",
        f"load_tensors:      Vulkan0 model buffer size =  {model_mb_per_layer * layers:.2f} MiB",
        "load_tensors:   CPU_Mapped model buffer size =   304.28 MiB",
        f"llama_kv_cache:    Vulkan0 KV buffer size =  {kv_mb:.2f} MiB",
        f"sched_reserve:    Vulkan0 compute buffer size =  {compute_mb:.2f} MiB",
        "sched_reserve: Vulkan_Host compute buffer size =    28.02 MiB",
    ]


class FakeEngine:
    """Engine double with controllable failures, buffers, text and blocking."""

    def __init__(
        self,
        backend: str = "vulkan",
        layers: int = 99,
        *,
        fail_on_load: bool = False,
        fail_on_generate: bool = False,
        gpu_present: bool = True,
        model_mb_per_layer: float = 64.86,
        kv_mb: float = 576.0,
        compute_mb: float = 325.0,
        text: str = "Hello from the fake engine.",
        chunk_delay: float = 0.0,
        gate: threading.Event | None = None,
        prompt_tokens: int = 12,
    ) -> None:
        self.backend = backend
        self.layers = layers
        self.fail_on_load = fail_on_load
        self.fail_on_generate = fail_on_generate
        self.gpu_present = gpu_present
        self.model_mb_per_layer = model_mb_per_layer
        self.kv_mb = kv_mb
        self.compute_mb = compute_mb
        self.text = text
        self.chunk_delay = chunk_delay
        self.gate = gate
        self.prompt_tokens = prompt_tokens
        self._loaded = False
        self.load_calls = 0
        self.unload_calls = 0
        self.entered = 0
        self.max_concurrent = 0
        self._concurrency_lock = threading.Lock()
        self.generated_tokens: list[int] = []

    # -- lifecycle ------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> FakeLoadReport:
        self.load_calls += 1
        if self.fail_on_load:
            raise RuntimeError(f"{self.backend} runtime could not initialise")
        self._loaded = True
        layers = 0 if self.backend == "cpu" else (37 if self.layers >= 37 else self.layers)
        return FakeLoadReport(
            model={
                "description": "fake-qwen3-4b",
                "n_layer": 36,
                "n_ctx_train": 40960,
                "size_bytes": 2_491_323_904,
                "quantization": "15",
                "architecture": "qwen3",
            },
            context={"n_ctx": 4096, "n_batch": 512, "n_threads": 5},
            backend={
                "status": 0,
                "device_count": 2 if self.backend != "cpu" else 1,
                "gpu_offload": self.backend != "cpu" and self.gpu_present,
                "gpu_device_present": self.backend != "cpu" and self.gpu_present,
            },
            backend_log=buffer_lines(
                layers=layers,
                model_mb_per_layer=self.model_mb_per_layer,
                kv_mb=self.kv_mb,
                compute_mb=self.compute_mb,
                backend=self.backend,
            ),
        )

    def unload(self) -> None:
        self.unload_calls += 1
        self._loaded = False

    def shutdown(self) -> None:
        self._loaded = False

    def backend_identity(self) -> dict[str, Any]:
        return {
            "runtime_tag": "b12503",
            "llama_version": "1.0.0-dev",
            "supports_gpu_offload": self.backend != "cpu",
            "backend_load": {"gpu_offload": self.backend != "cpu" and self.gpu_present},
            "vulkan_devices": ["fake-vulkan-0"] if self.backend != "cpu" and self.gpu_present else [],
        }

    # -- inference ------------------------------------------------------
    def generate(self, messages=None, *, prompt=None, max_tokens=128, temperature=0.7, top_p=0.8,
                 thinking=False, cancel_event=None, on_token=None) -> FakeGeneration:
        with self._concurrency_lock:
            self.entered += 1
            self.max_concurrent = max(self.max_concurrent, self.entered)
        try:
            if self.fail_on_generate:
                raise RuntimeError("fake inference failure")
            if self.gate is not None:
                self.gate.wait(timeout=5.0)
            started = time.perf_counter()
            chunks = _chunks(self.text)
            generated = 0
            finish = "length"
            cancelled = False
            first_at = None
            for chunk in chunks:
                if generated >= max_tokens:
                    break
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    finish = "cancelled"
                    break
                if on_token is not None:
                    on_token(chunk)
                if first_at is None:
                    first_at = time.perf_counter()
                generated += 1
                if self.chunk_delay:
                    time.sleep(self.chunk_delay)
            else:
                finish = "eog"
            self.generated_tokens.append(generated)
            total_ms = (time.perf_counter() - started) * 1000.0
            ttft_ms = 25.0 if first_at is not None else total_ms
            decode_ms = max(total_ms - ttft_ms, 1.0)
            return FakeGeneration(
                text=self.text,
                prompt_tokens=self.prompt_tokens,
                generated_tokens=generated,
                ttft_ms=ttft_ms,
                prompt_ms=20.0,
                decode_ms=decode_ms,
                total_ms=total_ms,
                prompt_tok_per_s=self.prompt_tokens / 0.02,
                decode_tok_per_s=max(generated - 1, 1) / (decode_ms / 1000.0),
                finish=finish,
                cancelled=cancelled,
            )
        finally:
            with self._concurrency_lock:
                self.entered -= 1

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _chunks(text: str) -> list[str]:
    """Split text into small, deterministic pieces (keeps tag sequences intact)."""

    pieces: list[str] = []
    index = 0
    while index < len(text):
        size = 7 if index % 3 else 5
        pieces.append(text[index : index + size])
        index += size
    return pieces


class EngineFactory:
    """Build engines per backend and remember every instance for assertions."""

    def __init__(self, **engine_kwargs: Any) -> None:
        self.kwargs = engine_kwargs
        self.instances: list[FakeEngine] = []
        self.calls: list[tuple[str, int]] = []
        self.failures: dict[str, Exception] = {}

    def fail(self, backend: str, message: str = "boom") -> None:
        self.failures[backend] = RuntimeError(message)

    def __call__(self, backend: str, config, layers: int) -> FakeEngine:
        self.calls.append((backend, layers))
        if backend in self.failures:
            raise self.failures[backend]
        engine = FakeEngine(backend=backend, layers=layers, **self.kwargs)
        self.instances.append(engine)
        return engine
