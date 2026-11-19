from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.indicators.engine import compute_indicators
from app.market_data.candles import epoch_to_iso
from app.schemas.models import IndicatorsResponse

router = APIRouter(prefix="/indicators", tags=["indicators"])


@router.get("", response_model=IndicatorsResponse)
def indicators(
    container: ContainerDep,
    limit: int = Query(default=500, ge=1, le=1500),
) -> dict:
    candles = container.market.completed_candles()
    series = container.market.candle_series(limit=limit)
    selected = candles[-limit:]
    timeframe = series["timeframe"]

    if not selected:
        return {
            "symbol": series["symbol"],
            "timeframe": timeframe,
            "candle_count": 0,
            "last_candle_time_iso": None,
            "series": {},
            "latest": {},
            "parameters": {},
            "warmup_bars": 0,
            "data_state": series["data_state"],
            "warnings": series["warnings"],
            "time_basis": series["time_basis"],
        }

    bundle = compute_indicators(selected)
    payload = bundle.to_payload()
    return {
        "symbol": series["symbol"],
        "timeframe": timeframe,
        "candle_count": len(selected),
        "last_candle_time_iso": epoch_to_iso(selected[-1].time),
        "series": payload["series"],
        "latest": payload["latest"],
        "parameters": payload["parameters"],
        "warmup_bars": bundle.warmup_bars(),
        "data_state": series["data_state"],
        "warnings": series["warnings"],
        "time_basis": series["time_basis"],
    }
