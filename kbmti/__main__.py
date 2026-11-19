"""CLI entry point: ``python -m kbmti``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import (
    DEFAULT_TIMEOUT,
    LOG_DIR,
    LaunchConfig,
    LaunchError,
    resolve_port,
    validate_environment,
)
from .services import ServiceManager, wait_for_patron, wait_for_services


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kbmti",
        description=(
            "Launch the KBMTI native desktop workstation. Starts the FastAPI backend, "
            "the PATRON model and the Vite frontend, then embeds the UI in a PySide6 window."
        ),
    )
    parser.add_argument("--version", action="version", version=f"KBMTI {__version__}")
    parser.add_argument(
        "--mode",
        choices=("development", "production"),
        default="development",
        help="development runs Vite dev with HMR; production serves the built frontend (default: development)",
    )
    parser.add_argument("--backend-port", type=int, default=0, help="pin the backend port (default: free port)")
    parser.add_argument("--frontend-port", type=int, default=0, help="pin the frontend port (default: free port)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds to wait for services (default: {DEFAULT_TIMEOUT:.0f})",
    )
    parser.add_argument("--devtools", action="store_true", help="enable Chromium DevTools (F12)")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="start and probe all services without opening the window, then shut down",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        help="capture the native window to a PNG after load, then exit (diagnostics)",
    )
    parser.add_argument("--data-dir", type=Path, help="override KBMTI_DATA_DIR for this launch")
    parser.add_argument(
        "--window-size",
        metavar="WxH",
        help="diagnostic window size, for example 1366x768",
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> LaunchConfig:
    backend_port = resolve_port(args.backend_port, "Backend")
    frontend_port = resolve_port(args.frontend_port, "Frontend")
    window_size = None
    if args.window_size:
        try:
            width, height = (int(part) for part in args.window_size.lower().split("x", 1))
            window_size = (width, height)
        except ValueError as exc:
            raise LaunchError("--window-size must look like 1366x768") from exc
    return LaunchConfig(
        backend_port=backend_port,
        frontend_port=frontend_port,
        mode=args.mode,
        timeout=args.timeout,
        devtools=args.devtools,
        data_dir=args.data_dir,
        screenshot=args.screenshot,
        window_size=window_size,
    )


def run_headless(config: LaunchConfig) -> int:
    manager = ServiceManager(config)
    try:
        validate_environment(config)
        manager.start()
        wait_for_services(manager, on_status=lambda text: print(f"[kbmti] {text}", flush=True))
        state = wait_for_patron(config)
        print(f"[kbmti] backend:  {config.backend_url}", flush=True)
        print(f"[kbmti] frontend: {config.frontend_url}", flush=True)
        print(f"[kbmti] patron:   {state.get('model_id', 'unavailable')} · {state.get('state', 'unknown')}", flush=True)
        print("[kbmti] services are ready; shutting down", flush=True)
        return 0
    except LaunchError as exc:
        print(f"[kbmti] {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        manager.stop()


def run_gui(config: LaunchConfig) -> int:
    if config.screenshot:
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    from importlib.util import find_spec

    if find_spec("PySide6") is None:
        print(
            "PySide6 is not installed in this Python environment.\n"
            "Install the desktop dependencies with:\n"
            "  backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-desktop.txt",
            file=sys.stderr,
        )
        return 2

    from .desktop import run_desktop

    return run_desktop(config)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = _config_from_args(args)
        if args.headless:
            return run_headless(config)
        return run_gui(config)
    except LaunchError as exc:
        print(f"[kbmti] {exc}", file=sys.stderr)
        print(f"[kbmti] logs: {LOG_DIR}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
