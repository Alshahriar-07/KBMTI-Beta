from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep

router = APIRouter(prefix="/replay", tags=["replay"])

REPLAY_MESSAGE = (
    "Replay foundation only: step through cached candles. Point-in-time PATRON replay and "
    "forecast scoring are available from stored forecast runs on the Forecasts page."
)


@router.get("/window")
def replay_window(
    container: ContainerDep,
    start: int = Query(default=0, ge=0),
    count: int = Query(default=200, ge=20, le=1000),
) -> dict:
    series = container.market.candle_series(limit=1000)
    candles = series.get("candles", [])
    start_index = min(max(0, start), max(0, len(candles) - 1))
    end_index = min(len(candles), start_index + count)
    window = candles[start_index:end_index]
    return {
        "symbol": series["symbol"],
        "timeframe": series["timeframe"],
        "start_index": start_index,
        "end_index": end_index,
        "total": len(candles),
        "candles": window,
        "source": series["source"],
        "data_state": series["data_state"],
        "time_basis": series["time_basis"],
        "ai_available": False,
        "message": REPLAY_MESSAGE,
    }
