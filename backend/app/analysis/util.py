"""Small deterministic helpers shared by the market-intelligence features."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from statistics import median

import pandas as pd

from app.market_data.candles import Candle


def utc_from_epoch(epoch: int | float) -> datetime:
    return datetime.fromtimestamp(float(epoch), UTC)


def candle_ref(candle: Candle) -> str:
    return f"candle:{int(candle.time)}"


def series_value(series: pd.Series, offset: int = 0) -> float | None:
    """Return a finite value at ``len - 1 - offset`` or ``None``.

    ``offset`` is expressed in valid positions from the end, not raw rows, so a
    NaN warm-up value never turns into a fabricated number.
    """

    valid = series.dropna()
    if valid.empty or offset >= len(valid):
        return None
    value = float(valid.iloc[-1 - offset])
    return value if math.isfinite(value) else None


def finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value) if math.isfinite(float(value)) else None


def median_or_none(values: list[float]) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return float(median(clean)) if clean else None


def percent_change(new: float, old: float) -> float | None:
    if old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def closes(candles: list[Candle]) -> list[float]:
    return [float(candle.close) for candle in candles]
