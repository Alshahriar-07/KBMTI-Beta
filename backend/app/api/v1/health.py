from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.core.config import APP_NAME, APP_VERSION, STAGE
from app.schemas.models import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health(container: ContainerDep) -> HealthResponse:
    return HealthResponse(
        app=APP_NAME,
        version=APP_VERSION,
        stage=STAGE,
        uptime_seconds=container.uptime_seconds,
        started_at=datetime.fromtimestamp(container.started_at, tz=UTC).isoformat(timespec="seconds"),
        database=str(container.db.path),
        patron={
            "state": container.patron.state,
            "ready": container.patron.ready,
            "model_id": container.patron.status()["model_id"],
            "last_success_at": container.patron.status()["last_success_at"],
            "last_error": container.patron.status()["last_error"],
        },
    )
