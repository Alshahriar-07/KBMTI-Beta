"""Prevent two launchers from owning two backend/Qwen instances on one desktop."""

from __future__ import annotations

import os

_MUTEX_NAME = "Local\\KBMTI-Desktop-Single-Instance-v1"
_handle: object | None = None


def acquire() -> bool:
    """Return False when another KBMTI launcher already holds the desktop mutex.

    The handle is deliberately kept alive for the process lifetime. Windows releases
    it automatically on exit, including an abnormal exit, so no stale PID file or
    manually cleaned lock is involved.
    """

    global _handle
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            return True  # A missing mutex must not block an otherwise valid launch.
        already_exists = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        if already_exists:
            kernel32.CloseHandle(handle)
            return False
        _handle = handle
        return True
    except (AttributeError, OSError):
        return True


def release() -> None:
    global _handle
    if _handle is None or os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(_handle)
    except (AttributeError, OSError):
        pass
    _handle = None


def describe_conflict() -> str:
    return (
        "KBMTI is already running on this desktop. Close the existing KBMTI window "
        "before starting another instance; the launcher allows only one backend and "
        "one Qwen model per machine."
    )


__all__ = ["acquire", "release", "describe_conflict"]
