"""Deterministic trend analysis from closed candles.

The state is a description of the EMA structure, not a probability. Four binary
conditions are scored (+1 bullish, -1 bearish, 0 unavailable): EMA 9 above EMA 21,
EMA 21 above EMA 50, price above EMA 21, and the EMA 21 slope over five bars.
The net score maps to the published states; no confidence percentage is invented.
"""

from __future__ import annotations

from datetime import datetime

from app.analysis.contracts import (
    TREND_VERSION,
    FeatureMeta,
    PricePosition,
    TrendAlignment,
    TrendConsistency,
    TrendFeature,
    TrendPhase,
    TrendState,
    TrendStrength,
)
from app.analysis.util import candle_ref, series_value
from app.indicators.engine import IndicatorBundle
from app.market_data.candles import Candle

SLOPE_LOOKBACK_BARS = 5
FLAT_SLOPE_PCT = 0.01  # percentage points per bar treated as flat


def _meta(calculated_at: datetime, source: str, *, valid: bool, reason: str | None = None) -> FeatureMeta:
    return FeatureMeta(
        version=TREND_VERSION,
        source=source,
        calculated_at=calculated_at,
        valid=valid,
        reason=reason,
    )


def insufficient_trend(calculated_at: datetime, source: str, reason: str) -> TrendFeature:
    return TrendFeature(
        meta=_meta(calculated_at, source, valid=False, reason=reason),
        state=TrendState.INSUFFICIENT_DATA,
        alignment=TrendAlignment.UNKNOWN,
        price_position=PricePosition.UNKNOWN,
        strength=TrendStrength.UNKNOWN,
        consistency=TrendConsistency.UNKNOWN,
        phase=TrendPhase.UNKNOWN,
    )


def evaluate_trend(
    candles: list[Candle],
    bundle: IndicatorBundle | None,
    *,
    calculated_at: datetime,
    source: str,
) -> TrendFeature:
    if bundle is None or len(candles) < 60:
        return insufficient_trend(
            calculated_at,
            source,
            "At least 60 closed candles are required for the EMA trend read.",
        )

    ema9 = series_value(bundle.ema9)
    ema21 = series_value(bundle.ema21)
    ema50 = series_value(bundle.ema50)
    close = float(candles[-1].close)
    if ema9 is None or ema21 is None or ema50 is None:
        return insufficient_trend(calculated_at, source, "EMA values are not yet available for this series.")

    ema21_five_bars_ago = series_value(bundle.ema21, offset=SLOPE_LOOKBACK_BARS)
    ema21_ten_bars_ago = series_value(bundle.ema21, offset=SLOPE_LOOKBACK_BARS * 2)
    slope = None
    if ema21_five_bars_ago is not None and ema21_five_bars_ago != 0:
        slope = (ema21 - ema21_five_bars_ago) / abs(ema21_five_bars_ago) * 100.0 / SLOPE_LOOKBACK_BARS

    previous_slope = None
    if ema21_five_bars_ago is not None and ema21_ten_bars_ago is not None and ema21_ten_bars_ago != 0:
        previous_slope = (
            (ema21_five_bars_ago - ema21_ten_bars_ago) / abs(ema21_ten_bars_ago) * 100.0 / SLOPE_LOOKBACK_BARS
        )

    if ema9 > ema21 > ema50:
        alignment = TrendAlignment.BULLISH_STACK
    elif ema9 < ema21 < ema50:
        alignment = TrendAlignment.BEARISH_STACK
    else:
        alignment = TrendAlignment.MIXED

    if close > ema9 and close > ema21 and close > ema50:
        price_position = PricePosition.ABOVE_ALL
    elif close < ema9 and close < ema21 and close < ema50:
        price_position = PricePosition.BELOW_ALL
    else:
        price_position = PricePosition.BETWEEN

    score = 0
    components: list[int] = []
    components.append(1 if ema9 > ema21 else -1 if ema9 < ema21 else 0)
    components.append(1 if ema21 > ema50 else -1 if ema21 < ema50 else 0)
    components.append(1 if close > ema21 else -1 if close < ema21 else 0)
    if slope is not None:
        slope_component = 1 if slope > FLAT_SLOPE_PCT else -1 if slope < -FLAT_SLOPE_PCT else 0
        components.append(slope_component)
    score = sum(components)

    if score >= 3:
        state = TrendState.STRONG_BULLISH
    elif score == 2:
        state = TrendState.BULLISH
    elif score <= -3:
        state = TrendState.STRONG_BEARISH
    elif score == -2:
        state = TrendState.BEARISH
    else:
        state = TrendState.NEUTRAL

    if abs(score) >= 3:
        strength = TrendStrength.STRONG
    elif abs(score) == 2:
        strength = TrendStrength.MODERATE
    elif abs(score) == 1:
        strength = TrendStrength.WEAK
    else:
        strength = TrendStrength.NONE

    positives = sum(1 for value in components if value > 0)
    negatives = sum(1 for value in components if value < 0)
    if positives == 0 and negatives == 0:
        consistency = TrendConsistency.UNKNOWN
    elif positives == len(components) or negatives == len(components):
        consistency = TrendConsistency.HIGH
    elif negatives == 0 or positives == 0:
        consistency = TrendConsistency.MEDIUM
    else:
        consistency = TrendConsistency.LOW

    if slope is None or previous_slope is None:
        phase = TrendPhase.UNKNOWN
    elif slope > FLAT_SLOPE_PCT and previous_slope > FLAT_SLOPE_PCT:
        phase = TrendPhase.CONTINUING if slope >= previous_slope else TrendPhase.WEAKENING
    elif slope < -FLAT_SLOPE_PCT and previous_slope < -FLAT_SLOPE_PCT:
        phase = TrendPhase.CONTINUING if slope <= previous_slope else TrendPhase.WEAKENING
    elif (slope > FLAT_SLOPE_PCT and previous_slope < -FLAT_SLOPE_PCT) or (
        slope < -FLAT_SLOPE_PCT and previous_slope > FLAT_SLOPE_PCT
    ):
        phase = TrendPhase.REVERSAL_RISK
    else:
        phase = TrendPhase.UNKNOWN

    slope_direction = "rising" if slope is not None and slope > FLAT_SLOPE_PCT else (
        "falling" if slope is not None and slope < -FLAT_SLOPE_PCT else "flat" if slope is not None else None
    )

    evidence = [
        candle_ref(candles[-1]),
        f"ema_stack:{alignment.value.lower()}",
        f"price_position:{price_position.value.lower()}",
    ]
    if slope_direction:
        evidence.append(f"ema21_slope:{slope_direction}")

    return TrendFeature(
        meta=_meta(calculated_at, source, valid=True),
        state=state,
        ema9=round(ema9, 8),
        ema21=round(ema21, 8),
        ema50=round(ema50, 8),
        alignment=alignment,
        price_position=price_position,
        slope_pct_per_bar=round(slope, 6) if slope is not None else None,
        slope_direction=slope_direction,
        strength=strength,
        consistency=consistency,
        phase=phase,
        evidence=evidence,
    )
