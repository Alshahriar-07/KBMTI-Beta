"""Lifecycle management for the backend and frontend child processes."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import (
    BACKEND_DIR,
    FRONTEND_DIR,
    LaunchConfig,
    LaunchError,
    backend_command,
    backend_environment,
    frontend_command,
    service_log_paths,
)

IS_WINDOWS = os.name == "nt"
CREATE_FLAGS = 0
if IS_WINDOWS:
    CREATE_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW


def tail_log(path: Path, lines: int = 40) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


@dataclass
class ManagedService:
    name: str
    command: list[str]
    cwd: Path
    env: dict[str, str]
    log_path: Path
    process: subprocess.Popen[bytes] | None = None
    _log_handle: object | None = None
    state: str = "NOT_STARTED"
    started_at: float | None = None
    last_health: str | None = None

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.state = "STARTING"
        self.started_at = time.time()
        self.last_health = None
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open("ab")
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=str(self.cwd),
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_FLAGS,
            )
        except OSError as exc:
            raise LaunchError(f"Could not start {self.name}: {exc}") from exc

    def snapshot(self) -> dict:
        """Stable diagnostics for the supervisor/error page (never credentials)."""

        return {
            "name": self.name,
            "pid": self.process.pid if self.process else None,
            "state": self.state,
            "started_at": self.started_at,
            "exit_code": self.exit_code(),
            "log_path": str(self.log_path),
            "last_health": self.last_health,
        }

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def exit_code(self) -> int | None:
        return self.process.poll() if self.process else None

    def stop(self, grace_seconds: float = 4.0) -> None:
        process = self.process
        if process is None:
            return
        self.state = "STOPPING"
        if process.poll() is None:
            # First ask the process group to close so the backend lifespan can
            # release the Qwen context and Vulkan allocations. Only force-kill if
            # it does not exit within the grace period.
            try:
                if IS_WINDOWS:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (OSError, ValueError):
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                if IS_WINDOWS:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except OSError:
                        process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        self.state = "STOPPED" if process.poll() is not None else "FAILED"
        if self._log_handle is not None:
            try:
                self._log_handle.close()  # type: ignore[union-attr]
            except OSError:
                pass
            self._log_handle = None

    def failure_detail(self) -> str:
        code = self.exit_code()
        message = f"{self.name} exited before it became ready"
        if code is not None:
            message += f" (exit code {code})"
        log = tail_log(self.log_path)
        return f"{message}\n\n--- {self.log_path} ---\n{log}" if log else message


@dataclass
class ServiceManager:
    config: LaunchConfig

    def __post_init__(self) -> None:
        backend_log, frontend_log = service_log_paths()
        env = backend_environment(self.config)
        frontend_env = dict(os.environ)
        frontend_env["BROWSER"] = "none"
        frontend_env["PYTHONUNBUFFERED"] = "1"
        frontend_env["VITE_BACKEND_ORIGIN"] = self.config.backend_url
        self.backend = ManagedService(
            name="FastAPI backend",
            command=backend_command(),
            cwd=BACKEND_DIR,
            env=env,
            log_path=backend_log,
        )
        self.frontend = ManagedService(
            name="Frontend dev server",
            command=frontend_command(self.config),
            cwd=FRONTEND_DIR,
            env=frontend_env,
            log_path=frontend_log,
        )

    def start(self) -> None:
        # A backend ticket is single-use. Renew it for every start, including
        # the user-visible Retry action, without retaining it on disk.
        from .licensing.gate import LaunchDenied, renew_backend_ticket

        try:
            renewed = renew_backend_ticket()
        except LaunchDenied as exc:
            raise LaunchError(exc.message) from exc
        if renewed:
            self.backend.env["KBMTI_APP_TOKEN"] = renewed
        self.backend.start()
        try:
            self.frontend.start()
        except Exception:
            self.backend.stop()
            raise

    def stop(self) -> None:
        # Ask the backend to release Qwen/Vulkan before ending the process group.
        # This is best-effort: a hung or already-dead backend must not block exit.
        if self.backend.running():
            try:
                _post_json(f"{self.config.backend_url}/api/v1/kie/unload", {}, timeout=8.0)
                self.backend.last_health = "Qwen unloaded"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
                pass
        self.frontend.stop()
        self.backend.stop()

    def services(self) -> tuple[ManagedService, ManagedService]:
        return self.backend, self.frontend

    def snapshot(self) -> list[dict]:
        return [service.snapshot() for service in self.services()]


def _get_json(url: str, timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8"))


def _post_json(url: str, payload: dict, timeout: float = 3.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_html(url: str, timeout: float = 3.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read(4096).decode("utf-8", errors="replace")


def backend_ready(config: LaunchConfig) -> bool:
    try:
        body = _get_json(f"{config.backend_url}/api/v1/health")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False
    return body.get("status") == "ok"


def frontend_ready(config: LaunchConfig) -> bool:
    try:
        html = _get_html(f"{config.frontend_url}/")
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
    return 'id="root"' in html and "<script" in html


def frontend_api_ready(config: LaunchConfig) -> bool:
    """The frontend proxy must reach the backend before the window opens."""

    try:
        body = _get_json(f"{config.frontend_url}/api/v1/health")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False
    return body.get("status") == "ok"


def wait_for_services(
    manager: ServiceManager,
    on_status: Callable[[str], None] | None = None,
    timeout: float | None = None,
    poll_interval: float = 0.5,
) -> None:
    """Wait for both HTTP endpoints, failing fast if a child exits."""

    config = manager.config
    effective_timeout = timeout if timeout is not None else config.timeout
    deadline = time.monotonic() + effective_timeout
    backend_ok = False
    frontend_ok = False
    proxy_ok = False
    while time.monotonic() < deadline:
        for service in manager.services():
            if not service.running():
                raise LaunchError(service.failure_detail())
        if not backend_ok:
            backend_ok = backend_ready(config)
            if backend_ok and on_status:
                on_status("Backend ready · checking model")
        if not frontend_ok:
            frontend_ok = frontend_ready(config)
            if frontend_ok and on_status:
                on_status("Frontend ready · checking API bridge")
        if backend_ok and frontend_ok and not proxy_ok:
            proxy_ok = frontend_api_ready(config)
            if proxy_ok and on_status:
                on_status("Local services ready · verifying Qwen and models")
        if backend_ok and frontend_ok and proxy_ok:
            return
        if on_status:
            if not backend_ok:
                on_status("Waiting for backend services…" if frontend_ok else "Starting backend services…")
            elif not frontend_ok:
                on_status("Starting frontend server…")
            else:
                on_status("Checking the API bridge…")
        time.sleep(poll_interval)
    pending: list[str] = []
    if not backend_ok:
        pending.append("FastAPI backend")
    if not frontend_ok:
        pending.append("frontend server")
    if backend_ok and frontend_ok and not proxy_ok:
        pending.append("API bridge")
    raise LaunchError(
        f"{' and '.join(pending) or 'Local services'} did not become ready within "
        f"{effective_timeout:.0f} seconds. Check the logs for the failing process."
    )


def patron_state(config: LaunchConfig) -> dict:
    """Best-effort model status for diagnostics; never blocks startup."""

    try:
        return _get_json(f"{config.backend_url}/api/v1/patron/status", timeout=2.0)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}


def ui_theme(config: LaunchConfig) -> str:
    """Read the persisted UI theme so the native shell paints the right colour."""

    try:
        body = _get_json(f"{config.backend_url}/api/v1/settings", timeout=2.0)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return "dark"
    theme = (body.get("ui") or {}).get("theme")
    return "light" if theme == "light" else "dark"


def wait_for_patron(
    config: LaunchConfig,
    timeout: float = 30.0,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    """Wait for the production PATRON checkpoint; never report a failed model as ready."""

    deadline = time.monotonic() + timeout
    state: dict = {}
    last_message = ""
    while time.monotonic() < deadline:
        state = patron_state(config)
        current = str(state.get("state", "UNKNOWN"))
        if current == "READY":
            return state
        if current in {"ERROR", "NOT_CONFIGURED", "DISABLED"}:
            detail = state.get("error") or state.get("message") or state.get("last_error")
            raise LaunchError(
                f"[PATRON_{current}] PATRON is unavailable: {detail or 'the model did not become ready.'} "
                f"See {service_log_paths()[0]}."
            )
        if on_status:
            message = f"PATRON {current.lower()} · waiting for production checkpoint"
            if message != last_message:
                on_status(message)
                last_message = message
        time.sleep(0.5)
    raise LaunchError(
        f"[PATRON_READY_TIMEOUT] PATRON did not become ready within {timeout:.0f}s "
        f"(last state: {state.get('state', 'UNKNOWN')}). See {service_log_paths()[0]}."
    )


def verify_qwen_inference(
    config: LaunchConfig,
    timeout: float = 60.0,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    """Prove the HTTP inference path, not only the status flag, before opening the UI."""

    try:
        result = _post_json(
            f"{config.backend_url}/api/v1/kie/chat",
            {
                "message": "Reply with exactly: KBMTI online.",
                "max_tokens": 8,
                "temperature": 0.0,
                "top_p": 1.0,
                "thinking": False,
            },
            timeout=timeout,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise LaunchError(
            f"[QWEN_API_INFERENCE_FAILED] Qwen did not answer through the backend API: {exc}. "
            f"See {service_log_paths()[0]}."
        ) from exc
    text = str(result.get("text") or "").strip()
    completion = int((result.get("stats") or {}).get("completion_tokens") or 0)
    if not text or completion <= 0:
        raise LaunchError(
            "[QWEN_API_INFERENCE_FAILED] Qwen returned an empty API inference result; "
            f"refusing to launch the Qwen-dependent workspace. See {service_log_paths()[0]}."
        )
    if on_status:
        on_status(f"Qwen API inference verified · {completion} tokens · {text[:40]}")
    return result


def wait_for_qwen(
    config: LaunchConfig,
    timeout: float = 150.0,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    """Block until Qwen has completed a real Vulkan smoke generation.

    A running Python backend or an existing model file is not enough. The gate
    requires a Vulkan backend, offloaded layers and the readiness generation's
    ``smoke_test.ok`` result before the UI may open.
    """

    deadline = time.monotonic() + timeout
    last_state = "UNKNOWN"
    last_message = ""
    last_status: dict = {}
    last_transport_error = ""
    while time.monotonic() < deadline:
        try:
            status = _get_json(f"{config.backend_url}/api/v1/kie/status", timeout=3.0)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            # The first request may race the HTTP listener. Keep waiting until the
            # readiness deadline, then report the actual transport failure.
            last_transport_error = str(exc)
            time.sleep(0.6)
            continue
        last_transport_error = ""
        last_status = status
        last_state = str(status.get("health_state") or status.get("state") or "UNKNOWN")
        if not status.get("enabled", True):
            raise LaunchError(
                "[QWEN_DISABLED] Qwen is disabled by configuration; the Trading Intelligence "
                "interface cannot start. Enable KBMTI_KIE_ENABLED and retry."
            )
        if status.get("ready") is True:
            backend = status.get("backend")
            memory = status.get("memory") or {}
            offloaded = int(memory.get("offloaded_layers") or status.get("offloaded_layers") or 0)
            smoke = status.get("smoke_test") or {}
            if backend != "vulkan":
                raise LaunchError(
                    f"[QWEN_CPU_FALLBACK] Qwen initialized on '{backend}' instead of Vulkan; "
                    "CPU/other fallback is not permitted. See the backend log."
                )
            if offloaded <= 0 or not smoke.get("ok"):
                raise LaunchError(
                    "[QWEN_READINESS_INVALID] Qwen reports ready without verified GPU offload "
                    "and a successful smoke inference. See the backend log."
                )
            if on_status:
                gpu = status.get("gpu_name") or "Vulkan device"
                on_status(f"Qwen READY · {gpu} · {offloaded} layers · smoke inference OK")
            return status
        terminal = {
            "GPU_BACKEND_UNAVAILABLE": "QWEN_VULKAN_UNAVAILABLE",
            "GPU_MEMORY_INSUFFICIENT": "QWEN_VRAM_INSUFFICIENT",
            "MODEL_NOT_FOUND": "QWEN_MODEL_NOT_FOUND",
            "MODEL_LOAD_FAILED": "QWEN_LOAD_FAILED",
            "INFERENCE_FAILED": "QWEN_INFERENCE_FAILED",
            "STOPPING": "QWEN_STOPPING",
        }
        if last_state in terminal or str(status.get("state")) == "ERROR":
            code = terminal.get(last_state, "QWEN_FAILED")
            detail = status.get("last_error") or status.get("health_message")
            raise LaunchError(
                f"[{code}] Qwen initialization failed (state: {last_state}): "
                f"{detail or 'no detail was reported'}. See {service_log_paths()[0]}."
            )
        message = f"Qwen {last_state.lower()} · AMD Vulkan · waiting for model and smoke inference"
        if on_status and message != last_message:
            on_status(message)
            last_message = message
        time.sleep(0.6)
    detail = (
        last_status.get("last_error")
        or last_status.get("health_message")
        or last_transport_error
        or "no detail"
    )
    raise LaunchError(
        f"[QWEN_READY_TIMEOUT] Qwen did not become inference-ready within {timeout:.0f}s "
        f"(state: {last_state}; {detail}). See {service_log_paths()[0]}."
    )

