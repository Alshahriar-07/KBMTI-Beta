"""PATRON model endpoints: status, information, health, readiness and inference."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body

from app.api.deps import ContainerDep
from app.core.errors import ValidationError
from app.schemas.models import PatronReadinessResponse, PatronStatusResponse

router = APIRouter(prefix="/patron", tags=["patron"])

MAX_INFER_CANDLES = 96
MAX_BODY_BYTES = 256_000


@router.get("/status", response_model=PatronStatusResponse)
def patron_status(container: ContainerDep) -> dict:
    return container.patron.status()


@router.get("/info")
def patron_info(container: ContainerDep) -> dict[str, Any]:
    return container.patron.info()


@router.get("/health")
def patron_health(container: ContainerDep) -> dict[str, Any]:
    return container.patron.health()


@router.get("/readiness", response_model=PatronReadinessResponse)
def patron_readiness(container: ContainerDep) -> dict:
    return container.patron.readiness()


@router.post("/load")
def patron_load(container: ContainerDep) -> dict[str, Any]:
    """Idempotent explicit load; concurrent callers share one initialization."""

    container.patron.ensure_loaded(blocking=True)
    return container.patron.status()


@router.post("/infer")
def patron_infer(
    container: ContainerDep,
    payload: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Run PATRON on its native 96-candle input contract."""

    if len(str(payload)) > MAX_BODY_BYTES:
        raise ValidationError("The PATRON payload is too large.")
    candles = payload.get("candles")
    if not isinstance(candles, list) or len(candles) != MAX_INFER_CANDLES:
        raise ValidationError(
            "PATRON requires exactly 96 closed BTC/USDT 15m candles, oldest -> newest.",
            {
                "received": len(candles) if isinstance(candles, list) else None,
                "required": MAX_INFER_CANDLES,
            },
        )
    return container.patron.infer_payload(payload)
