from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep
from app.core.timeframes import TIMEFRAME_LABEL, TIMEFRAME_SECONDS, Timeframe
from app.schemas.models import CandleSeriesResponse, MT5Status, SnapshotResponse, SymbolListResponse

router = APIRouter(prefix="/market", tags=["market"])


class SymbolSelectionRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)


class SymbolSelectionResponse(BaseModel):
    selected_symbol: str
    btc_like: bool
    status: MT5Status


class TimeframeSelectionRequest(BaseModel):
    timeframe: str = Field(min_length=1, max_length=8)


class TimeframeSelectionResponse(BaseModel):
    timeframe: str
    status: MT5Status


class TimeframeOption(BaseModel):
    value: str
    label: str
    seconds: int


class ProviderSelectionRequest(BaseModel):
    provider: str = Field(pattern=r"^(binance|mt5)$")


class ProviderOption(BaseModel):
    id: str
    label: str
    role: str
    default: bool = False


@router.get("/snapshot", response_model=SnapshotResponse)
def market_snapshot(container: ContainerDep) -> dict:
    return container.market.snapshot()


@router.get("/candles", response_model=CandleSeriesResponse)
def market_candles(
    container: ContainerDep,
    limit: int = Query(default=500, ge=1, le=1500),
    refresh: bool = Query(default=False),
) -> dict:
    return container.market.candle_series(limit=limit, force=refresh)


@router.post("/symbol", response_model=SymbolSelectionResponse)
def select_symbol(payload: SymbolSelectionRequest, container: ContainerDep) -> dict:
    return container.market.select_symbol(payload.symbol)


@router.get("/symbols", response_model=SymbolListResponse)
def market_symbols(container: ContainerDep, refresh: bool = Query(default=False)) -> dict:
    return container.market.provider.get_symbols(refresh=refresh)


@router.post("/timeframe", response_model=TimeframeSelectionResponse)
def select_timeframe(payload: TimeframeSelectionRequest, container: ContainerDep) -> dict:
    return container.market.set_timeframe(payload.timeframe)


@router.get("/timeframes", response_model=list[TimeframeOption])
def timeframes() -> list[dict]:
    return [
        {"value": timeframe.value, "label": TIMEFRAME_LABEL[timeframe], "seconds": TIMEFRAME_SECONDS[timeframe]}
        for timeframe in Timeframe
    ]


@router.get("/providers", response_model=list[ProviderOption])
def providers(container: ContainerDep) -> list[dict]:
    active = container.market.provider_id
    return [
        {"id": "binance", "label": "Binance", "role": "Recommended / Primary", "default": active == "binance"},
        {"id": "mt5", "label": "MetaTrader 5", "role": "Optional", "default": active == "mt5"},
    ]


@router.get("/provider", response_model=MT5Status)
def current_provider(container: ContainerDep) -> dict:
    return container.market.status()


@router.post("/provider", response_model=MT5Status)
def select_provider(payload: ProviderSelectionRequest, container: ContainerDep) -> dict:
    return container.market.select_provider(payload.provider, connect=True)


@router.post("/connect", response_model=MT5Status)
def connect_market(container: ContainerDep) -> dict:
    return container.market.connect(force=True)


@router.post("/reconnect", response_model=MT5Status)
def reconnect_market(container: ContainerDep) -> dict:
    return container.market.reconnect()


@router.post("/disconnect", response_model=MT5Status)
def disconnect_market(container: ContainerDep) -> dict:
    return container.market.disconnect()


@router.post("/refresh", response_model=SnapshotResponse)
def refresh_market(container: ContainerDep) -> dict:
    return container.market.refresh()
