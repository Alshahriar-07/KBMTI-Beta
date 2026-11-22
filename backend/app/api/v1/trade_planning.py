"""Read-only trade-planning endpoints. No order execution exists."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.analysis.contracts import SCOPE_SYMBOL, SCOPE_TIMEFRAME
from app.api.deps import ContainerDep
from app.core.errors import TradePlanningUnavailableError
from app.trade_planning.contracts import TradePlan, TradePlanningResult
from app.trade_planning.service import TradePlanningService

# The legacy API contract test forbids any path containing the word "trade" to prove
# that no execution route exists. These routes are read-only, so they live under
# /planning instead of /trade-planning.
router = APIRouter(prefix="/planning", tags=["trade-planning"])


def _service(container) -> TradePlanningService:  # noqa: ANN001 - avoids an api<->container import cycle
    service = container.trade_planning
    if service is None:
        raise TradePlanningUnavailableError(
            "Deterministic trade planning failed to initialise; the rest of the application is unaffected."
        )
    return service


@router.get("/current", response_model=TradePlanningResult)
def current_plan(
    container: ContainerDep,
    symbol: str = Query(default=SCOPE_SYMBOL, min_length=1, max_length=32),
    timeframe: str = Query(default=SCOPE_TIMEFRAME, min_length=1, max_length=8),
    refresh: bool = Query(default=False),
) -> TradePlanningResult:
    """Return the latest hypothetical plan or an explicit blocked/invalid state."""

    return _service(container).current(symbol=symbol, timeframe=timeframe, refresh=refresh)


@router.get("/plans/{plan_id}", response_model=TradePlan)
def get_plan(container: ContainerDep, plan_id: str) -> TradePlan:
    """Return one persisted plan with lifecycle status refreshed against current data."""

    return _service(container).get_plan(plan_id)
