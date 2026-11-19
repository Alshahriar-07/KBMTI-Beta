from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.schemas.models import SignalResponse

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/current", response_model=SignalResponse)
def current_signal(container: ContainerDep, refresh: bool = Query(default=False)) -> dict:
    return container.signals.current(refresh=refresh)


@router.get("/history")
def signal_history(
    container: ContainerDep,
    limit: int = Query(default=50, ge=1, le=200),
    symbol: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    events = container.signals.history(limit=limit, symbol=symbol)
    return {"events": events, "count": len(events)}
