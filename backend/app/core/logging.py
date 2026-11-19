"""Logging setup: rotating local log file plus console output for development."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_configured = False


def configure_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    """Configure the root logger once and return the active log file path."""

    global _configured
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "kbmti-backend.log"
    if _configured:
        return log_file

    root = logging.getLogger()
    root.setLevel(level)

    file_handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(console)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True
    return log_file


def reset_logging_for_tests() -> None:
    global _configured
    _configured = False


def tail_log(log_file: Path, limit: int = 200) -> list[str]:
    if not log_file.exists():
        return []
    try:
        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    cleaned = [line.rstrip("\n") for line in lines[-max(1, limit) :]]
    return cleaned
