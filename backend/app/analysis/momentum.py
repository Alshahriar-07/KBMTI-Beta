"""Deterministic momentum analysis built on the existing indicator engine.

Momentum divergence is intentionally not emitted in Phase 1: a reliable detector
needs objective pivot pairing and confirmation rules that are not yet specified.
It is reported as deferred rather than guessed.
"""

from __future__ import annotations

from datetime import datetime

from app.analysis.contracts import (
    MOMENTUM_VERSION,
    FeatureMeta,
    MomentumFeature,
    MomentumPhase,
    MomentumState,
)
from app.analysis.util import candle_ref, series_value
from app.indicators.engine import IndicatorBundle
from app.market_data.candles import Candle

MIN_MOMENTUM_BARS = 60
CHANGE_LOOKBACK_BARS = 3
ROC_BARS = 10
ACCELERATION_THRESHOLD_PCT = 0.05


def _meta(calculated_at: datetime, source: str, *, valid: bool, reason: str | None = None) -> FeatureMeta:
    return FeatureMeta(
        version=MOMENTUM_VERSION,
        source=source,
        calculated_at=calculated_at,
        valid=valid,
        reason=reason,
    )


def insufficient_momentum(calculated_at: datetime, source: str, reason: str) -> MomentumFeature:
    return MomentumFeature(
        meta=_meta(calculated_at, source, valid=False, reason=reason),
        state=MomentumState.INSUFFICIENT_DATA,
        phase=MomentumPhase.INSUFFICIENT_DATA,
    )


def _roc(candles: list[Candle], offset: int = 0) -> float | None:
    end_index = len(candles) - 1 - offset
    start_index = end_index - ROC_BARS
    if start_index < 0:
        return None
    start = float(candles[start_index].close)
    end = float(candles[end_index].close)
    if start == 0:
        return None
    return (end - start) / start * 100.0


def evaluate_momentum(
    candles: list[Candle],
    bundle: IndicatorBundle | None,
    *,
    calculated_at: datetime,
    source: str,
) -> MomentumFeature:
    if bundle is None or len(candles) < MIN_MOMENTUM_BARS:
        return insufficient_momentum(
            calculated_at,
            source,
            f"At least {MIN_MOMENTUM_BARS} closed candles are required for momentum analysis.",
        )

    rsi = series_value(bundle.rsi14)
    rsi_previous = series_value(bundle.rsi14, offset=CHANGE_LOOKBACK_BARS)
    macd = series_value(bundle.macd_line)
    signal = series_value(bundle.macd_signal)
    histogram = series_value(bundle.macd_hist)
    histogram_previous = series_value(bundle.macd_hist, offset=CHANGE_LOOKBACK_BARS)

    if rsi is None or macd is None or signal is None or histogram is None:
        return insufficient_momentum(calculated_at, source, "Indicator values are not yet available for momentum.")

    roc = _roc(candles)
    roc_previous = _roc(candles, offset=5)

    votes = {
        "rsi": 1 if rsi >= 55 else -1 if rsi <= 45 else 0,
        "macd_histogram": 1 if histogram > 0 else -1 if histogram < 0 else 0,
        "macd_line": 1 if macd > signal else -1 if macd < signal else 0,
        "roc": 1 if roc is not None and roc > 0 else -1 if roc is not None and roc < 0 else 0,
    }
    net = sum(votes.values())
    has_bullish = any(value > 0 for value in votes.values())
    has_bearish = any(value < 0 for value in votes.values())

    if net >= 2:
        state = MomentumState.BULLISH
    elif net <= -2:
        state = MomentumState.BEARISH
    elif has_bullish and has_bearish:
        state = MomentumState.MIXED
    else:
        state = MomentumState.NEUTRAL

    if roc is None or roc_previous is None:
        phase = MomentumPhase.INSUFFICIENT_DATA
        roc_change = None
    else:
        roc_change = roc - roc_previous
        if roc_change > ACCELERATION_THRESHOLD_PCT:
            phase = MomentumPhase.ACCELERATING
        elif roc_change < -ACCELERATION_THRESHOLD_PCT:
            phase = MomentumPhase.DECELERATING
        else:
            phase = MomentumPhase.STEADY

    evidence = [candle_ref(candles[-1]), f"rsi14:{rsi:.2f}", f"macd_histogram:{histogram:.6f}"]
    if roc is not None:
        evidence.append(f"roc10:{roc:.4f}")

    return MomentumFeature(
        meta=_meta(calculated_at, source, valid=True),
        state=state,
        phase=phase,
        rsi14=round(rsi, 4),
        rsi_change=round(rsi - rsi_previous, 4) if rsi_previous is not None else None,
        macd=round(macd, 8),
        macd_signal=round(signal, 8),
        macd_histogram=round(histogram, 8),
        macd_histogram_change=round(histogram - histogram_previous, 8)
        if histogram_previous is not None
        else None,
        roc_pct=round(roc, 4) if roc is not None else None,
        roc_change_pct=round(roc_change, 4) if roc_change is not None else None,
        evidence=evidence,
    )
