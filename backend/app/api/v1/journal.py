"""Paper/manual journal and outcome-review endpoints.

Paths intentionally avoid the legacy forbidden execution words so the existing
``test_no_trade_execution_routes_exist`` contract continues to prove that no
order-execution route exists. Nothing here places, fills or sizes an order.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.core.errors import ApiError, ValidationError
from app.outcomes.contracts import ReviewEnvelope
from app.trade_journal.contracts import (
    JournalTrade,
    MonitoringResult,
    OutcomeReviewRequest,
    SetupActionRequest,
    TradeCreateRequest,
    TradeEventRequest,
)

router = APIRouter(prefix="/journal", tags=["journal"])


def _journal(container):  # noqa: ANN001 - avoid api<->container import cycle
    service = container.journal
    if service is None:
        raise ApiError(
            "JOURNAL_UNAVAILABLE",
            "The local journal is unavailable because trade planning did not initialise.",
            503,
        )
    return service


def _outcomes(container):  # noqa: ANN001
    service = container.outcomes
    if service is None:
        raise ApiError("OUTCOMES_UNAVAILABLE", "The outcome service is unavailable.", 503)
    return service


@router.get("/records")
def list_records(
    container: ContainerDep,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return _journal(container).list_records(status=status, limit=limit)


@router.post("/records", response_model=JournalTrade, status_code=201)
def create_record(container: ContainerDep, request: TradeCreateRequest) -> JournalTrade:
    return _journal(container).create_record(request)


@router.get("/records/{record_id}", response_model=JournalTrade)
def get_record(container: ContainerDep, record_id: str) -> JournalTrade:
    return _journal(container).get_record(record_id)


@router.post("/records/{record_id}/events", response_model=JournalTrade)
def append_event(container: ContainerDep, record_id: str, request: TradeEventRequest) -> JournalTrade:
    return _journal(container).append_event(record_id, request)


@router.get("/records/{record_id}/monitor", response_model=MonitoringResult)
def monitor_record(
    container: ContainerDep,
    record_id: str,
    price: Annotated[Decimal | None, Query()] = None,
) -> MonitoringResult:
    return _journal(container).monitor(record_id, price)


@router.post("/setups/{plan_id}/actions")
def record_setup_action(
    container: ContainerDep,
    plan_id: str,
    action: Literal["ACCEPT", "REJECT", "IGNORE"],
    request: SetupActionRequest,
) -> dict:
    from app.trade_journal.contracts import SetupActionType

    return _journal(container).record_setup_action(plan_id, SetupActionType(action), request)


@router.get("/setups/{plan_id}/actions")
def setup_actions(container: ContainerDep, plan_id: str) -> dict:
    return _journal(container).actions(plan_id)


@router.get("/outcomes")
def list_outcomes(
    container: ContainerDep,
    category: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return _outcomes(container).list_outcomes(category=category, limit=limit)


@router.get("/outcomes/{record_id}")
def get_outcome(container: ContainerDep, record_id: str) -> dict:
    return _outcomes(container).get_outcome(record_id).model_dump(mode="json")


@router.post("/outcomes/{record_id}/review", response_model=ReviewEnvelope)
def review_outcome(container: ContainerDep, record_id: str, request: OutcomeReviewRequest) -> ReviewEnvelope:
    review = _outcomes(container).review(record_id, request)
    if review is None:  # pragma: no cover - service always returns or raises
        raise ValidationError("Outcome review failed.")
    return ReviewEnvelope(review=review, outcome=_outcomes(container).get_outcome(record_id))


@router.get("/summary")
def journal_summary(container: ContainerDep) -> dict:
    return _outcomes(container).summary()
