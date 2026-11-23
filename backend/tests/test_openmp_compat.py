"""Windows OpenMP coexistence guard for PATRON + Qwen in one process."""

from __future__ import annotations

import os

from app.kie.runtime.openmp_compat import (
    OPENMP_COMPAT_ENV,
    configure_windows_openmp_compat,
)


def test_windows_sets_the_duplicate_runtime_guard(monkeypatch) -> None:
    monkeypatch.delenv(OPENMP_COMPAT_ENV, raising=False)
    assert configure_windows_openmp_compat(platform_name="nt") is True
    assert os.environ[OPENMP_COMPAT_ENV] == "TRUE"


def test_non_windows_is_a_noop(monkeypatch) -> None:
    monkeypatch.delenv(OPENMP_COMPAT_ENV, raising=False)
    assert configure_windows_openmp_compat(platform_name="posix") is False
    assert OPENMP_COMPAT_ENV not in os.environ


def test_operator_value_is_preserved(monkeypatch) -> None:
    monkeypatch.setenv(OPENMP_COMPAT_ENV, "TRUE")
    assert configure_windows_openmp_compat(platform_name="nt") is False
    assert os.environ[OPENMP_COMPAT_ENV] == "TRUE"
