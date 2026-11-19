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

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
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

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def exit_code(self) -> int | None:
        return self.process.poll() if self.process else None

    def stop(self, grace_seconds: float = 4.0) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            if IS_WINDOWS:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except OSError:
                    process.terminate()
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
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
        self.backend.start()
        try:
            self.frontend.start()
        except Exception:
            self.backend.stop()
            raise

    def stop(self) -> None:
        self.frontend.stop()
        self.backend.stop()

    def services(self) -> tuple[ManagedService, ManagedService]:
        return self.backend, self.frontend


def _get_json(url: str, timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8"))


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
                on_status("Workspace ready")
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


def wait_for_patron(config: LaunchConfig, timeout: float = 20.0) -> dict:
    """Wait for the background model load, bounded so a model error cannot hang the app."""

    deadline = time.monotonic() + timeout
    state: dict = {}
    while time.monotonic() < deadline:
        state = patron_state(config)
        if state.get("state") in {"READY", "ERROR", "NOT_CONFIGURED", "DISABLED"}:
            return state
        time.sleep(0.5)
    return state
