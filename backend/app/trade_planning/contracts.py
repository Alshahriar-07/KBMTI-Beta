"""Typed trade-plan contracts.

A plan is a deterministic description of hypothetical geometry, not an order and
not a fill. ``actual_fill_price`` and ``position_size`` are always null; a real fill
must come from an execution record that does not exist in this phase.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.risk.contracts import (
    ExecutionEligibility,
    PlanValidationStatus,
    RiskAssessment,
    RiskReward,
    RiskValidationStatus,
    StrategyValidationStatus,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanStatus(StrEnum):
    PLAN_READY = "PLAN_READY"
    PLAN_BLOCKED = "PLAN_BLOCKED"
    PLAN_INVALID = "PLAN_INVALID"
    PLAN_EXPIRED = "PLAN_EXPIRED"
    PLAN_REVIEW_REQUIRED = "PLAN_REVIEW_REQUIRED"


class PlanReason(StrictModel):
    code: str
    message: str
    detail: str | None = None


class PlanCheck(StrictModel):
    name: str
    passed: bool
    detail: str


class PlanEvidence(StrictModel):
    code: str
    message: str
    refs: list[str] = Field(default_factory=list)


class EntryZone(StrictModel):
    lower: Decimal
    upper: Decimal
    anchor: Decimal
    anchor_type: str
    half_width_atr: float
    evidence: list[str] = Field(default_factory=list)


class TradeTarget(StrictModel):
    label: Literal["TP1", "TP2", "TP3"]
    price: Decimal
    risk_multiple: Decimal
    atr_distance: float
    method: str
    evidence: list[str] = Field(default_factory=list)
    valid: bool = True


class TradePlan(StrictModel):
    plan_id: str
    plan_version: Literal["1.0.0"] = "1.0.0"

    strategy_id: str
    strategy_version: str
    strategy_config_version: str
    strategy_evaluation_id: str
    strategy_validation_status: StrategyValidationStatus
    strategy_quality_score: int

    market_snapshot_id: str
    market_feature_version: str
    symbol: str
    timeframe: str
    direction: Literal["LONG", "SHORT"]
    reference_price: Decimal

    entry_zone: EntryZone
    suggested_entry: Decimal
    actual_fill_price: None = None
    stop_loss: Decimal
    stop_basis: str
    take_profits: list[TradeTarget] = Field(min_length=3, max_length=3)
    risk_reward: RiskReward

    invalidation_conditions: list[str] = Field(default_factory=list)
    confirmation_requirements: list[str] = Field(default_factory=list)

    plan_status: PlanStatus
    plan_validation_status: PlanValidationStatus
    risk_validation_status: RiskValidationStatus
    execution_eligibility: ExecutionEligibility
    risk_policy_version: str
    risk_assessment: RiskAssessment

    position_size_status: Literal["NOT_CALCULATED"] = "NOT_CALCULATED"
    position_size: None = None
    missing_account_inputs: list[str] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)
    evidence: list[PlanEvidence] = Field(default_factory=list)
    rejection_reasons: list[PlanReason] = Field(default_factory=list)

    data_as_of: AwareDatetime
    created_at: AwareDatetime
    expires_at: AwareDatetime


class TradePlanningResult(StrictModel):
    request_id: str
    status: PlanStatus
    plan: TradePlan | None = None

    strategy_id: str
    strategy_version: str
    strategy_config_version: str
    strategy_evaluation_id: str
    strategy_validation_status: StrategyValidationStatus
    strategy_decision: str

    market_snapshot_id: str
    market_feature_version: str
    symbol: str
    timeframe: str
    direction: str
    reference_price: float

    plan_validation_status: PlanValidationStatus
    risk_validation_status: RiskValidationStatus
    execution_eligibility: ExecutionEligibility
    risk_policy_version: str

    position_size_status: Literal["NOT_CALCULATED"] = "NOT_CALCULATED"
    position_size: None = None
    missing_account_inputs: list[str] = Field(default_factory=list)

    rejection_reasons: list[PlanReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: list[PlanCheck] = Field(default_factory=list)
    evidence: list[PlanEvidence] = Field(default_factory=list)

    data_as_of: AwareDatetime
    expires_at: AwareDatetime
    generated_at: AwareDatetime
    cached: bool = False
