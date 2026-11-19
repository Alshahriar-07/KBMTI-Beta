from __future__ import annotations

from app.core.config import Settings
from app.indicators.engine import compute_indicators
from app.market_data.candles import Candle, clean_candles
from app.signals.engine import BUY_BIAS, NO_CLEAR_SETUP, SELL_BIAS, WAIT, evaluate_signal
from app.signals.service import SignalService
from tests.fake_mt5 import make_candles


def build(count: int = 220, drift: float = 18.0, amplitude: float = 45.0):
    candles, _ = clean_candles(make_candles(count=count, drift=drift, amplitude=amplitude))
    bundle = compute_indicators(candles)
    return candles, bundle


def candles_from_closes(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            time=1_700_000_000 + index * 900,
            open=previous,
            high=max(previous, close) + 8.0,
            low=min(previous, close) - 8.0,
            close=close,
            tick_volume=100 + index % 30,
        )
        for index, (previous, close) in enumerate(zip([closes[0]] + closes[:-1], closes, strict=True))
    ]


def test_uptrend_produces_buy_bias_with_evidence() -> None:
    candles, bundle = build()
    result = evaluate_signal(
        symbol="BTCUSDm",
        timeframe="M15",
        bundle=bundle,
        close=candles[-1].close,
        completed_candle_count=len(candles),
        data_as_of="2026-11-12T00:00:00+00:00",
        freshness="fresh",
    )
    assert result.label == BUY_BIAS
    assert result.direction == "bullish"
    assert result.score >= 0.45
    assert result.supporting
    assert result.invalidation
    assert result.ai_available is False
    assert "not AI" in result.disclaimer


def test_downtrend_produces_sell_bias() -> None:
    closes = [70_000.0 - 0.028 * index**2 for index in range(220)]
    candles = candles_from_closes(closes)
    bundle = compute_indicators(candles)
    result = evaluate_signal(
        symbol="BTCUSDm",
        timeframe="M15",
        bundle=bundle,
        close=candles[-1].close,
        completed_candle_count=len(candles),
        data_as_of=None,
        freshness="fresh",
    )
    assert result.label == SELL_BIAS
    assert result.direction == "bearish"
    assert result.score <= -0.45


def test_stale_data_forces_wait() -> None:
    candles, bundle = build()
    result = evaluate_signal(
        symbol="BTCUSDm",
        timeframe="M15",
        bundle=bundle,
        close=candles[-1].close,
        completed_candle_count=len(candles),
        data_as_of=None,
        freshness="stale",
        stale_reason="No new tick for 300 seconds.",
    )
    assert result.label == WAIT
    assert any("stale" in warning.lower() for warning in result.warnings)
    assert result.invalidation


def test_insufficient_history_returns_no_clear_setup() -> None:
    candles, bundle = build(count=12)
    result = evaluate_signal(
        symbol="BTCUSDm",
        timeframe="M15",
        bundle=bundle,
        close=candles[-1].close,
        completed_candle_count=len(candles),
        data_as_of=None,
        freshness="fresh",
    )
    assert result.label == NO_CLEAR_SETUP
    assert any("warm-up" in warning for warning in result.warnings)
    assert result.supporting == []


def test_flat_market_is_not_a_buy_or_sell_signal() -> None:
    candles, _ = clean_candles(make_candles(count=160, drift=0.0, amplitude=0.0))
    bundle = compute_indicators(candles)
    result = evaluate_signal(
        symbol="BTCUSDm",
        timeframe="M15",
        bundle=bundle,
        close=candles[-1].close,
        completed_candle_count=len(candles),
        data_as_of=None,
        freshness="fresh",
    )
    assert result.label in (WAIT, NO_CLEAR_SETUP)
    assert abs(result.score) < 0.45


class _FakeMarket:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    def status(self):
        return {"selected_symbol": "BTCUSDm"}

    def snapshot(self):
        return {"timeframe": "M15", "spread_points": None}

    def freshness(self):
        return "fresh", None

    def completed_candles(self):
        return list(self.candles)


class _FakeSignalRepository:
    def __init__(self) -> None:
        self.rows = []

    def insert(self, row):
        self.rows.append(row)


def test_signal_cache_invalidates_when_a_new_candle_closes() -> None:
    candles, _ = build()
    market = _FakeMarket(candles)
    service = SignalService(market, _FakeSignalRepository(), Settings())

    first = service.current()
    cached = service.current()
    assert cached is first
    assert first["source_candle_count"] == len(candles)

    last = candles[-1]
    market.candles.append(
        Candle(
            time=last.time + 900,
            open=last.close,
            high=last.close + 25.0,
            low=last.close - 10.0,
            close=last.close + 18.0,
            tick_volume=120,
        )
    )
    refreshed = service.current()
    assert refreshed is not first
    assert refreshed["source_candle_count"] == 221


def test_signal_metrics_are_real_indicator_values() -> None:
    candles, bundle = build()
    result = evaluate_signal(
        symbol="BTCUSDm",
        timeframe="M15",
        bundle=bundle,
        close=candles[-1].close,
        completed_candle_count=len(candles),
        data_as_of=None,
        freshness="fresh",
        spread_points=25,
    )
    latest = bundle.latest()
    assert result.metrics["rsi14"] == latest["rsi14"]
    assert result.metrics["ema21"] == latest["ema21"]
    assert result.metrics["spread_points"] == 25
    assert result.metrics["close"] == candles[-1].close
