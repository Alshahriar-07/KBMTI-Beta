"""Read-only deterministic strategy endpoints.

Routing is additive under ``/api/v1/strategies``. Every response is a typed Phase 2
contract and contains no entry, stop, target, leverage or position size.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analysis.contracts import SCOPE_SYMBOL, SCOPE_TIMEFRAME
from app.api.deps import ContainerDep
from app.core.errors import StrategyUnavailableError
from app.strategies.config import STRATEGY_ID
from app.strategies.contracts import StrategyCatalogResponse, TrendPullbackEvaluation
from app.strategies.service import StrategyService

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _service(container) -> StrategyService:  # noqa: ANN001 - avoids an api<->container import cycle
    service = container.strategies
    if service is None:
        raise StrategyUnavailableError(
            "Deterministic strategy evaluation failed to initialise; the rest of the application is unaffected."
        )
    return service


@router.get("", response_model=StrategyCatalogResponse)
def strategy_catalog_endpoint(container: ContainerDep) -> StrategyCatalogResponse:
    """List the implemented deterministic strategies and their approved scope."""

    return _service(container).catalog()


@router.get("/trend-pullback", response_model=TrendPullbackEvaluation)
def trend_pullback_evaluation(
    container: ContainerDep,
    symbol: str = Query(default=SCOPE_SYMBOL, min_length=1, max_length=32),
    timeframe: str = Query(default=SCOPE_TIMEFRAME, min_length=1, max_length=8),
    refresh: bool = Query(default=False),
) -> TrendPullbackEvaluation:
    """Evaluate the latest closed BTCUSDT M15 bar with the Trend Pullback rules."""

    return _service(container).evaluate(
        strategy_id=STRATEGY_ID,
        symbol=symbol,
        timeframe=timeframe,
        refresh=refresh,
    )
