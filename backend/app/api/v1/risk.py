"""Read-only risk-validation endpoint. No position sizing or execution."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analysis.contracts import SCOPE_SYMBOL, SCOPE_TIMEFRAME
from app.api.deps import ContainerDep
from app.core.errors import RiskUnavailableError
from app.risk.contracts import RiskCurrentResponse
from app.trade_planning.service import TradePlanningService

router = APIRouter(prefix="/risk", tags=["risk"])


def _service(container) -> TradePlanningService:  # noqa: ANN001 - avoids an api<->container import cycle
    service = container.trade_planning
    if service is None:
        raise RiskUnavailableError(
            "Risk validation depends on trade planning, which failed to initialise."
        )
    return service


@router.get("/current", response_model=RiskCurrentResponse)
def current_risk(
    container: ContainerDep,
    symbol: str = Query(default=SCOPE_SYMBOL, min_length=1, max_length=32),
    timeframe: str = Query(default=SCOPE_TIMEFRAME, min_length=1, max_length=8),
    refresh: bool = Query(default=False),
) -> RiskCurrentResponse:
    """Return the risk assessment for the latest plan attempt, with null position size."""

    return _service(container).risk_current(symbol=symbol, timeframe=timeframe, refresh=refresh)
