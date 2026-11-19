"""Deterministic volatility analysis.

``atr_percentile`` ranks the current ATR against the previous ATR values in a fixed
window. ``realized_vol_percent`` is the standard deviation of 15-minute log returns,
expressed in percent per bar (not annualised, which would imply a horizon the
15-minute series does not support).
"""

from __future__ import annotations

import math
from datetime import datetime
from statistics import median, pstdev

from app.analysis.contracts import (
    VOLATILITY_VERSION,
    FeatureMeta,
    VolatilityFeature,
    VolatilityPhase,
    VolatilityState,
)
from app.analysis.util import candle_ref, series_value
from app.indicators.engine import IndicatorBundle
from app.market_data.candles import Candle

MIN_VOLATILITY_BARS = 60
ATR_PERCENTILE_WINDOW = 100
REALIZED_VOL_WINDOW = 50
EXPANSION_WINDOW = 20
EXPANSION_THRESHOLD = 1.15
CONTRACTION_THRESHOLD = 0.85


def _meta(calculated_at: datetime, source: str, *, valid: bool, reason: str | None = None) -> FeatureMeta:
    return FeatureMeta(
        version=VOLATILITY_VERSION,
        source=source,
        calculated_at=calculated_at,
        valid=valid,
        reason=reason,
    )


def insufficient_volatility(calculated_at: datetime, source: str, reason: str) -> VolatilityFeature:
    return VolatilityFeature(
        meta=_meta(calculated_at, source, valid=False, reason=reason),
        state=VolatilityState.INSUFFICIENT_DATA,
        phase=VolatilityPhase.INSUFFICIENT_DATA,
    )


def _realized_volatility_percent(candles: list[Candle]) -> float | None:
    window = candles[-(REALIZED_VOL_WINDOW + 1) :]
    if len(window) < REALIZED_VOL_WINDOW + 1:
        return None
    returns: list[float] = []
    for previous, current in zip(window, window[1:]):
        if previous.close <= 0 or current.close <= 0:
            return None
        returns.append(math.log(float(current.close) / float(previous.close)))
    if len(returns) < 2:
        return None
    return pstdev(returns) * 100.0


def evaluate_volatility(
    candles: list[Candle],
    bundle: IndicatorBundle | None,
    *,
    calculated_at: datetime,
    source: str,
) -> VolatilityFeature:
    if bundle is None or len(candles) < MIN_VOLATILITY_BARS:
        return insufficient_volatility(
            calculated_at,
            source,
            f"At least {MIN_VOLATILITY_BARS} closed candles are required for volatility analysis.",
        )

    atr_series = bundle.atr14.dropna()
    if atr_series.empty:
        return insufficient_volatility(calculated_at, source, "ATR is not yet available for this series.")

    atr = series_value(bundle.atr14)
    if atr is None or atr <= 0 or candles[-1].close <= 0:
        return insufficient_volatility(calculated_at, source, "ATR is not a usable positive value.")

    window_values = [float(value) for value in atr_series.iloc[-ATR_PERCENTILE_WINDOW:]]
    percentile = sum(1 for value in window_values if value <= atr) / len(window_values)

    if percentile <= 0.20:
        state = VolatilityState.LOW
    elif percentile < 0.80:
        state = VolatilityState.NORMAL
    elif percentile < 0.95:
        state = VolatilityState.HIGH
    else:
        state = VolatilityState.EXTREME

    previous = window_values[-(EXPANSION_WINDOW + 1) : -1]
    baseline = median(previous) if previous else None
    ratio = atr / baseline if baseline and baseline > 0 else None
    if ratio is None:
        phase = VolatilityPhase.INSUFFICIENT_DATA
    elif ratio >= EXPANSION_THRESHOLD:
        phase = VolatilityPhase.EXPANDING
    elif ratio <= CONTRACTION_THRESHOLD:
        phase = VolatilityPhase.CONTRACTING
    else:
        phase = VolatilityPhase.STABLE

    realized = _realized_volatility_percent(candles)
    atr_percent = atr / float(candles[-1].close) * 100.0

    evidence = [
        candle_ref(candles[-1]),
        f"atr14:{atr:.4f}",
        f"atr_percentile:{percentile:.3f}",
    ]
    return VolatilityFeature(
        meta=_meta(calculated_at, source, valid=True),
        state=state,
        phase=phase,
        atr14=round(atr, 8),
        atr_percent=round(atr_percent, 6),
        atr_percentile=round(percentile, 6),
        realized_vol_percent=round(realized, 6) if realized is not None else None,
        expansion_ratio=round(ratio, 6) if ratio is not None else None,
        window_bars=len(window_values),
        evidence=evidence,
    )
