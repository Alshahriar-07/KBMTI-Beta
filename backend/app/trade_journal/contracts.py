"""Contracts for the paper/manual trade journal.

No contract contains a position size or an exchange order identifier. A journal record
describes a setup a human accepted and, optionally, a simulated or manually reported
fill; it is never proof that an order was placed.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SetupActionType(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    IGNORE = "IGNORE"


class TradeMode(StrEnum):
    PAPER = "PAPER"
    MANUAL = "MANUAL"


class TradeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TradeEventType(StrEnum):
    ENTRY = "ENTRY"
    NOTE = "NOTE"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    STOP_HIT = "STOP_HIT"
    TP_HIT = "TP_HIT"
    INVALIDATED = "INVALIDATED"
    EXIT = "EXIT"


class OutcomeCategory(StrEnum):
    SUCCESS = "SUCCESS"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    INVALID_SETUP = "INVALID_SETUP"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MonitoringGuidance(StrEnum):
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"
    HOLD = "HOLD"
    TP1_REACHED = "TP1_REACHED"
    INVALIDATED = "INVALIDATED"
    STOP_HIT = "STOP_HIT"
    EXPIRED = "EXPIRED"
    RE_EVALUATE = "RE_EVALUATE"


class SetupAction(StrictModel):
    action_id: str
    plan_id: str
    action: SetupActionType
    actor: str
    note: str | None = None
    created_at: AwareDatetime


class JournalEvent(StrictModel):
    event_id: str
    trade_id: str
    event_type: TradeEventType
    price: Decimal | None = None
    note: str | None = None
    occurred_at: AwareDatetime
    created_at: AwareDatetime


class JournalTrade(StrictModel):
    trade_id: str
    plan_id: str
    mode: TradeMode
    status: TradeStatus
    direction: str
    symbol: str
    timeframe: str
    strategy_id: str
    strategy_version: str
    strategy_validation_status: str
    qwen_model_version: str | None = None

    planned_entry: Decimal
    actual_entry: Decimal | None = None
    stop_loss: Decimal
    tp1: Decimal
    tp2: Decimal
    tp3: Decimal
    exit_price: Decimal | None = None
    fees: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")

    outcome: OutcomeCategory | None = None
    r_multiple: Decimal | None = None
    mfe: Decimal | None = None
    mae: Decimal | None = None

    opened_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    notes: str | None = None
    events: list[JournalEvent] = Field(default_factory=list)

    # The following are informational only and are recalculated by the service.
    position_size_status: str = "NOT_CALCULATED"
    position_size: None = None
    execution: str = "DISABLED"


class TradeCreateRequest(StrictModel):
    plan_id: str
    mode: TradeMode = TradeMode.PAPER
    actual_entry: Decimal | None = None
    fees: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    notes: str | None = None
    actor: str = "local_operator"


class TradeEventRequest(StrictModel):
    event_type: TradeEventType
    price: Decimal | None = None
    note: str | None = None
    occurred_at: AwareDatetime | None = None
    actor: str = "local_operator"


class SetupActionRequest(StrictModel):
    actor: str = "local_operator"
    note: str | None = None


class MonitoringResult(StrictModel):
    trade_id: str
    guidance: MonitoringGuidance
    price: Decimal
    reasons: list[str] = Field(default_factory=list)
    invalidation_triggered: bool = False
    stop_hit: bool = False
    tp1_reached: bool = False
    next_check: str


class OutcomeReviewStatus(StrEnum):
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    APPROVED_FOR_DATASET = "APPROVED_FOR_DATASET"
    EXCLUDED = "EXCLUDED"


class FailureFinding(StrictModel):
    code: str
    message: str
    confidence: str = Field(pattern="^(confirmed|probable|possible|unknown)$")
    evidence_refs: list[str] = Field(default_factory=list)


class OutcomeReview(StrictModel):
    trade_id: str
    status: OutcomeReviewStatus
    reviewer: str
    note: str | None = None
    findings: list[FailureFinding] = Field(default_factory=list)
    dataset_eligible: bool = False
    created_at: AwareDatetime
    updated_at: AwareDatetime


class OutcomeReviewRequest(StrictModel):
    status: OutcomeReviewStatus
    reviewer: str
    note: str | None = None


class TradeOutcome(StrictModel):
    trade_id: str
    category: OutcomeCategory
    r_multiple: Decimal | None = None
    gross_r: Decimal | None = None
    costs_r: Decimal | None = None
    mfe_r: Decimal | None = None
    mae_r: Decimal | None = None
    holding_seconds: int | None = None
    findings: list[FailureFinding] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    sample_warning: str | None = None
