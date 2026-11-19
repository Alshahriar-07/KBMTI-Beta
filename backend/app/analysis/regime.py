"""Deterministic market-regime classification.

Rules are evaluated in the order below and the first match wins. This ordering is
the published definition of the classifier; changing it requires a version bump.

1. Any core feature is unavailable -> ``INSUFFICIENT_DATA``.
2. The snapshot is stale -> ``UNCERTAIN`` (facts may be shown, but no regime claim).
3. Bullish/strong-bullish trend and an uptrend structure -> ``TRENDING_UP``.
4. Bearish/strong-bearish trend and a downtrend structure -> ``TRENDING_DOWN``.
5. Extreme volatility -> ``HIGH_VOLATILITY``.
6. High volatility without a directional agreement -> ``HIGH_VOLATILITY``.
7. Neutral trend with ranging/transition structure -> ``RANGING``.
8. Anything else (conflicting evidence) -> ``UNCERTAIN``.
"""

from __future__ import annotations

from datetime import datetime

from app.analysis.contracts import (
    REGIME_VERSION,
    FeatureMeta,
    RegimeFeature,
    RegimeState,
    StructureState,
    TrendState,
    VolatilityState,
)


def _meta(calculated_at: datetime, source: str, *, valid: bool, reason: str | None = None) -> FeatureMeta:
    return FeatureMeta(
        version=REGIME_VERSION,
        source=source,
        calculated_at=calculated_at,
        valid=valid,
        reason=reason,
    )


def classify_regime(
    *,
    trend_state: TrendState,
    structure_state: StructureState,
    volatility_state: VolatilityState,
    is_stale: bool,
    insufficient: bool,
    calculated_at: datetime,
    source: str,
    evidence: list[str] | None = None,
) -> RegimeFeature:
    reasons: list[str] = []
    refs = list(evidence or [])

    if insufficient:
        reasons.append("One or more core features are unavailable for this series.")
        return RegimeFeature(
            meta=_meta(calculated_at, source, valid=False, reason=reasons[0]),
            state=RegimeState.INSUFFICIENT_DATA,
            reasons=reasons,
            evidence=refs,
        )

    if is_stale:
        reasons.append("Market data is stale, so no current regime is claimed.")
        return RegimeFeature(
            meta=_meta(calculated_at, source, valid=False, reason=reasons[0]),
            state=RegimeState.UNCERTAIN,
            reasons=reasons,
            evidence=refs,
        )

    bullish_trend = trend_state in {TrendState.BULLISH, TrendState.STRONG_BULLISH}
    bearish_trend = trend_state in {TrendState.BEARISH, TrendState.STRONG_BEARISH}

    if bullish_trend and structure_state is StructureState.UPTREND:
        reasons.append(f"Trend is {trend_state.value} and structure is UPTREND.")
        state = RegimeState.TRENDING_UP
    elif bearish_trend and structure_state is StructureState.DOWNTREND:
        reasons.append(f"Trend is {trend_state.value} and structure is DOWNTREND.")
        state = RegimeState.TRENDING_DOWN
    elif volatility_state is VolatilityState.EXTREME:
        reasons.append("ATR percentile is extreme.")
        state = RegimeState.HIGH_VOLATILITY
    elif volatility_state is VolatilityState.HIGH:
        reasons.append("ATR percentile is high and directional evidence does not agree.")
        state = RegimeState.HIGH_VOLATILITY
    elif trend_state is TrendState.NEUTRAL and structure_state in {
        StructureState.RANGING,
        StructureState.TRANSITION,
    }:
        reasons.append("Trend is neutral and structure is not directional.")
        state = RegimeState.RANGING
    else:
        reasons.append(
            f"Evidence conflicts (trend {trend_state.value}, structure {structure_state.value}, "
            f"volatility {volatility_state.value})."
        )
        state = RegimeState.UNCERTAIN

    return RegimeFeature(
        meta=_meta(calculated_at, source, valid=True),
        state=state,
        reasons=reasons,
        evidence=refs,
    )
