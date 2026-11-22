"""KIE configuration.

Defaults are chosen from the Phase A measurements on the target workstation
(i5-9400F, RX 580 2048SP 8 GB, 16 GB RAM) and can be overridden with ``KBMTI_KIE_*``
environment variables. Nothing here loads a model or touches the GPU.

Context size is 4096 by default on purpose: Phase A measured 3 853 MiB of Vulkan
buffers at 8192 context and 3.0 s / 12.4 s of prefill for 525 / 2 064 tokens. Doubling
the context is a measured decision, not a knob to turn casually.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.kie.runtime.manifest import MODELS_ROOT

BACKEND_DIR = Path(__file__).resolve().parents[2]

DEFAULT_N_CTX = 4096
DEFAULT_N_BATCH = 512
DEFAULT_VRAM_BUDGET_MB = 4096
DEFAULT_RAM_BUDGET_MB = 11_000
# Phase A: RSS after unload stayed ~376 MB above baseline because the Vulkan loader and
# driver bookkeeping are not released. The budget must carry that for the whole session.
DEFAULT_VULKAN_RESIDUAL_MB = 376.0

# GPU-first by default. The CPU runtime is opt-in only (``KBMTI_KIE_BACKEND=cpu``):
# silently answering on CPU after a Vulkan failure would misrepresent acceleration.
BACKEND_ORDER = ("vulkan",)


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if not value or not value.strip():
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class KieConfig:
    """Resolved KIE settings (immutable; build once per process)."""

    enabled: bool = True
    # Qwen is warmed in the background on normal application startup. Set
    # KBMTI_KIE_AUTOLOAD=false to skip eager startup; the assistant still
    # initializes it when Qwen is first requested.
    autoload: bool = True
    backend_preference: str = "auto"  # "auto" | "vulkan" | "cpu"
    models_root: Path = field(default_factory=lambda: MODELS_ROOT)
    n_ctx: int = DEFAULT_N_CTX
    n_batch: int = DEFAULT_N_BATCH
    n_gpu_layers: int = 99
    vram_budget_mb: int = DEFAULT_VRAM_BUDGET_MB
    ram_budget_mb: int = DEFAULT_RAM_BUDGET_MB
    vulkan_residual_mb: float = DEFAULT_VULKAN_RESIDUAL_MB
    queue_max: int = 3
    queue_wait_seconds: float = 30.0
    generation_timeout_seconds: float = 120.0
    load_timeout_seconds: float = 120.0
    default_max_tokens: int = 512
    hard_max_tokens: int = 1024
    default_temperature: float = 0.3
    default_top_p: float = 0.9
    history_limit: int = 8
    # Phase B ships the KIE chat responder dark: /chat stays rule-based unless this is on.
    chat_responder: bool = False

    @property
    def backends(self) -> tuple[str, ...]:
        preference = (self.backend_preference or "auto").strip().lower()
        if preference == "cpu":
            return ("cpu",)
        if preference == "vulkan":
            return ("vulkan",)
        # An unknown preference must not silently widen to CPU. GPU-first remains the
        # default; a CPU run requires the explicit ``cpu`` preference above.
        return BACKEND_ORDER

    def effective_max_tokens(self, requested: int | None) -> int:
        if requested is None:
            return min(self.default_max_tokens, self.hard_max_tokens)
        return max(1, min(int(requested), self.hard_max_tokens))

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "autoload": self.autoload,
            "backend_preference": self.backend_preference,
            "backends": list(self.backends),
            "n_ctx": self.n_ctx,
            "n_batch": self.n_batch,
            "n_gpu_layers": self.n_gpu_layers,
            "vram_budget_mb": self.vram_budget_mb,
            "ram_budget_mb": self.ram_budget_mb,
            "vulkan_residual_mb": self.vulkan_residual_mb,
            "queue_max": self.queue_max,
            "queue_wait_seconds": self.queue_wait_seconds,
            "generation_timeout_seconds": self.generation_timeout_seconds,
            "default_max_tokens": self.default_max_tokens,
            "hard_max_tokens": self.hard_max_tokens,
            "default_temperature": self.default_temperature,
            "default_top_p": self.default_top_p,
            "chat_responder": self.chat_responder,
        }


def load_config() -> KieConfig:
    """Read the configuration once from the environment."""

    return KieConfig(
        enabled=_env_bool("KBMTI_KIE_ENABLED", True),
        # The application starts Qwen in the background by default. Without this, a
        # normal launch never calls /kie/load and the assistant reports UNAVAILABLE even
        # though the model and Vulkan runtime are installed.
        autoload=_env_bool("KBMTI_KIE_AUTOLOAD", True),
        backend_preference=_env_str("KBMTI_KIE_BACKEND", "auto").lower(),
        models_root=Path(_env_str("KBMTI_KIE_MODELS_ROOT", str(MODELS_ROOT))),
        n_ctx=max(1024, _env_int("KBMTI_KIE_CTX", DEFAULT_N_CTX)),
        n_batch=max(64, _env_int("KBMTI_KIE_BATCH", DEFAULT_N_BATCH)),
        n_gpu_layers=_env_int("KBMTI_KIE_GPU_LAYERS", 99),
        vram_budget_mb=max(512, _env_int("KBMTI_KIE_VRAM_BUDGET_MB", DEFAULT_VRAM_BUDGET_MB)),
        ram_budget_mb=max(1024, _env_int("KBMTI_KIE_RAM_BUDGET_MB", DEFAULT_RAM_BUDGET_MB)),
        vulkan_residual_mb=max(0.0, _env_float("KBMTI_KIE_RESIDUAL_MB", DEFAULT_VULKAN_RESIDUAL_MB)),
        queue_max=max(0, _env_int("KBMTI_KIE_QUEUE_MAX", 3)),
        queue_wait_seconds=max(0.0, _env_float("KBMTI_KIE_QUEUE_WAIT_S", 30.0)),
        generation_timeout_seconds=max(5.0, _env_float("KBMTI_KIE_TIMEOUT_S", 120.0)),
        load_timeout_seconds=max(10.0, _env_float("KBMTI_KIE_LOAD_TIMEOUT_S", 120.0)),
        default_max_tokens=max(16, _env_int("KBMTI_KIE_MAX_TOKENS", 512)),
        hard_max_tokens=max(16, _env_int("KBMTI_KIE_HARD_MAX_TOKENS", 1024)),
        default_temperature=_env_float("KBMTI_KIE_TEMPERATURE", 0.3),
        default_top_p=_env_float("KBMTI_KIE_TOP_P", 0.9),
        history_limit=max(0, _env_int("KBMTI_KIE_HISTORY", 8)),
        chat_responder=_env_bool("KBMTI_KIE_CHAT_RESPONDER", False),
    )
