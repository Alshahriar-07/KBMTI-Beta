"""Typed contract for the unified, Qwen-interpreted market response.

The response is assembled from deterministic services. PATRON's raw forecast is
preserved verbatim as source evidence; Qwen may interpret it but cannot alter a
price, quantile, action or risk decision. The forecast assessment is computed by
deterministic rules and carries no invented confidence score.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.intelligence.contracts import IntelligenceAction, QwenMetadata, StrategyComparison


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ForecastAssessmentStatus(StrEnum):
    VALID = "VALID"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    STALE = "STALE"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class ForecastSourceInfo(StrictModel):
    """Immutable PATRON evidence. Quantiles remain in their original units."""

    provider: Literal["patron"] = "patron"
    model_id: str
    model_version: str
    checkpoint: str | None = None
    checkpoint_sha256: str | None = None
    feature_version: str | None = None
    generated_at: AwareDatetime | None = None
    forecast_as_of: AwareDatetime | None = None
    input_last_bar_at: AwareDatetime | None = None
    horizon_candles: int = Field(default=0, ge=0)
    horizon_minutes: int = Field(default=0, ge=0)
    reference_close: float | None = None
    range_quantiles: list[dict[str, Any]] = Field(default_factory=list)
    predicted_candles: list[dict[str, Any]] = Field(default_factory=list)
    barrier_probabilities: dict[str, float] = Field(default_factory=dict)
    momentum: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    source_hash: str
    freshness_seconds: float | None = None


class ForecastAssessment(StrictModel):
    status: ForecastAssessmentStatus
    reasons: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    usable_in_decision: bool = False
    # Explicitly no numeric confidence score: there is no validated calibration
    # method for one, so only a qualitative status and measured diagnostics exist.
    confidence_score: Literal[None] = None
    freshness_seconds: float | None = None
    interval_width_atr: float | None = None
    barrier_margin: float | None = None
    momentum_margin: float | None = None
    forecast_direction: str | None = None
    deterministic_direction: str | None = None
    # Median path displacement in ATR units. A direction disagreement below
    # ``MATERIAL_DIRECTION_ATR`` is not treated as a material conflict; the raw
    # PATRON direction and this measurement are still reported.
    median_path_atr: float | None = None
    direction_conflict_material: bool | None = None
    horizon_minutes: int | None = None


class ComponentReadiness(StrictModel):
    """Machine-readable state for one pipeline component.

    ``reason_code`` is a stable code (not prose) so the UI and reports can tell why a
    component is unavailable without parsing sentences.
    """

    status: str
    detail: str
    reason_code: str | None = None
    missing_inputs: list[str] = Field(default_factory=list)


class MarketReadiness(ComponentReadiness):
    status: Literal["READY", "STALE", "UNAVAILABLE"]
    data_as_of: AwareDatetime | None = None
    freshness_seconds: float | None = None


class PatronReadiness(ComponentReadiness):
    status: Literal[
        "AVAILABLE", "CONFLICTING", "LOW_CONFIDENCE", "STALE", "INVALID", "UNAVAILABLE"
    ]
    assessment: ForecastAssessmentStatus
    usable_in_decision: bool
    conflicts: list[str] = Field(default_factory=list)
    freshness_seconds: float | None = None
    median_path_atr: float | None = None


class QwenReadiness(ComponentReadiness):
    status: Literal["INITIALIZING", "READY", "FAILED", "DISABLED", "UNAVAILABLE"]
    health_state: str | None = None
    waited_seconds: float | None = None


class StrategyReadiness(ComponentReadiness):
    status: Literal["PENDING", "PASSED", "FAILED"]
    reviewed_cases: int | None = None
    required_cases: int | None = None


class TradePlanReadiness(ComponentReadiness):
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    plan_status: str | None = None


class RiskReadiness(ComponentReadiness):
    status: Literal["APPROVED", "REJECTED", "NOT_EVALUATED"]


class PositionSizeReadiness(ComponentReadiness):
    status: Literal["AVAILABLE", "NOT_CALCULATED"]


class ExecutionReadiness(ComponentReadiness):
    status: Literal["DISABLED"] = "DISABLED"


class PipelineReadiness(StrictModel):
    """One state per component so a single INITIALIZING never hides the real blocker."""

    market: MarketReadiness
    patron: PatronReadiness
    qwen: QwenReadiness
    strategy: StrategyReadiness
    trade_plan: TradePlanReadiness
    risk: RiskReadiness
    position_size: PositionSizeReadiness
    execution: ExecutionReadiness


class MarketCondition(StrictModel):
    trend: str
    trend_strength: str
    trend_alignment: str
    structure: str
    momentum: str
    momentum_phase: str
    volatility: str
    volatility_phase: str
    regime: str
    direction: str
    summary: str


class RiskValidationView(StrictModel):
    status: str
    execution_eligibility: str
    checks: list[dict[str, Any]] = Field(default_factory=list)
    position_size_status: Literal["NOT_CALCULATED"] = "NOT_CALCULATED"
    position_size: None = None


class UnifiedTradePlan(StrictModel):
    plan_id: str
    strategy_id: str
    strategy_version: str
    direction: str
    plan_status: str
    entry_zone: dict[str, str]
    suggested_entry: str
    confirmation_level: str | None = None
    stop_loss: str
    stop_basis: str
    take_profits: list[dict[str, str]] = Field(default_factory=list)
    risk_reward: dict[str, str] = Field(default_factory=dict)
    invalidation_conditions: list[str] = Field(default_factory=list)
    confirmation_requirements: list[str] = Field(default_factory=list)
    expires_at: str
    risk_validation_status: str
    execution_eligibility: str


class ChartLevelView(StrictModel):
    """A verified support, resistance or liquidity level from the snapshot."""

    id: str
    kind: Literal["SUPPORT", "RESISTANCE", "LIQUIDITY"]
    price: float
    label: str
    touches: int | None = None
    time: str | None = None
    detail: str


class ChartMarkerView(StrictModel):
    """A verified swing, structure event or liquidity sweep on the price chart."""

    id: str
    kind: str
    price: float
    time: str
    label: str
    detail: str
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"] = "NEUTRAL"


class ScenarioPoint(StrictModel):
    """A hypothetical point expressed as an offset from the last closed bar."""

    offset_bars: int = Field(ge=1, le=6)
    price: float


class MarketScenario(StrictModel):
    """Conditional path built only from verified levels, never a price forecast."""

    id: Literal[
        "bullish_continuation",
        "bearish_reversal",
        "bearish_continuation",
        "bullish_reversal",
        "sideways_consolidation",
    ]
    title: str
    bias: Literal["BULLISH", "BEARISH", "SIDEWAYS"]
    available: bool
    condition: str
    trigger: float | None = None
    target: float | None = None
    invalidation: float | None = None
    confirmation: str
    invalidation_text: str
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    unavailable_reason: str | None = None
    structure: str = ""
    data_as_of: AwareDatetime | None = None
    data_is_stale: bool = False
    path: list[ScenarioPoint] = Field(default_factory=list)


class ChartOverlay(StrictModel):
    """Deterministic chart annotations; Qwen cannot add or edit these."""

    levels: list[ChartLevelView] = Field(default_factory=list)
    structure: list[ChartMarkerView] = Field(default_factory=list)
    scenarios: list[MarketScenario] = Field(default_factory=list)
    method_note: str = (
        "Levels and markers are computed from closed candles. Scenario paths are "
        "conditional level-to-level sketches, not price predictions."
    )


class MarketIntelligence(StrictModel):
    request_id: str
    generated_at: AwareDatetime
    data_as_of: AwareDatetime
    is_stale: bool
    symbol: str
    timeframe: str

    market_snapshot: dict[str, Any]
    market_condition: MarketCondition
    chart_overlay: ChartOverlay = Field(default_factory=ChartOverlay)
    forecast_source: ForecastSourceInfo | None = None
    forecast_assessment: ForecastAssessment
    ai_market_interpretation: str
    ai_forecast_interpretation: str
    bullish_evidence: list[str] = Field(default_factory=list)
    bearish_evidence: list[str] = Field(default_factory=list)
    strategy_candidates: list[StrategyComparison] = Field(default_factory=list)
    readiness: PipelineReadiness
    decision: IntelligenceAction
    decision_reason: str
    trade_plan: UnifiedTradePlan | None = None
    risk_validation: RiskValidationView
    invalidation_conditions: list[str] = Field(default_factory=list)
    data_freshness: dict[str, Any] = Field(default_factory=dict)
    model_versions: dict[str, str | None] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unavailable_fields: list[str] = Field(default_factory=list)
    ai_status: QwenMetadata

    execution: Literal["DISABLED"] = "DISABLED"
    position_size_status: Literal["NOT_CALCULATED"] = "NOT_CALCULATED"
    position_size: None = None
    disclaimer: str = (
        "Deterministic analysis is authoritative. The strategy gate is PENDING, PATRON "
        "is probabilistic source evidence, Qwen cannot alter numbers or risk, and no "
        "order or position size exists."
    )


class MarketQwenOutput(StrictModel):
    """The only JSON shape accepted from Qwen for the unified response."""

    action: IntelligenceAction
    market_summary: str = Field(min_length=20, max_length=1000)
    forecast_interpretation: str = Field(min_length=10, max_length=900)
    bullish_evidence: list[str] = Field(default_factory=list, max_length=8)
    bearish_evidence: list[str] = Field(default_factory=list, max_length=8)
    uncertainty: str = Field(min_length=10, max_length=700)
    missing_information: list[str] = Field(default_factory=list, max_length=8)
    next_action: str = Field(min_length=4, max_length=400)
    evidence_refs: list[str] = Field(min_length=1, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=10)
