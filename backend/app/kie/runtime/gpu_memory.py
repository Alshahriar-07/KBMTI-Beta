"""Windows GPU memory sampling through the Performance Data Helper (PDH) API.

Needed by the Phase A probe: "verify actual GPU layer offloading" and "measure VRAM before
and during inference" cannot be answered from task manager screenshots. PDH exposes the
same per-process counters Task Manager uses, without PowerShell, subprocesses or extra
packages:

    \\GPU Process Memory(<luid>_phys_<n>)\\Dedicated Usage

If the counters are unavailable (no WDDM 2.0 driver, PDH disabled, non-Windows) every
method returns ``None`` plus a reason, and the probe reports the limitation instead of
inventing a number.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import POINTER, Structure, byref, c_ulong, c_void_p, c_wchar_p
from dataclasses import dataclass

PDH_FMT_LARGE = 0x00000100
PDH_MORE_DATA = 0x800007D2
ERROR_SUCCESS = 0


class PDH_FMT_COUNTERVALUE(Structure):
    _fields_ = [("CStatus", c_ulong), ("largeValue", ctypes.c_longlong)]


class PDH_FMT_COUNTERVALUE_ITEM_W(Structure):
    _fields_ = [("szName", c_wchar_p), ("FmtValue", PDH_FMT_COUNTERVALUE)]


@dataclass
class GpuMemorySample:
    process_dedicated_bytes: int | None
    process_shared_bytes: int | None
    adapter_dedicated_bytes: int | None
    instances: dict[str, int]
    error: str | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "process_dedicated_mb": _mb(self.process_dedicated_bytes),
            "process_shared_mb": _mb(self.process_shared_bytes),
            "adapter_dedicated_mb": _mb(self.adapter_dedicated_bytes),
            "instances": {k: _mb(v) for k, v in self.instances.items()},
            "error": self.error,
            "note": self.note,
        }


def _mb(value: int | None) -> float | None:
    return None if value is None else round(value / (1024 * 1024), 1)


class GpuMemorySampler:
    """Reads the current process's dedicated VRAM (and adapter total) via PDH."""

    def __init__(self) -> None:
        self._pdh = None
        self._query = c_void_p()
        self._counters: dict[str, c_void_p] = {}
        self._error: str | None = None
        if os.name != "nt":
            self._error = "PDH GPU counters are Windows-only"
            return
        try:
            pdh = ctypes.WinDLL("pdh.dll")
        except OSError as exc:  # pragma: no cover - platform specific
            self._error = f"pdh.dll unavailable: {exc}"
            return
        pdh.PdhOpenQueryW.argtypes = [c_wchar_p, c_void_p, POINTER(c_void_p)]
        pdh.PdhOpenQueryW.restype = c_ulong
        pdh.PdhAddEnglishCounterW.argtypes = [c_void_p, c_wchar_p, c_void_p, POINTER(c_void_p)]
        pdh.PdhAddEnglishCounterW.restype = c_ulong
        pdh.PdhCollectQueryData.argtypes = [c_void_p]
        pdh.PdhCollectQueryData.restype = c_ulong
        # NOTE: the output pointer is typed ``void *`` on purpose. Declaring it as
        # POINTER(POINTER(PDH_FMT_COUNTERVALUE_ITEM_W)) makes ctypes reinterpret the
        # argument and crashes the interpreter on the second (fill) call.
        pdh.PdhGetFormattedCounterArrayW.argtypes = [
            c_void_p,
            c_ulong,
            POINTER(c_ulong),
            POINTER(c_ulong),
            c_void_p,
        ]
        pdh.PdhGetFormattedCounterArrayW.restype = c_ulong
        pdh.PdhRemoveCounter.argtypes = [c_void_p]
        pdh.PdhRemoveCounter.restype = c_ulong
        pdh.PdhCloseQuery.argtypes = [c_void_p]
        pdh.PdhCloseQuery.restype = c_ulong
        self._pdh = pdh

        status = pdh.PdhOpenQueryW(None, None, byref(self._query))
        if status != ERROR_SUCCESS:
            self._error = f"PdhOpenQuery failed (0x{status:08X})"
            self._pdh = None
            return
        for key, path in (
            ("process_dedicated", "\\GPU Process Memory(*)\\Dedicated Usage"),
            ("process_shared", "\\GPU Process Memory(*)\\Shared Usage"),
            ("adapter_dedicated", "\\GPU Adapter Memory(*)\\Dedicated Usage"),
        ):
            counter = c_void_p()
            status = pdh.PdhAddEnglishCounterW(self._query, path, None, byref(counter))
            if status == ERROR_SUCCESS:
                self._counters[key] = counter
            else:
                self._error = (self._error or "") + f"{key} unavailable (0x{status:08X}); "
        if not self._counters:
            self._error = self._error or "no GPU memory counters available"

    def _collect(self, counter: c_void_p) -> dict[str, int]:
        pdh = self._pdh
        assert pdh is not None
        status = pdh.PdhCollectQueryData(self._query)
        if status != ERROR_SUCCESS:
            return {}
        size = c_ulong(0)
        count = c_ulong(0)
        status = pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_LARGE, byref(size), byref(count), None)
        if status != PDH_MORE_DATA or size.value == 0:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        items = ctypes.cast(buf, POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
        status = pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_LARGE, byref(size), byref(count), ctypes.cast(buf, c_void_p)
        )
        if status != ERROR_SUCCESS:
            return {}
        out: dict[str, int] = {}
        for i in range(count.value):
            item = items[i]
            if item.szName:
                out[item.szName] = int(item.FmtValue.largeValue)
        return out

    def sample(self, pid: int | None = None) -> GpuMemorySample:
        pid = pid or os.getpid()
        if self._pdh is None:
            return GpuMemorySample(None, None, None, {}, self._error)
        dedicated = self._collect(self._counters["process_dedicated"]) if "process_dedicated" in self._counters else {}
        shared = self._collect(self._counters["process_shared"]) if "process_shared" in self._counters else {}
        adapter = (
            self._collect(self._counters["adapter_dedicated"]) if "adapter_dedicated" in self._counters else {}
        )
        marker = f"pid_{pid}_"
        mine = {k: v for k, v in dedicated.items() if marker in k}
        my_shared = {k: v for k, v in shared.items() if marker in k}
        total_dedicated = sum(mine.values()) if mine else None
        total_shared = sum(my_shared.values()) if my_shared else None
        adapter_total = sum(v for k, v in adapter.items() if "luid" in k) if adapter else None
        error = None
        note = None
        if total_dedicated is None:
            if adapter_total is not None:
                # The counter is healthy but Windows only publishes a per-process GPU
                # instance once the process has allocated VRAM: this process uses none.
                total_dedicated = 0
                total_shared = 0 if total_shared is None else total_shared
                note = "no GPU Process Memory instance for this pid; reported as 0 MB"
            else:
                error = "GPU memory counters unavailable (no adapter instances returned)"
        return GpuMemorySample(total_dedicated, total_shared, adapter_total, mine, error, note)

    def close(self) -> None:
        if self._pdh is None:
            return
        for counter in self._counters.values():
            self._pdh.PdhRemoveCounter(counter)
        self._pdh.PdhCloseQuery(self._query)
        self._pdh = None


if __name__ == "__main__":  # pragma: no cover - manual diagnostic
    sampler = GpuMemorySampler()
    print(sampler.sample().as_dict())
    if len(sys.argv) > 1 and sys.argv[1] == "--close":
        sampler.close()
