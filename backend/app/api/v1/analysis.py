"""Additive market-intelligence endpoints.

Both routes are read-only and delegate to ``AppContainer.analysis``. They are
registered under the existing ``/api/v1/market`` prefix without changing any
existing market endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analysis.contracts import (
    SCOPE_SYMBOL,
    SCOPE_TIMEFRAME,
    MarketContextResponse,
    MarketSnapshot,
)
from app.analysis.service import AnalysisService
from app.api.deps import ContainerDep
from app.core.errors import AnalysisUnavailableError

router = APIRouter(prefix="/market", tags=["analysis"])


def _service(container) -> AnalysisService:  # noqa: ANN001 - avoids an api<->container import cycle
    service = container.analysis
    if service is None:
        raise AnalysisUnavailableError(
            "Deterministic market analysis failed to initialise; the rest of the application is unaffected."
        )
    return service


@router.get("/context", response_model=MarketContextResponse)
def market_context(
    container: ContainerDep,
    symbol: str = Query(default=SCOPE_SYMBOL, min_length=1, max_length=32),
    timeframe: str = Query(default=SCOPE_TIMEFRAME, min_length=1, max_length=8),
    refresh: bool = Query(default=False),
) -> MarketContextResponse:
    """Return the compact, validated market context for the latest closed bar."""

    return _service(container).context(symbol=symbol, timeframe=timeframe, refresh=refresh)


@router.get("/analysis", response_model=MarketSnapshot)
def market_analysis(
    container: ContainerDep,
    symbol: str = Query(default=SCOPE_SYMBOL, min_length=1, max_length=32),
    timeframe: str = Query(default=SCOPE_TIMEFRAME, min_length=1, max_length=8),
    refresh: bool = Query(default=False),
) -> MarketSnapshot:
    """Return the full deterministic analysis bundle with feature evidence."""

    return _service(container).snapshot(symbol=symbol, timeframe=timeframe, refresh=refresh)
