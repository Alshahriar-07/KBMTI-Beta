from __future__ import annotations

import pytest

from app.market_data.candles import clean_candles, mark_forming, raw_to_candle


def row(time: int, open_: float, high: float, low: float, close: float, volume: int = 10) -> dict:
    return {
        "time": time,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "tick_volume": volume,
        "spread": 20,
        "real_volume": 0,
    }


def test_clean_candles_sorts_and_deduplicates() -> None:
    rows = [
        row(300, 10, 12, 9, 11),
        row(100, 8, 9, 7, 8.5),
        row(200, 9, 10, 8, 9.5),
        row(200, 9, 11, 8, 10.5),
    ]
    candles, warnings = clean_candles(rows)
    assert [candle.time for candle in candles] == [100, 200, 300]
    assert candles[1].close == 10.5
    assert any("duplicate" in warning for warning in warnings)


def test_clean_candles_rejects_invalid_ohlc() -> None:
    rows = [
        row(100, 10, 9, 8, 10),  # high below max(open, close)
        row(200, 10, 12, 11, 10),  # low above min(open, close)
        row(300, 10, 12, 8, 11),
        row(400, 0, 0, 0, 0),  # non-positive prices
    ]
    candles, warnings = clean_candles(rows)
    assert [candle.time for candle in candles] == [300]
    assert any("integrity" in warning for warning in warnings)


def test_clean_candles_reports_when_nothing_is_valid() -> None:
    candles, warnings = clean_candles([row(100, 10, 9, 8, 10)])
    assert candles == []
    assert any("No valid candles" in warning for warning in warnings)


def test_raw_to_candle_accepts_sequence_rows() -> None:
    candle = raw_to_candle((1_700_000_000, 1.0, 2.0, 0.5, 1.5, 7, 3, 0))
    assert candle.time == 1_700_000_000
    assert candle.high == 2.0
    assert candle.tick_volume == 7


def test_mark_forming_separates_current_bar() -> None:
    rows = [row(900, 1, 2, 0.5, 1.5), row(1800, 1, 2, 0.5, 1.5)]
    candles, _ = clean_candles(rows)
    completed, forming = mark_forming(candles, 900, reference_epoch=2000)
    assert len(completed) == 1
    assert forming is not None and forming.time == 1800


def test_mark_forming_includes_closed_final_bar() -> None:
    rows = [row(900, 1, 2, 0.5, 1.5), row(1800, 1, 2, 0.5, 1.5)]
    candles, _ = clean_candles(rows)
    completed, forming = mark_forming(candles, 900, reference_epoch=2700)
    assert len(completed) == 2
    assert forming is None


@pytest.mark.parametrize("timeframe_seconds", [60, 300, 900])
def test_mark_forming_respects_timeframe(timeframe_seconds: int) -> None:
    candles, _ = clean_candles([row(1000, 1, 2, 0.5, 1.5)])
    completed, forming = mark_forming(candles, timeframe_seconds, reference_epoch=1000 + timeframe_seconds - 1)
    assert completed == []
    assert forming is not None
