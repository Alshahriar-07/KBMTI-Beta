"""Deterministic out-of-sample metrics.

These helpers deliberately accept plain observations. They do not read forecasts,
candles or the database, so the same functions can score PATRON, a strategy or a
walk-forward backtest without sharing mutable state.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ForecastObservations:
    """Matured forecast errors and directional labels for one evaluation window."""

    abs_errors: tuple[float, ...] = ()
    pct_errors: tuple[float, ...] = ()
    direction_correct: tuple[bool, ...] = ()
    in_band: tuple[bool, ...] = ()
    bullish: tuple[bool, ...] = ()
    bearish: tuple[bool, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.abs_errors)
        if len(self.pct_errors) not in {0, n} or len(self.direction_correct) not in {0, n}:
            raise ValueError("forecast observation series must have equal lengths")
        if len(self.in_band) not in {0, n} or len(self.bullish) not in {0, n} or len(self.bearish) not in {0, n}:
            raise ValueError("forecast observation series must have equal lengths")


def _mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _rate(values: Iterable[bool]) -> float | None:
    rows = list(values)
    return sum(1 for row in rows if row) / len(rows) if rows else None


def summarize_observations(observations: ForecastObservations) -> dict[str, object]:
    """Return sample counts plus MAE/MAPE, direction accuracy and band coverage."""

    rows = list(observations.abs_errors)
    n = len(rows)
    return {
        "samples": n,
        "close_mae": round(float(_mean(rows)), 6) if n else None,
        "close_mape": round(float(_mean(observations.pct_errors)), 8) if observations.pct_errors else None,
        "direction_accuracy": round(float(_rate(observations.direction_correct)), 4)
        if observations.direction_correct
        else None,
        "band_coverage": round(float(_rate(observations.in_band)), 4) if observations.in_band else None,
        "bullish_accuracy": round(float(_rate(observations.bullish)), 4) if observations.bullish else None,
        "bearish_accuracy": round(float(_rate(observations.bearish)), 4) if observations.bearish else None,
        "sample_warning": "Fewer than 30 matured observations; accuracy is descriptive, not statistical evidence."
        if 0 < n < 30
        else None,
    }


def direction_probability_from_quantiles(reference: float, quantiles: Iterable[float]) -> float:
    """Estimate P(close > reference) from predicted quantiles.

    A normal approximation is used rather than counting quantiles above the reference:
    the latter is coarse with a small quantile grid and gives 0/1 far too easily. The
    result is a model diagnostic, not a calibrated trading probability.
    """

    values = sorted(float(q) for q in quantiles)
    if not values:
        raise ValueError("at least one quantile is required")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("quantiles must be finite")
    mean = statistics.fmean(values)
    sigma = statistics.pstdev(values) if len(values) > 1 else 0.0
    if sigma <= 1e-12:
        return 1.0 if mean > float(reference) else 0.0 if mean < float(reference) else 0.5
    z = (float(reference) - mean) / sigma
    return 0.5 * (1.0 - math.erf(z / math.sqrt(2.0)))


__all__ = ["ForecastObservations", "direction_probability_from_quantiles", "summarize_observations"]
