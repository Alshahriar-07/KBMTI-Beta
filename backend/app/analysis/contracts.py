"""Typed contracts for deterministic BTCUSDT M15 market intelligence.

Every feature carries :class:`FeatureMeta` so a persisted snapshot can be traced to
the calculation version and the input series that produced it. The contracts are
frozen: a snapshot is an immutable observation, never a mutable cache entry.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SCOPE_SYMBOL = "BTCUSDT"
SCOPE_TIMEFRAME = "M15"
SCOPE_TIMEFRAME_SECONDS = 900
FEATURE_VERSION = "market-intelligence-1.0.0"
MIN_ANALYSIS_BARS = 100
MAX_ANALYSIS_BARS = 500

TREND_VERSION = "trend-1.0.0"
STRUCTURE_VERSION = "structure-1.0.0"
MOMENTUM_VERSION = "momentum-1.0.0"
VOLATILITY_VERSION = "volatility-1.0.0"
LIQUIDITY_VERSION = "liquidity-1.0.0"
REGIME_VERSION = "regime-1.0.0"


class StrictModel(BaseModel):
    """Reject unknown fields and prevent mutation after construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TrendState(StrEnum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class TrendAlignment(StrEnum):
    BULLISH_STACK = "BULLISH_STACK"
    BEARISH_STACK = "BEARISH_STACK"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class PricePosition(StrEnum):
    ABOVE_ALL = "ABOVE_ALL"
    BELOW_ALL = "BELOW_ALL"
    BETWEEN = "BETWEEN"
    UNKNOWN = "UNKNOWN"


class TrendStrength(StrEnum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class TrendConsistency(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class TrendPhase(StrEnum):
    CONTINUING = "CONTINUING"
    WEAKENING = "WEAKENING"
    REVERSAL_RISK = "REVERSAL_RISK"
    UNKNOWN = "UNKNOWN"


class StructureState(StrEnum):
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    RANGING = "RANGING"
    TRANSITION = "TRANSITION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class StructureEventType(StrEnum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"
    BOS_UP = "BOS_UP"
    BOS_DOWN = "BOS_DOWN"
    CHOCH_UP = "CHOCH_UP"
    CHOCH_DOWN = "CHOCH_DOWN"


class MomentumState(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MomentumPhase(StrEnum):
    ACCELERATING = "ACCELERATING"
    DECELERATING = "DECELERATING"
    STEADY = "STEADY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VolatilityState(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VolatilityPhase(StrEnum):
    EXPANDING = "EXPANDING"
    CONTRACTING = "CONTRACTING"
    STABLE = "STABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RegimeState(StrEnum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ValidationStatus(StrEnum):
    OK = "OK"
    STALE = "STALE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"


class LevelKind(StrEnum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class FeatureMeta(StrictModel):
    version: str
    source: str
    calculated_at: AwareDatetime
    valid: bool = True
    reason: str | None = None


class SnapshotScope(StrictModel):
    symbol: str
    timeframe: str
    supported: bool
    reason: str | None = None


class DataProvenance(StrictModel):
    provider: str
    source: str
    candle_count: int = Field(ge=0)
    first_candle_time: AwareDatetime | None = None
    last_closed_candle_time: AwareDatetime | None = None
    fetched_at: AwareDatetime
    input_hash: str
    timeframe_seconds: int = Field(gt=0)


class ValidationState(StrictModel):
    status: ValidationStatus
    checks: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SwingPoint(StrictModel):
    kind: str
    price: float
    time: AwareDatetime
    index: int = Field(ge=0)
    evidence: list[str] = Field(default_factory=list)


class StructureEvent(StrictModel):
    type: StructureEventType
    price: float
    candle_time: AwareDatetime
    confirmed: bool
    broken_level: float | None = None
    evidence: list[str] = Field(default_factory=list)


class PriceLevel(StrictModel):
    kind: LevelKind
    price: float
    touches: int = Field(ge=1)
    first_time: AwareDatetime
    last_time: AwareDatetime
    source: str
    evidence: list[str] = Field(default_factory=list)


class TrendFeature(StrictModel):
    meta: FeatureMeta
    state: TrendState
    ema9: float | None = None
    ema21: float | None = None
    ema50: float | None = None
    alignment: TrendAlignment
    price_position: PricePosition
    slope_pct_per_bar: float | None = None
    slope_direction: str | None = None
    strength: TrendStrength
    consistency: TrendConsistency
    phase: TrendPhase
    evidence: list[str] = Field(default_factory=list)


class StructureFeature(StrictModel):
    meta: FeatureMeta
    state: StructureState
    swings: list[SwingPoint] = Field(default_factory=list)
    events: list[StructureEvent] = Field(default_factory=list)
    levels: list[PriceLevel] = Field(default_factory=list)
    last_bos: StructureEvent | None = None
    last_choch: StructureEvent | None = None
    evidence: list[str] = Field(default_factory=list)


class MomentumFeature(StrictModel):
    meta: FeatureMeta
    state: MomentumState
    phase: MomentumPhase
    rsi14: float | None = None
    rsi_change: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    macd_histogram_change: float | None = None
    roc_pct: float | None = None
    roc_change_pct: float | None = None
    evidence: list[str] = Field(default_factory=list)


class VolatilityFeature(StrictModel):
    meta: FeatureMeta
    state: VolatilityState
    phase: VolatilityPhase
    atr14: float | None = None
    atr_percent: float | None = None
    atr_percentile: float | None = Field(default=None, ge=0.0, le=1.0)
    realized_vol_percent: float | None = None
    expansion_ratio: float | None = None
    window_bars: int = Field(default=0, ge=0)
    evidence: list[str] = Field(default_factory=list)


class LiquidityPool(StrictModel):
    id: str
    kind: str
    price: float
    touches: int = Field(ge=2)
    side: str
    distance_percent: float
    first_time: AwareDatetime
    last_time: AwareDatetime
    evidence: list[str] = Field(default_factory=list)


class LiquiditySweep(StrictModel):
    id: str
    kind: str
    level: float
    candle_time: AwareDatetime
    confirmation: str
    evidence: list[str] = Field(default_factory=list)


class LiquidityFeature(StrictModel):
    meta: FeatureMeta
    available: bool
    pools: list[LiquidityPool] = Field(default_factory=list)
    sweeps: list[LiquiditySweep] = Field(default_factory=list)
    method_note: str = (
        "Pools are repeated swing levels in closed candles. They are not order-book, "
        "institutional or exchange liquidity data."
    )


class RegimeFeature(StrictModel):
    meta: FeatureMeta
    state: RegimeState
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class MarketSnapshot(StrictModel):
    request_id: str
    snapshot_id: str
    symbol: str
    timeframe: str
    provider: str
    generated_at: AwareDatetime
    data_as_of: AwareDatetime
    is_stale: bool
    feature_version: str
    scope: SnapshotScope
    provenance: DataProvenance
    validation: ValidationState
    warnings: list[str] = Field(default_factory=list)
    last_price: float
    trend: TrendFeature
    structure: StructureFeature
    momentum: MomentumFeature
    volatility: VolatilityFeature
    liquidity: LiquidityFeature
    regime: RegimeFeature


class MarketContextResponse(StrictModel):
    """Compact view for dashboards; the full bundle stays on /market/analysis."""

    request_id: str
    snapshot_id: str
    symbol: str
    timeframe: str
    provider: str
    generated_at: AwareDatetime
    data_as_of: AwareDatetime
    is_stale: bool
    feature_version: str
    scope: SnapshotScope
    provenance: DataProvenance
    validation: ValidationState
    last_price: float
    trend_state: TrendState
    trend_strength: TrendStrength
    structure_state: StructureState
    momentum_state: MomentumState
    momentum_phase: MomentumPhase
    volatility_state: VolatilityState
    volatility_phase: VolatilityPhase
    regime_state: RegimeState
    regime_reasons: list[str] = Field(default_factory=list)
    key_levels: list[PriceLevel] = Field(default_factory=list)
    liquidity_pools: list[LiquidityPool] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def is_supported_scope(symbol: str, timeframe: str) -> bool:
    return symbol.strip().upper() == SCOPE_SYMBOL and timeframe.strip().upper() == SCOPE_TIMEFRAME


def scope_for(symbol: str, timeframe: str) -> SnapshotScope:
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().upper()
    supported = normalized_symbol == SCOPE_SYMBOL and normalized_timeframe == SCOPE_TIMEFRAME
    reason = None
    if not supported:
        reason = (
            f"Phase 1 market intelligence supports {SCOPE_SYMBOL} {SCOPE_TIMEFRAME} only; "
            f"requested {normalized_symbol or '<empty>'} {normalized_timeframe or '<empty>'}."
        )
    return SnapshotScope(
        symbol=normalized_symbol,
        timeframe=normalized_timeframe,
        supported=supported,
        reason=reason,
    )


def utc_timestamp(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime; naive input is rejected upstream."""

    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value
