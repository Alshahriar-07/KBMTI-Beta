from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.core.config import APP_VERSION
from app.schemas.models import SystemStatusResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatusResponse)
def system_status(container: ContainerDep) -> dict:
    active = container.market.status()
    mt5_status = container.market.mt5_status()
    patron = container.patron.status()
    backend = {
        "status": "ok",
        "version": APP_VERSION,
        "port": container.settings.port,
        "uptime_seconds": container.uptime_seconds,
        "database": str(container.db.path).replace("\\", "/"),
        "stage": 2,
        "patron": {
            "state": patron["state"],
            "ready": patron["ready"],
            "model_id": patron["model_id"],
            "last_success_at": patron["last_success_at"],
            "last_error": patron["last_error"],
        },
    }
    market = {
        "provider": active.get("provider"),
        "provider_label": active.get("provider_label"),
        "connected": active.get("connected"),
        "selected_symbol": active.get("selected_symbol"),
        "freshness": active.get("freshness"),
        "ws_connected": active.get("ws_connected"),
        "last_error": active.get("last_error"),
    }
    mt5 = {
        "connected": mt5_status["connected"],
        "package_available": mt5_status["package_available"],
        "selected_symbol": mt5_status["selected_symbol"],
        "freshness": mt5_status["freshness"],
        "last_error": mt5_status["last_error"],
    }
    return container.system.status(backend=backend, mt5=mt5, market=market)
