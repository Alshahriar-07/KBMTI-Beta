from __future__ import annotations

import math

import pytest

from app.evaluation import ForecastObservations, add_market_regimes, summarize_observations
from app.evaluation.metrics import direction_probability_from_quantiles


def test_forecast_observations_summary() -> None:
    observations = ForecastObservations(
        abs_errors=(0.1, 0.2, 0.3),
        pct_errors=(0.001, 0.002, 0.003),
        direction_correct=(True, False, True),
        in_band=(True, True, False),
        bullish=(True, False, True),
        bearish=(False, True, False),
    )
    summary = summarize_observations(observations)
    assert summary["samples"] == 3
    assert summary["close_mae"] == pytest.approx(0.2)
    assert summary["direction_accuracy"] == pytest.approx(2 / 3, rel=1e-4)
    assert summary["band_coverage"] == pytest.approx(2 / 3, rel=1e-4)
    assert "Fewer than 30" in str(summary["sample_warning"])


def test_direction_probability_is_bounded_and_centred() -> None:
    assert direction_probability_from_quantiles(100, [90, 100, 110]) == pytest.approx(0.5)
    assert direction_probability_from_quantiles(80, [80, 85, 90]) > 0.5
    assert direction_probability_from_quantiles(100, [80, 85, 90]) < 0.5
    for value in (0.0, 0.25, 0.75, 1.0):
        assert math.isfinite(value)


def test_regimes_do_not_use_future_candles() -> None:
    candles = [
        {"time": i, "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "close": 100.5 + i}
        for i in range(40)
    ]
    rows = add_market_regimes(candles, lookback=5)
    assert rows[0]["regime"] == "INSUFFICIENT_DATA"
    assert rows[-1]["regime"] == "TRENDING_UP"
    assert all(row["atr14"] is not None for row in rows[15:])
    # Mutating a future candle cannot change an earlier label.
    changed = [dict(row) for row in candles]
    changed[-1]["close"] = 10_000.0
    changed[-1]["high"] = 10_001.0
    altered = add_market_regimes(changed, lookback=5)
    assert altered[20]["regime"] == rows[20]["regime"]
