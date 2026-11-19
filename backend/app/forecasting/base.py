"""Forecast provider contract shared by PATRON and any future model.

A provider must perform real inference and must never fabricate candles. The
shipped implementation is `PatronForecastProvider`; no provider may execute
trades.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.timeframes import TIMEFRAME_SECONDS, Timeframe
from app.market_data.candles import Candle

DEFAULT_HORIZON = 5
MAX_HORIZON = 12


@dataclass
class ForecastRequest:
    symbol: str
    timeframe: Timeframe
    candles: Sequence[Candle]
    horizon: int = DEFAULT_HORIZON
    context_limit: int = 512


@dataclass
class ForecastOutput:
    candles: list[Candle]
    provider: str
    model_id: str
    tokenizer_id: str | None
    latency_ms: float
    runtime: str
    input_candle_count: int
    input_last_bar_at: int
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ForecastProvider(Protocol):
    provider_id: str
    model_id: str
    tokenizer_id: str

    def status(self) -> dict[str, Any]: ...

    def run(self, request: ForecastRequest) -> ForecastOutput: ...


def validate_forecast_request(request: ForecastRequest) -> None:
    if not request.candles:
        raise ValueError("Forecast requires at least one completed candle.")
    if not 1 <= request.horizon <= MAX_HORIZON:
        raise ValueError(f"Horizon must be between 1 and {MAX_HORIZON} candles.")
    if request.context_limit <= 0:
        raise ValueError("Context limit must be positive.")
    timestamps = [candle.time for candle in request.candles]
    if timestamps != sorted(timestamps):
        raise ValueError("Input candles must be sorted ascending by time.")
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("Input candles contain duplicate timestamps.")


def validate_forecast_output(output: ForecastOutput, request: ForecastRequest) -> list[str]:
    """Enforce timestamp continuity and OHLC invariants on model output.

    Raises ValueError for structurally unusable forecasts; returns non-fatal warnings.
    """

    warnings: list[str] = []
    expected_count = request.horizon
    if len(output.candles) != expected_count:
        raise ValueError(f"Expected {expected_count} forecast candles, received {len(output.candles)}.")

    step = TIMEFRAME_SECONDS[request.timeframe]
    last_input_time = request.candles[-1].time
    previous = last_input_time
    for index, candle in enumerate(output.candles):
        expected_time = last_input_time + step * (index + 1)
        if candle.time <= previous:
            raise ValueError("Forecast timestamps must strictly increase after the last input candle.")
        if candle.time != expected_time:
            warnings.append(
                f"Forecast candle {index + 1} timestamp is {candle.time}, expected {expected_time}."
            )
        if any(math.isnan(value) or math.isinf(value) or value <= 0 for value in (candle.open, candle.high, candle.low, candle.close)):
            raise ValueError("Forecast candles contain non-positive or non-finite prices.")
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close) or candle.high < candle.low:
            raise ValueError("Forecast candles violate OHLC invariants.")
        previous = candle.time

    return warnings
