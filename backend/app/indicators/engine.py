"""Deterministic technical indicator calculations.

Calculations use pandas/NumPy and follow standard charting conventions:
- EMA is seeded with the SMA of the first window, then smoothed with 2/(n+1).
- RSI uses Wilder's smoothing seeded with the first 14-period average.
- MACD uses EMA(12) - EMA(26) with an EMA(9) signal line.
- Bollinger Bands use a 20-period SMA with a 2 standard deviation envelope.
- ATR uses Wilder's smoothing over true range, seeded with the first period average.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.market_data.candles import Candle

DEFAULT_PARAMETERS: dict[str, Any] = {
    "ema_fast": 9,
    "ema_mid": 21,
    "ema_slow": 50,
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bb_period": 20,
    "bb_std": 2.0,
    "atr_period": 14,
}


def candles_to_frame(candles: Sequence[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [c.time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "tick_volume": [c.tick_volume for c in candles],
        }
    )


def ema(values: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("EMA period must be positive.")
    array = values.to_numpy(dtype=float)
    result = np.full(len(array), np.nan)
    if len(array) < period:
        return pd.Series(result, index=values.index)
    seed = float(np.nanmean(array[:period]))
    result[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(array)):
        previous = alpha * array[index] + (1.0 - alpha) * previous
        result[index] = previous
    return pd.Series(result, index=values.index)


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0 and avg_gain == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def rsi(values: pd.Series, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("RSI period must be positive.")
    delta = values.diff().to_numpy(dtype=float)
    gains = np.where(np.isnan(delta), np.nan, np.maximum(delta, 0.0))
    losses = np.where(np.isnan(delta), np.nan, np.maximum(-delta, 0.0))
    result = np.full(len(delta), np.nan)
    if len(delta) <= period:
        return pd.Series(result, index=values.index)

    avg_gain = float(np.nanmean(gains[1 : period + 1]))
    avg_loss = float(np.nanmean(losses[1 : period + 1]))
    result[period] = _rsi_value(avg_gain, avg_loss)

    for index in range(period + 1, len(delta)):
        gain = 0.0 if np.isnan(gains[index]) else gains[index]
        loss = 0.0 if np.isnan(losses[index]) else losses[index]
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result[index] = _rsi_value(avg_gain, avg_loss)

    return pd.Series(result, index=values.index)


def macd(
    values: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(values, fast) - ema(values, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger(values: pd.Series, period: int = 20, std_multiplier: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = values.rolling(window=period, min_periods=period).mean()
    deviation = values.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + std_multiplier * deviation
    lower = middle - std_multiplier * deviation
    return upper, middle, lower


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("ATR period must be positive.")
    tr = true_range(frame).to_numpy(dtype=float)
    result = np.full(len(tr), np.nan)
    if len(tr) < period:
        return pd.Series(result, index=frame.index)
    average = float(np.nanmean(tr[:period]))
    result[period - 1] = average
    for index in range(period, len(tr)):
        average = (average * (period - 1) + tr[index]) / period
        result[index] = average
    return pd.Series(result, index=frame.index)


def _series_points(times: Sequence[int], values: pd.Series) -> list[dict[str, float | int]]:
    points: list[dict[str, float | int]] = []
    for time_value, value in zip(times, values.tolist(), strict=True):
        if value is None:
            continue
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            continue
        points.append({"time": int(time_value), "value": round(float(value), 8)})
    return points


def _last_valid(values: pd.Series) -> float | None:
    if values.empty:
        return None
    cleaned = values.dropna()
    if cleaned.empty:
        return None
    return round(float(cleaned.iloc[-1]), 8)


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


@dataclass
class IndicatorBundle:
    ema9: pd.Series
    ema21: pd.Series
    ema50: pd.Series
    rsi14: pd.Series
    macd_line: pd.Series
    macd_signal: pd.Series
    macd_hist: pd.Series
    bb_upper: pd.Series
    bb_middle: pd.Series
    bb_lower: pd.Series
    atr14: pd.Series
    times: list[int] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)

    def latest(self) -> dict[str, float | None]:
        return {
            "ema9": _last_valid(self.ema9),
            "ema21": _last_valid(self.ema21),
            "ema50": _last_valid(self.ema50),
            "rsi14": _last_valid(self.rsi14),
            "macd": _last_valid(self.macd_line),
            "macd_signal": _last_valid(self.macd_signal),
            "macd_histogram": _last_valid(self.macd_hist),
            "bb_upper": _last_valid(self.bb_upper),
            "bb_middle": _last_valid(self.bb_middle),
            "bb_lower": _last_valid(self.bb_lower),
            "atr14": _last_valid(self.atr14),
        }

    def warmup_bars(self) -> int:
        return max(
            int(self.parameters.get("ema_slow", 50)),
            int(self.parameters.get("macd_slow", 26)) + int(self.parameters.get("macd_signal", 9)),
            int(self.parameters.get("bb_period", 20)),
            int(self.parameters.get("atr_period", 14)),
            int(self.parameters.get("rsi_period", 14)),
        )

    def to_payload(self) -> dict[str, Any]:
        digits = 2
        return {
            "series": {
                "ema9": _series_points(self.times, self.ema9.round(digits)),
                "ema21": _series_points(self.times, self.ema21.round(digits)),
                "ema50": _series_points(self.times, self.ema50.round(digits)),
                "bbUpper": _series_points(self.times, self.bb_upper.round(digits)),
                "bbMiddle": _series_points(self.times, self.bb_middle.round(digits)),
                "bbLower": _series_points(self.times, self.bb_lower.round(digits)),
                "rsi14": _series_points(self.times, self.rsi14.round(2)),
                "macd": _series_points(self.times, self.macd_line.round(4)),
                "macdSignal": _series_points(self.times, self.macd_signal.round(4)),
                "macdHistogram": _series_points(self.times, self.macd_hist.round(4)),
                "atr14": _series_points(self.times, self.atr14.round(4)),
            },
            "latest": {key: _round(value) for key, value in self.latest().items()},
            "parameters": self.parameters,
        }


def compute_indicators(candles: Sequence[Candle], parameters: dict[str, Any] | None = None) -> IndicatorBundle:
    params = {**DEFAULT_PARAMETERS, **(parameters or {})}
    frame = candles_to_frame(candles)
    close = frame["close"]
    macd_line, macd_signal, macd_hist = macd(
        close, int(params["macd_fast"]), int(params["macd_slow"]), int(params["macd_signal"])
    )
    bb_upper, bb_middle, bb_lower = bollinger(close, int(params["bb_period"]), float(params["bb_std"]))

    return IndicatorBundle(
        ema9=ema(close, int(params["ema_fast"])),
        ema21=ema(close, int(params["ema_mid"])),
        ema50=ema(close, int(params["ema_slow"])),
        rsi14=rsi(close, int(params["rsi_period"])),
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        atr14=atr(frame, int(params["atr_period"])),
        times=[int(value) for value in frame["time"].tolist()],
        parameters=params,
    )
