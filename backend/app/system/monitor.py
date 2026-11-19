"""Local system telemetry.

Only values that can actually be read are reported. Unsupported metrics are
returned as unavailable with a short explanation - never estimated or invented.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any

import psutil

GPU_CACHE_SECONDS = 60.0


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SystemMonitor:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._gpu_cache: dict[str, Any] | None = None
        self._gpu_cache_at = 0.0
        # Prime psutil so the first reported CPU sample is meaningful.
        try:
            psutil.cpu_percent(interval=None)
        except Exception:  # pragma: no cover
            pass

    def cpu(self) -> dict[str, Any]:
        try:
            percent = psutil.cpu_percent(interval=None)
            frequency = psutil.cpu_freq()
            return {
                "percent": round(float(percent), 1),
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "frequency_mhz": round(float(frequency.current), 0) if frequency else None,
            }
        except Exception:  # pragma: no cover
            return {"percent": None, "physical_cores": None, "logical_cores": None, "frequency_mhz": None}

    def memory(self) -> dict[str, Any]:
        try:
            info = psutil.virtual_memory()
            return {
                "total_bytes": int(info.total),
                "used_bytes": int(info.total - info.available),
                "available_bytes": int(info.available),
                "percent": round(float(info.percent), 1),
            }
        except Exception:  # pragma: no cover
            return {"total_bytes": None, "used_bytes": None, "available_bytes": None, "percent": None}

    def _run_cim_query(self) -> list[dict[str, Any]]:
        if sys.platform != "win32":
            return []
        command = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=4.0, check=False)
        except (OSError, subprocess.SubprocessError):
            return []
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        try:
            import json

            payload = json.loads(completed.stdout)
        except ValueError:
            return []
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def _nvidia_smi(self) -> dict[str, Any] | None:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return None
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=4.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        first = completed.stdout.strip().splitlines()[0]
        parts = [part.strip() for part in first.split(",")]
        if len(parts) < 4:
            return None
        try:
            return {
                "available": True,
                "name": parts[0],
                "utilization_percent": float(parts[1]),
                "memory_used_mb": float(parts[2]),
                "memory_total_mb": float(parts[3]),
                "note": "Telemetry read from nvidia-smi.",
            }
        except ValueError:
            return None

    def gpu(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            if self._gpu_cache is not None and now - self._gpu_cache_at < GPU_CACHE_SECONDS:
                return self._gpu_cache

            result: dict[str, Any]
            nvidia = self._nvidia_smi()
            if nvidia:
                result = nvidia
            else:
                controllers = self._run_cim_query()
                names = [str(item.get("Name") or "").strip() for item in controllers if item.get("Name")]
                if names:
                    primary = names[0]
                    result = {
                        "available": True,
                        "name": primary,
                        "utilization_percent": None,
                        "memory_used_mb": None,
                        "memory_total_mb": None,
                        "note": (
                            "GPU name detected via Windows WMI. Utilization and memory telemetry are not exposed "
                            "by this driver/vendor combination."
                        ),
                    }
                else:
                    result = {
                        "available": False,
                        "name": None,
                        "utilization_percent": None,
                        "memory_used_mb": None,
                        "memory_total_mb": None,
                        "note": "No reliable GPU telemetry source was detected.",
                    }
            self._gpu_cache = result
            self._gpu_cache_at = now
            return result

    def temperature(self) -> dict[str, Any]:
        try:
            sensors = psutil.sensors_temperatures()  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            sensors = None
        if sensors:
            for entries in sensors.values():
                for entry in entries:
                    if entry.current:
                        return {
                            "available": True,
                            "celsius": round(float(entry.current), 1),
                            "note": f"Sensor: {entry.label or 'unnamed'}.",
                        }
        return {
            "available": False,
            "celsius": None,
            "note": (
                "No reliable temperature sensor is exposed to applications on this system. "
                "KBMTI does not estimate temperatures."
            ),
        }

    def platform_info(self) -> dict[str, Any]:
        try:
            boot_time = psutil.boot_time()
        except Exception:  # pragma: no cover
            boot_time = None
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "boot_time": datetime.fromtimestamp(boot_time, tz=UTC).isoformat(timespec="seconds") if boot_time else None,
        }

    def status(
        self,
        backend: dict[str, Any],
        mt5: dict[str, Any],
        market: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "cpu": self.cpu(),
            "memory": self.memory(),
            "gpu": self.gpu(),
            "temperature": self.temperature(),
            "backend": backend,
            "market": market or {},
            "mt5": mt5,
            "platform": self.platform_info(),
            "sampled_at": _iso_now(),
        }
