from __future__ import annotations

import logging
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Query, Request

from app.api.deps import ContainerDep
from app.core.config import APP_NAME, APP_VERSION, STAGE
from app.core.logging import tail_log
from app.schemas.models import DiagnosticsResponse

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
logger = logging.getLogger(__name__)


def _log_file(request: Request) -> Path | None:
    return getattr(request.app.state, "log_file", None)


@router.get("", response_model=DiagnosticsResponse)
def diagnostics(request: Request, container: ContainerDep) -> dict:
    active = container.market.status()
    status = container.market.mt5_status()
    log_file = _log_file(request)
    db = container.db
    return {
        "app": {"name": APP_NAME, "version": APP_VERSION, "stage": STAGE},
        "backend": {
            "status": "ok",
            "host": container.settings.host,
            "port": container.settings.port,
            "uptime_seconds": container.uptime_seconds,
            "data_dir": str(container.settings.data_dir),
            "poll_interval_seconds": container.settings.poll_interval_seconds,
            "candle_refresh_seconds": container.settings.candle_refresh_seconds,
            "stale_after_seconds": container.settings.stale_after_seconds,
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "platform": container.system.platform_info(),
        "market": {
            "provider": active.get("provider"),
            "provider_label": active.get("provider_label"),
            "state": active.get("state"),
            "state_label": active.get("state_label"),
            "state_reason": active.get("state_reason"),
            "connected": active.get("connected"),
            "selected_symbol": active.get("selected_symbol"),
            "timeframe": active.get("timeframe"),
            "freshness": active.get("freshness"),
            "freshness_reason": active.get("freshness_reason"),
            "last_error": active.get("last_error"),
            "last_successful_update": active.get("last_successful_update"),
            "ws_connected": active.get("ws_connected"),
            "rest_connected": active.get("rest_connected"),
            "providers": active.get("providers", {}),
        },
        "realtime": {
            "market": container.binance.diagnostics().get("realtime"),
            "forecast": container.forecast_automation.status(),
        },
        "patron": {
            **container.patron.health(),
            "runtime": container.patron.status(),
            "history_client": container.binance_history.status(),
        },
        "mt5": {
            "state": status["state"],
            "state_label": status["state_label"],
            "state_reason": status["state_reason"],
            "operational": status["operational"],
            "package_available": status["package_available"],
            "package_version": status["package_version"],
            "connected": status["connected"],
            "terminal_connected": status["terminal_connected"],
            "broker_connected": status["broker_connected"],
            "account_available": status["account_available"],
            "symbol_available": status["symbol_available"],
            "tick_available": status["tick_available"],
            "history_available": status["history_available"],
            "terminal": status["terminal"],
            "account": status["account"],
            "detected_terminal_paths": status["terminal_paths"],
            "terminal_candidates": status["terminal_candidates"],
            "configured_terminal_path": status["configured_terminal_path"],
            "resolved_terminal_path": status["resolved_terminal_path"],
            "selected_symbol": status["selected_symbol"],
            "timeframe": status["timeframe"],
            "freshness": status["freshness"],
            "freshness_reason": status["freshness_reason"],
            "last_error": status["last_error"],
            "last_error_code": status["last_error_code"],
            "last_error_description": status["last_error_description"],
            "last_error_stage": status["last_error_stage"],
            "reconnect_attempts": status["reconnect_attempts"],
            "next_retry_seconds": status["next_retry_seconds"],
            "last_successful_update": status["last_successful_update"],
            "time_basis": status["time_basis"],
            "server_offset_seconds": status["server_offset_seconds"],
            "connection": container.market.diagnostics(),
        },
        "database": {
            "path": str(db.path),
            "size_bytes": db.size_bytes(),
            "tables": db.table_counts(),
            "integrity": db.integrity_check(),
        },
        "logs": {
            "path": str(log_file) if log_file else None,
            "recent": tail_log(log_file, limit=200) if log_file else [],
        },
        "settings": container.settings_repo.all(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


@router.get("/logs")
def logs(request: Request, limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    log_file = _log_file(request)
    return {
        "path": str(log_file) if log_file else None,
        "lines": tail_log(log_file, limit=limit) if log_file else [],
    }
