from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep
from app.core.errors import NotFoundError, ValidationError
from app.market_data.candles import Candle
from app.schemas.models import ForecastHistoryResponse, ForecastStatusResponse

router = APIRouter(prefix="/forecast", tags=["forecast"])


class RunForecastRequest(BaseModel):
    symbol: str | None = Field(default=None, max_length=32)
    timeframe: str | None = Field(default=None, max_length=8)
    horizon: int = Field(default=6, ge=1, le=6)


@router.get("/status", response_model=ForecastStatusResponse)
def forecast_status(container: ContainerDep) -> dict:
    return container.forecast.status()


@router.post("/run")
def run_forecast(container: ContainerDep, payload: RunForecastRequest | None = None) -> dict[str, Any]:
    request = payload or RunForecastRequest()
    snapshot = container.market.snapshot()
    symbol = (request.symbol or snapshot.get("symbol") or "BTCUSDT").strip().upper()
    timeframe = (request.timeframe or snapshot.get("timeframe") or "M15").strip().upper()

    candles = container.market.completed_candles(force=True)
    if not candles:
        rows = container.binance_history.recent("BTCUSDT", "15m", limit=520)
        candles = [
            Candle(
                time=row.open_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                tick_volume=row.trades,
                real_volume=int(row.volume),
                source="binance",
                symbol="BTCUSDT",
            )
            for row in rows
        ]
    if not candles:
        raise ValidationError(
            "No completed candles are available to validate the forecast request.",
            {"provider": container.market.provider_id},
        )
    return container.forecast.run_forecast(
        symbol=symbol,
        timeframe=timeframe,
        horizon=request.horizon,
        candles=candles,
    )


@router.get("/latest")
def forecast_latest(container: ContainerDep) -> dict[str, Any] | None:
    return container.forecast.latest()


@router.get("/live")
def forecast_live(
    container: ContainerDep,
    limit: int = Query(default=60, ge=10, le=200),
) -> dict[str, Any]:
    """One polling payload for the forecast workspace.

    Candles always come from Binance BTC/USDT 15m (PATRON's contract) so the
    chart does not silently change venue when another provider is selected.
    """

    payload = container.forecast.live_context(limit=limit)
    snapshot = container.market.snapshot()
    aligned = (
        snapshot.get("provider") == "binance"
        and str(snapshot.get("symbol") or "").upper() == "BTCUSDT"
        and str(snapshot.get("timeframe") or "").upper() == "M15"
    )
    forming = None
    if aligned and snapshot.get("data_state") == "live":
        forming = container.market.candle_series(limit=2).get("forming_candle")
    payload["forming_candle"] = forming
    payload["market"] = {
        "provider": snapshot.get("provider") or container.market.provider_id,
        "symbol": snapshot.get("symbol"),
        "timeframe": snapshot.get("timeframe"),
        "last": snapshot.get("last"),
        "daily_change_percent": snapshot.get("daily_change_percent"),
        "data_state": snapshot.get("data_state"),
        "connected": snapshot.get("connected"),
        "live": aligned,
        "as_of": snapshot.get("last_update"),
    }
    return payload


@router.get("/timeline")
def forecast_timeline(
    container: ContainerDep,
    limit: int = Query(default=24, ge=1, le=200),
) -> dict[str, Any]:
    return container.forecast.timeline(limit=limit)


@router.post("/evaluate")
def evaluate_forecasts(
    container: ContainerDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return container.forecast.evaluate(limit_runs=limit)


@router.get("/history", response_model=ForecastHistoryResponse)
def forecast_history(container: ContainerDep, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    return container.forecast.history(limit=limit)


@router.get("/{run_id}")
def forecast_run(run_id: str, container: ContainerDep) -> dict:
    run = container.forecast.get_run(run_id)
    if not run:
        raise NotFoundError(f"Forecast run '{run_id}' was not found.")
    return run
