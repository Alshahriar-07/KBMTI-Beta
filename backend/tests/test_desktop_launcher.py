from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kbmti.config import (  # noqa: E402
    LaunchConfig,
    LaunchError,
    backend_environment,
    find_free_port,
    frontend_command,
    resolve_port,
    validate_environment,
)
from kbmti.services import ManagedService  # noqa: E402


def test_free_port_is_bindable() -> None:
    port = find_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


def test_resolve_port_rejects_occupied_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied = sock.getsockname()[1]
        with pytest.raises(LaunchError, match="already in use"):
            resolve_port(occupied, "Backend")


def test_frontend_command_passes_detected_port() -> None:
    config = LaunchConfig(frontend_port=4123)
    command = frontend_command(config)
    assert "--port" in command
    assert command[command.index("--port") + 1] == "4123"
    assert "--strictPort" in command
    assert "dev" in command


def test_backend_environment_sets_loopback_port(tmp_path: Path) -> None:
    config = LaunchConfig(backend_port=9876, data_dir=tmp_path)
    env = backend_environment(config)
    assert env["KBMTI_HOST"] == "127.0.0.1"
    assert env["KBMTI_PORT"] == "9876"
    assert env["KBMTI_DATA_DIR"] == str(tmp_path)


def test_validate_environment_for_development() -> None:
    validate_environment(LaunchConfig())


def test_managed_service_stops_child(tmp_path: Path) -> None:
    service = ManagedService(
        name="test child",
        command=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=ROOT,
        env=dict(os.environ),
        log_path=tmp_path / "child.log",
    )
    service.start()
    assert service.running()
    pid = service.process.pid  # type: ignore[union-attr]
    service.stop()
    assert not service.running()
    assert service.exit_code() is not None
    assert pid > 0
