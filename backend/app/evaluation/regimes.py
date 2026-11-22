"""Deterministic regime labels for historical evaluation slices.

The labels depend only on closed candles available at each row. A row's label never
uses a future candle, which is what makes the resulting per-regime metrics usable in
walk-forward evaluation.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any


def _as_float(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    if value is None:
        raise ValueError(f"candle is missing '{key}'")
    return float(value)


def _atr(rows: Sequence[Mapping[str, Any]], end: int, window: int = 14) -> float | None:
    if end + 1 < window + 1:
        return None
    ranges: list[float] = []
    for index in range(end - window + 1, end + 1):
        high = _as_float(rows[index], "high")
        low = _as_float(rows[index], "low")
        previous_close = _as_float(rows[index - 1], "close")
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return statistics.fmean(ranges)


def _regime(rows: Sequence[Mapping[str, Any]], index: int, lookback: int) -> str:
    if index < lookback:
        return "INSUFFICIENT_DATA"
    closes = [_as_float(row, "close") for row in rows[index - lookback : index + 1]]
    start, end = closes[0], closes[-1]
    change_pct = (end - start) / start if start else 0.0
    atr = _atr(rows, index)
    atr_pct = (atr / end) if atr is not None and end else None
    if atr_pct is not None and atr_pct >= 0.02:
        return "HIGH_VOLATILITY"
    if abs(change_pct) >= 0.01:
        return "TRENDING_UP" if change_pct > 0 else "TRENDING_DOWN"
    return "RANGING"


def add_market_regimes(
    candles: Sequence[Mapping[str, Any]],
    *,
    lookback: int = 20,
) -> list[dict[str, Any]]:
    """Return copies of ``candles`` with point-in-time ``regime`` and ``atr14``.

    Existing fields are preserved. The input is never mutated.
    """

    if lookback < 2:
        raise ValueError("lookback must be at least 2")
    result: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        row = dict(candle)
        row["regime"] = _regime(candles, index, lookback)
        atr = _atr(candles, index)
        row["atr14"] = round(atr, 8) if atr is not None else None
        result.append(row)
    return result


__all__ = ["add_market_regimes"]
