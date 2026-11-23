"""Windows OpenMP coexistence for the in-process PATRON + Qwen runtime.

PyTorch (PATRON) ships Intel's ``libiomp5md.dll``. The pinned llama.cpp Vulkan
build ships LLVM's ``libomp.dll``. Both are OpenMP runtimes, and LLVM's runtime
aborts the process with ``OMP: Error #15`` when it discovers Intel's runtime
already initialized in the same process. That happens while Qwen loads, *after*
PATRON has loaded, so there is no Python exception to catch: the interpreter
disappears and an HTTP proxy reports 502.

This module is the narrow compatibility boundary. It is only active on Windows
and only sets the documented runtime guard before either OpenMP runtime is
initialized. It does not change the inference backend, model, offload, queue or
any trading/strategy behaviour.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

OPENMP_COMPAT_ENV = "KMP_DUPLICATE_LIB_OK"
OPENMP_COMPAT_VALUE = "TRUE"


def configure_windows_openmp_compat(*, platform_name: str | None = None) -> bool:
    """Allow PyTorch and llama.cpp OpenMP runtimes to coexist on Windows.

    Returns ``True`` when this call set the guard, ``False`` when the process is
    not Windows or the operator already configured the variable. The variable is
    process-wide, so it must be set before the second OpenMP runtime initializes.
    """

    if (platform_name or os.name) != "nt":
        return False
    existing = os.environ.get(OPENMP_COMPAT_ENV)
    if existing and existing.strip().upper() in {"1", "TRUE", "YES", "ON"}:
        return False
    os.environ[OPENMP_COMPAT_ENV] = OPENMP_COMPAT_VALUE
    logger.warning(
        "Windows OpenMP compatibility mode enabled (%s=%s): PyTorch libiomp5md.dll "
        "and llama.cpp libomp.dll share one process. This does not change the "
        "inference backend or enable CPU fallback.",
        OPENMP_COMPAT_ENV,
        OPENMP_COMPAT_VALUE,
    )
    return True


def windows_openmp_compat_enabled() -> bool:
    value = os.environ.get(OPENMP_COMPAT_ENV, "")
    return os.name == "nt" and value.strip().upper() in {"1", "TRUE", "YES", "ON"}


__all__ = [
    "OPENMP_COMPAT_ENV",
    "configure_windows_openmp_compat",
    "windows_openmp_compat_enabled",
]
