"""Paths, commands and launch configuration for the KBMTI desktop app."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "apps" / "desktop"
FRONTEND_PACKAGE = FRONTEND_DIR / "package.json"
FRONTEND_DIST = FRONTEND_DIR / "dist" / "index.html"
LOG_DIR = PROJECT_ROOT / ".local" / "desktop-logs"


def brand_asset(name: str) -> Path:
    """Resolve branding from the package first, then the repo/UI fallbacks.

    Package-relative resolution keeps the icon available in a future frozen
    build without depending on the current working directory.
    """

    for directory in (
        PACKAGE_DIR / "assets",
        PROJECT_ROOT / "assets",
        FRONTEND_DIR / "public" / "brand",
    ):
        candidate = (directory / name).resolve()
        if candidate.is_file():
            return candidate
    return (PACKAGE_DIR / "assets" / name).resolve()


BRAND_ICON = brand_asset("icon.ico")
BRAND_SPLASH = brand_asset("icon-512.png")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_TIMEOUT = 150.0


class LaunchError(RuntimeError):
    """A user-facing startup failure with an actionable message."""


@dataclass(frozen=True)
class LaunchConfig:
    host: str = DEFAULT_HOST
    backend_port: int = 0
    frontend_port: int = 0
    mode: str = "development"
    timeout: float = DEFAULT_TIMEOUT
    devtools: bool = False
    log_level: str = "info"
    data_dir: Path | None = None
    screenshot: Path | None = None
    window_size: tuple[int, int] | None = None
    extra_env: dict[str, str] = field(default_factory=dict)

    @property
    def backend_url(self) -> str:
        return f"http://{self.host}:{self.backend_port}"

    @property
    def frontend_url(self) -> str:
        return f"http://{self.host}:{self.frontend_port}"

    @property
    def production(self) -> bool:
        return self.mode == "production"


def port_is_free(port: int, host: str = DEFAULT_HOST) -> bool:
    if port <= 0 or port > 65535:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(preferred: int = 0, host: str = DEFAULT_HOST) -> int:
    """Return an available port, preferring ``preferred`` when it is free."""

    if preferred and port_is_free(preferred, host):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def resolve_port(requested: int, label: str, host: str = DEFAULT_HOST) -> int:
    if requested and not port_is_free(requested, host):
        raise LaunchError(
            f"{label} port {requested} is already in use on {host}. "
            "Stop the other process or pass a different port."
        )
    return find_free_port(requested, host)


def npm_executable() -> str:
    for candidate in ("npm.cmd", "npm"):
        found = shutil.which(candidate)
        if found:
            return found
    raise LaunchError("npm was not found on PATH. Install Node.js 20+ and reopen the terminal.")


def node_executable() -> str:
    found = shutil.which("node")
    if not found:
        raise LaunchError("node was not found on PATH. Install Node.js 20+ and reopen the terminal.")
    return found


def frontend_script(mode: str) -> str:
    if not FRONTEND_PACKAGE.is_file():
        raise LaunchError(f"Frontend package.json was not found at {FRONTEND_PACKAGE}.")
    try:
        package = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaunchError(f"Could not read the frontend package.json: {exc}") from exc
    scripts = package.get("scripts") or {}
    script = "preview" if mode == "production" else "dev"
    if not scripts.get(script):
        raise LaunchError(f"Frontend package.json has no '{script}' script.")
    return script


def frontend_command(config: LaunchConfig) -> list[str]:
    npm = npm_executable()
    script = frontend_script(config.mode)
    vite_args = [
        "--host",
        config.host,
        "--port",
        str(config.frontend_port),
        "--strictPort",
    ]
    # Invoke npm's JavaScript entry point directly. A .cmd shim would require
    # cmd.exe quoting, which breaks on the default "C:\Program Files" install.
    cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if cli.is_file():
        return [node_executable(), str(cli), "run", script, "--", *vite_args]
    if os.name == "nt":
        quoted = " ".join(f'"{arg}"' if " " in arg else arg for arg in [npm, "run", script, "--", *vite_args])
        return ["cmd.exe", "/d", "/s", "/c", quoted]
    return [npm, "run", script, "--", *vite_args]


def backend_command() -> list[str]:
    return [sys.executable, "-m", "app"]


def service_log_paths() -> tuple[Path, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / "backend.log", LOG_DIR / "frontend.log"


def validate_environment(config: LaunchConfig) -> None:
    if sys.version_info < (3, 12):  # noqa: UP036 - the CLI must explain the requirement
        raise LaunchError(f"Python 3.12+ is required; this interpreter is {sys.version.split()[0]}.")
    if not BACKEND_DIR.is_dir():
        raise LaunchError(f"Backend directory was not found at {BACKEND_DIR}.")
    if not FRONTEND_DIR.is_dir():
        raise LaunchError(f"Frontend directory was not found at {FRONTEND_DIR}.")
    node_executable()
    npm_executable()
    frontend_script(config.mode)
    if config.production and not FRONTEND_DIST.is_file():
        raise LaunchError(
            "Production frontend build is missing. Run 'npm run build' in apps/desktop first, "
            "or launch in development mode (the default)."
        )

    from importlib.util import find_spec

    missing = [name for name in ("fastapi", "uvicorn", "httpx") if find_spec(name) is None]
    if missing:
        raise LaunchError(
            "The active Python environment is missing backend dependencies: "
            + ", ".join(missing)
            + ". Use backend/.venv or install backend/requirements.txt."
        )


def backend_environment(config: LaunchConfig) -> dict[str, str]:
    env = dict(os.environ)
    env["KBMTI_HOST"] = config.host
    env["KBMTI_PORT"] = str(config.backend_port)
    env["PYTHONUNBUFFERED"] = "1"
    if config.data_dir:
        env["KBMTI_DATA_DIR"] = str(config.data_dir)
    env.update(config.extra_env)
    return env
