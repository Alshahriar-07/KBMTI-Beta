"""Frozen contracts for deterministic strategy evaluation.

A strategy evaluation is an explanation, not an order. It intentionally contains
no entry, stop-loss, take-profit, leverage or position-size fields; those belong to
the trade-planning and risk phases.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyDecision(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"


class StrategyDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class ConfirmationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class QualityLabel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CheckResult(StrictModel):
    name: str
    passed: bool
    detail: str
    value: float | None = None


class StrategyReason(StrictModel):
    code: str
    message: str
    detail: str | None = None


class StrategyEvidence(StrictModel):
    code: str
    message: str
    refs: list[str] = Field(default_factory=list)
    value: float | None = None
    direction: str | None = None


class EligibilityAssessment(StrictModel):
    eligible: bool
    trend_aligned: bool
    structure_intact: bool
    regime_compatible: bool
    pullback_present: bool
    missing_features: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)


class StrategyQuality(StrictModel):
    """Deterministic checklist score; explicitly not a probability."""

    score: int = Field(ge=0, le=100)
    label: QualityLabel
    basis: str = "Deterministic weighted checklist; not a probability or expected edge."
    is_probability: Literal[False] = False


class TrendPullbackEvaluation(StrictModel):
    evaluation_id: str
    strategy_id: str
    strategy_version: str
    config_version: str
    symbol: str
    timeframe: str
    decision: StrategyDecision
    direction: StrategyDirection
    quality: StrategyQuality
    eligibility: EligibilityAssessment
    confirmation_status: ConfirmationStatus
    reference_price: float
    evidence: list[StrategyEvidence] = Field(default_factory=list)
    rejection_reasons: list[StrategyReason] = Field(default_factory=list)
    wait_reasons: list[StrategyReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    market_snapshot_id: str
    market_feature_version: str
    data_as_of: AwareDatetime
    evaluated_at: AwareDatetime
    valid_until: AwareDatetime


class StrategyCatalogItem(StrictModel):
    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    status: str
    description: str
    implemented: bool


class StrategyCatalogResponse(StrictModel):
    strategies: list[StrategyCatalogItem]
    evaluated_at: AwareDatetime
