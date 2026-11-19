from __future__ import annotations

import math

import pandas as pd
import pytest

from app.indicators.engine import atr, bollinger, candles_to_frame, compute_indicators, ema, macd, rsi
from app.market_data.candles import Candle


def make_candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(time=1_700_000_000 + index * 900, open=close, high=close + 1, low=close - 1, close=close)
        for index, close in enumerate(closes)
    ]


def test_ema_of_constant_series_is_constant() -> None:
    series = pd.Series([5.0] * 30)
    result = ema(series, 9)
    assert result.iloc[:8].isna().all()
    assert result.iloc[-1] == pytest.approx(5.0)


def test_ema_matches_sma_seeded_recursive_definition() -> None:
    values = pd.Series([float(value) for value in range(1, 21)])
    period = 5
    result = ema(values, period)
    alpha = 2 / (period + 1)
    manual = values.iloc[:period].mean()
    assert result.iloc[period - 1] == pytest.approx(manual)
    for value in values.iloc[period:]:
        manual = alpha * value + (1 - alpha) * manual
    assert result.iloc[-1] == pytest.approx(manual, rel=1e-9)


def test_rsi_extremes() -> None:
    rising = pd.Series([float(value) for value in range(1, 60)])
    falling = pd.Series([float(value) for value in range(60, 1, -1)])
    flat = pd.Series([100.0] * 40)

    assert rsi(rising, 14).iloc[-1] == pytest.approx(100.0)
    assert rsi(falling, 14).iloc[-1] == pytest.approx(0.0)
    assert rsi(flat, 14).iloc[-1] == pytest.approx(50.0)


def test_rsi_matches_wilder_reference() -> None:
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    series = pd.Series(closes)
    period = 14
    result = rsi(series, period)
    # The first RSI value appears once 14 deltas are available (index 14).
    assert result.iloc[14] == pytest.approx(70.53, abs=0.1)
    assert result.iloc[:14].isna().all()


def test_bollinger_middle_equals_sma() -> None:
    values = pd.Series([float(value) for value in range(1, 41)])
    upper, middle, lower = bollinger(values, 20, 2.0)
    assert middle.iloc[-1] == pytest.approx(values.iloc[-20:].mean())
    assert upper.iloc[-1] > middle.iloc[-1] > lower.iloc[-1]
    assert (upper.iloc[-1] - middle.iloc[-1]) == pytest.approx(middle.iloc[-1] - lower.iloc[-1])


def test_macd_of_constant_series_is_zero() -> None:
    values = pd.Series([250.0] * 60)
    line, signal, histogram = macd(values)
    assert line.iloc[-1] == pytest.approx(0.0)
    assert signal.iloc[-1] == pytest.approx(0.0)
    assert histogram.iloc[-1] == pytest.approx(0.0)


def test_atr_on_constant_range() -> None:
    closes = [100.0] * 30
    candles = [Candle(time=index * 60, open=100.0, high=101.0, low=99.0, close=100.0) for index in range(30)]
    frame = candles_to_frame(candles)
    result = atr(frame, 14)
    assert result.iloc[-1] == pytest.approx(2.0)
    assert frame["close"].tolist() == closes


def test_compute_indicators_bundle_has_no_nan_points() -> None:
    closes = [100 + 10 * math.sin(index / 5) + index * 0.5 for index in range(120)]
    bundle = compute_indicators(make_candles(closes))
    payload = bundle.to_payload()
    for name, points in payload["series"].items():
        assert points, f"{name} series is empty"
        assert all(point["value"] is not None for point in points)
        assert all(math.isfinite(point["value"]) for point in points)
    assert payload["latest"]["ema9"] is not None
    assert payload["latest"]["rsi14"] is not None
    assert bundle.warmup_bars() >= 50


def test_compute_indicators_handles_short_history() -> None:
    bundle = compute_indicators(make_candles([100.0, 101.0, 102.0]))
    latest = bundle.latest()
    assert latest["ema50"] is None
    assert latest["rsi14"] is None
    assert bundle.to_payload()["series"]["ema9"] == []
