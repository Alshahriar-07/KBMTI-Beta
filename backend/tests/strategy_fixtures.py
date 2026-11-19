"""Deterministic synthetic BTCUSDT M15 fixtures for the Trend Pullback strategy.

Candles are produced by a documented arithmetic cycle instead of committing large
JSON files. Each scenario is exactly reproducible from this source, and the cycle
geometry was tuned so the Phase 1 analyzers resolve to the intended regime,
structure and pullback state.

Trend shape (long; shorts are mirrored):

* 12 cycles of 16 bars up at +12.0 and 4 bars down at -8.0.
* A final tail chosen per scenario (pullback bars are negative, recovery positive).
* High/low wicks are deterministic offsets so swing detection has no ties.

The ``resistance``/``support`` scenarios use a shorter 18-cycle template
(6 bars at +24.0, 3 bars at -13.0, then 4 bars at -26.0 and 3 recovery bars at
+12.0). Its prior swing high/low sits just beyond the last close, which is the
documented reason the room check rejects an otherwise confirmed candidate.

These fixtures are synthetic. They prove rule behavior, not historical edge.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.analysis.context import MarketContextBuilder
from app.analysis.contracts import MarketSnapshot
from app.market_data.candles import Candle

START = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
BAR_SECONDS = 900


def _candles_from_closes(closes: list[float], *, first_step: float, direction: int) -> list[Candle]:
    candles: list[Candle] = []
    previous = closes[0] - first_step * direction
    for index, close in enumerate(closes):
        open_ = previous
        high = max(open_, close) + 5.0 + (index % 3)
        low = min(open_, close) - 4.0 - (index % 2)
        candles.append(
            Candle(
                time=START + index * BAR_SECONDS,
                open=open_,
                high=high,
                low=low,
                close=close,
                tick_volume=100,
                source="binance",
                symbol="BTCUSDT",
            )
        )
        previous = close
    return candles


def build_cycle_candles(direction: int, tail: list[float]) -> list[Candle]:
    """Build a 12-cycle trend followed by an explicit pullback/recovery tail."""

    closes: list[float] = []
    price = 30000.0
    for _ in range(12):
        for _ in range(16):
            price += 12.0 * direction
            closes.append(price)
        for _ in range(4):
            price -= 8.0 * direction
            closes.append(price)
    for step in tail:
        price += step * direction
        closes.append(price)
    return _candles_from_closes(closes, first_step=12.0, direction=direction)


def build_room_candles(direction: int) -> list[Candle]:
    """Build the shorter cycle whose prior swing sits just above/below the close."""

    closes: list[float] = []
    price = 30000.0
    for _ in range(18):
        for _ in range(6):
            price += 24.0 * direction
            closes.append(price)
        for _ in range(3):
            price -= 13.0 * direction
            closes.append(price)
    for _ in range(4):
        price -= 26.0 * direction
        closes.append(price)
    for _ in range(3):
        price += 12.0 * direction
        closes.append(price)
    return _candles_from_closes(closes, first_step=24.0, direction=direction)


def build_snapshot(candles: list[Candle]) -> MarketSnapshot:
    now = datetime.fromtimestamp(int(candles[-1].time) + BAR_SECONDS + 30, UTC)
    return MarketContextBuilder(stale_after_seconds=120.0, clock=lambda: now).build(
        symbol="BTCUSDT",
        timeframe="M15",
        candles=candles,
        provider="binance",
        source="fixture",
        fetched_at=now,
    )


def confirmed_long() -> MarketSnapshot:
    return build_snapshot(build_cycle_candles(1, [-16.0] * 4 + [9.0] * 3))


def confirmed_short() -> MarketSnapshot:
    return build_snapshot(build_cycle_candles(-1, [-16.0] * 4 + [9.0] * 3))


def awaiting_momentum_long() -> MarketSnapshot:
    return build_snapshot(build_cycle_candles(1, [-14.0] * 4 + [9.0, 4.0]))


def extended_long() -> MarketSnapshot:
    return build_snapshot(build_cycle_candles(1, [-14.0] * 4 + [9.0, 9.0, 4.0]))


def no_trend_long() -> MarketSnapshot:
    return build_snapshot(build_cycle_candles(1, [-14.0] * 4 + [6.0]))


def volatility_incompatible_long() -> MarketSnapshot:
    return build_snapshot(build_cycle_candles(1, [-14.0] * 4 + [15.0]))


def resistance_too_close_long() -> MarketSnapshot:
    return build_snapshot(build_room_candles(1))


def support_too_close_short() -> MarketSnapshot:
    return build_snapshot(build_room_candles(-1))
