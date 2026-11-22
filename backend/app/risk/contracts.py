"""Risk-engine contracts.

Risk validation is deliberately separate from strategy validation and plan
validation. A plan can be geometrically correct while its strategy is unvalidated,
and account-level position sizing is unavailable until verified account inputs exist.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyValidationStatus(StrEnum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class PlanValidationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_EVALUATED = "NOT_EVALUATED"


class RiskValidationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_EVALUATED = "NOT_EVALUATED"


class ExecutionEligibility(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"


class PositionSizeStatus(StrEnum):
    NOT_CALCULATED = "NOT_CALCULATED"


class RiskReason(StrictModel):
    code: str
    message: str
    detail: str | None = None


class RiskCheck(StrictModel):
    name: str
    passed: bool
    blocking: bool = True
    detail: str


class RiskPolicy(StrictModel):
    """Frozen, versioned policy. A value change requires a version bump."""

    policy_version: str = "risk-policy-1.0.0"

    entry_zone_half_width_atr: float = Field(default=0.10, gt=0.0)
    structural_buffer_atr: float = Field(default=0.05, ge=0.0)
    stop_buffer_atr: float = Field(default=0.15, ge=0.0)
    min_stop_distance_atr: float = Field(default=0.10, gt=0.0)
    max_stop_distance_atr: float = Field(default=2.50, gt=0.0)
    entry_tolerance_atr: float = Field(default=0.10, ge=0.0)

    min_rr_tp1: float = Field(default=1.0, gt=0.0)
    tp1_risk_multiple: float = Field(default=1.0, gt=0.0)
    tp2_risk_multiple: float = Field(default=1.5, gt=0.0)
    tp3_risk_multiple: float = Field(default=2.0, gt=0.0)
    min_target_spacing_atr: float = Field(default=0.35, gt=0.0)

    max_plan_bars: int = Field(default=2, ge=1)
    required_confirmation: str = "CONFIRMED"
    price_decimals: int = Field(default=2, ge=0, le=8)
    ratio_decimals: int = Field(default=4, ge=0, le=8)


DEFAULT_RISK_POLICY = RiskPolicy()

MISSING_ACCOUNT_INPUTS: tuple[str, ...] = (
    "account_balance_or_equity",
    "contract_size",
    "tick_value",
    "verified_leverage",
    "fee_model",
)


class RiskReward(StrictModel):
    entry_to_stop: Decimal
    risk_per_unit: Decimal
    tp1_reward: Decimal
    tp2_reward: Decimal
    tp3_reward: Decimal
    rr_tp1: Decimal
    rr_tp2: Decimal
    rr_tp3: Decimal
    stop_distance_atr: float
    tp1_distance_atr: float
    tp2_distance_atr: float
    tp3_distance_atr: float


class RiskAssessment(StrictModel):
    policy_version: str
    validation_status: RiskValidationStatus
    passed: bool
    checks: list[RiskCheck] = Field(default_factory=list)
    reasons: list[RiskReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    risk_reward: RiskReward | None = None
    position_size_status: Literal["NOT_CALCULATED"] = "NOT_CALCULATED"
    position_size: None = None
    missing_account_inputs: list[str] = Field(default_factory=lambda: list(MISSING_ACCOUNT_INPUTS))


class RiskCurrentResponse(StrictModel):
    """Read-only risk view for the latest plan attempt."""

    request_id: str
    plan_id: str | None
    strategy_id: str
    strategy_version: str
    strategy_validation_status: StrategyValidationStatus
    plan_status: str | None
    plan_validation_status: PlanValidationStatus
    risk_validation_status: RiskValidationStatus
    execution_eligibility: ExecutionEligibility
    risk_policy_version: str
    position_size_status: Literal["NOT_CALCULATED"] = "NOT_CALCULATED"
    position_size: None = None
    missing_account_inputs: list[str] = Field(default_factory=lambda: list(MISSING_ACCOUNT_INPUTS))
    assessment: RiskAssessment | None = None
    rejection_reasons: list[RiskReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    market_snapshot_id: str
    strategy_evaluation_id: str
    data_as_of: AwareDatetime
    generated_at: AwareDatetime
