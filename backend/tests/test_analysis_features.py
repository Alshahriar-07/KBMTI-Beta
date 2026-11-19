from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.analysis.context import MarketContextBuilder
from app.analysis.contracts import (
    FEATURE_VERSION,
    MarketSnapshot,
    MomentumState,
    RegimeState,
    StructureEventType,
    StructureState,
    TrendAlignment,
    TrendState,
    ValidationStatus,
    VolatilityState,
    scope_for,
)
from app.core.errors import UnsupportedScopeError
from tests.analysis_fixtures import build_snapshot, fixture_candles, fixture_now


def test_scope_requires_btcusdt_m15() -> None:
    assert scope_for("btcusdt", "m15").supported is True
    unsupported = scope_for("ETHUSDT", "M15")
    assert unsupported.supported is False
    assert "BTCUSDT M15" in (unsupported.reason or "")
    assert scope_for("BTCUSDT", "H1").supported is False


def test_builder_rejects_unsupported_scope() -> None:
    now = fixture_now("uptrend")
    builder = MarketContextBuilder(stale_after_seconds=120, clock=lambda: now)
    with pytest.raises(UnsupportedScopeError) as excinfo:
        builder.build(
            symbol="ETHUSDT",
            timeframe="M15",
            candles=fixture_candles("uptrend"),
            provider="binance",
            source="fixture",
            fetched_at=now,
        )
    assert excinfo.value.code == "UNSUPPORTED_SCOPE"


def test_snapshot_round_trips_and_carries_versions() -> None:
    snapshot = build_snapshot("uptrend")
    restored = MarketSnapshot.model_validate(snapshot.model_dump(mode="json"))
    assert restored.snapshot_id == snapshot.snapshot_id
    assert restored.feature_version == FEATURE_VERSION
    for feature in (
        snapshot.trend,
        snapshot.structure,
        snapshot.momentum,
        snapshot.volatility,
        snapshot.liquidity,
        snapshot.regime,
    ):
        assert feature.meta.version
        assert feature.meta.source == "binance:BTCUSDT:M15:closed"
        assert feature.meta.calculated_at.tzinfo is not None


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MarketSnapshot.model_validate(
            {
                **build_snapshot("uptrend").model_dump(mode="json"),
                "generated_at": "2026-10-21T00:00:00",
            }
        )


def test_strong_uptrend_is_described_by_trend_and_structure() -> None:
    snapshot = build_snapshot("uptrend")
    assert snapshot.trend.state in {TrendState.BULLISH, TrendState.STRONG_BULLISH}
    assert snapshot.trend.alignment is TrendAlignment.BULLISH_STACK
    assert snapshot.structure.state is StructureState.UPTREND
    kinds = {event.type for event in snapshot.structure.events}
    assert StructureEventType.HH in kinds
    assert StructureEventType.HL in kinds
    assert StructureEventType.BOS_UP in kinds
    assert snapshot.structure.last_bos is not None
    assert snapshot.trend.meta.valid is True


def test_strong_downtrend_is_described_by_trend_and_structure() -> None:
    snapshot = build_snapshot("downtrend")
    assert snapshot.trend.state in {TrendState.BEARISH, TrendState.STRONG_BEARISH}
    assert snapshot.structure.state is StructureState.DOWNTREND
    kinds = {event.type for event in snapshot.structure.events}
    assert StructureEventType.BOS_DOWN in kinds
    assert snapshot.structure.last_bos is not None


def test_sideways_market_is_ranging_and_neutral() -> None:
    snapshot = build_snapshot("sideways")
    assert snapshot.trend.state is TrendState.NEUTRAL
    assert snapshot.structure.state is StructureState.RANGING
    assert snapshot.regime.state is RegimeState.RANGING


def test_breakout_produces_close_confirmed_bos() -> None:
    snapshot = build_snapshot("breakout")
    bos = [event for event in snapshot.structure.events if event.type is StructureEventType.BOS_UP]
    assert bos, "the breakout fixture must contain a confirmed BOS_UP"
    for event in bos:
        assert event.confirmed is True
        assert event.broken_level is not None
        assert event.price > event.broken_level


def test_reversal_produces_choch_down() -> None:
    snapshot = build_snapshot("reversal")
    assert snapshot.structure.last_choch is not None
    assert snapshot.structure.last_choch.type is StructureEventType.CHOCH_DOWN
    assert snapshot.structure.last_choch.confirmed is True


def test_momentum_alignment_follows_the_fixture_direction() -> None:
    down = build_snapshot("downtrend")
    assert down.momentum.state in {MomentumState.BEARISH, MomentumState.MIXED}
    assert down.momentum.rsi14 is not None and down.momentum.macd_histogram is not None

    up = build_snapshot("liquidity")
    assert up.momentum.state is MomentumState.BULLISH


def test_volatility_states_use_atr_percentile() -> None:
    high = build_snapshot("high_volatility")
    assert high.volatility.state in {VolatilityState.HIGH, VolatilityState.EXTREME}
    assert high.volatility.atr_percentile is not None and high.volatility.atr_percentile >= 0.8

    low = build_snapshot("low_volatility")
    assert low.volatility.state is VolatilityState.LOW
    assert low.volatility.atr_percentile is not None and low.volatility.atr_percentile <= 0.2
    assert low.volatility.phase is not None


def test_regimes_follow_the_documented_rule_order() -> None:
    assert build_snapshot("uptrend").regime.state is RegimeState.TRENDING_UP
    assert build_snapshot("downtrend").regime.state is RegimeState.TRENDING_DOWN
    assert build_snapshot("high_volatility").regime.state is RegimeState.HIGH_VOLATILITY


def test_liquidity_pools_and_confirmed_sweep() -> None:
    snapshot = build_snapshot("liquidity")
    assert snapshot.liquidity.available is True
    kinds = {pool.kind for pool in snapshot.liquidity.pools}
    assert kinds == {"high", "low"}
    sweeps = [sweep for sweep in snapshot.liquidity.sweeps if sweep.kind == "high"]
    assert sweeps and sweeps[-1].confirmation == "CONFIRMED"


def test_insufficient_warmup_degrades_every_feature() -> None:
    snapshot = build_snapshot("insufficient")
    assert snapshot.validation.status is ValidationStatus.INSUFFICIENT_DATA
    assert snapshot.trend.state is TrendState.INSUFFICIENT_DATA
    assert snapshot.structure.state is StructureState.INSUFFICIENT_DATA
    assert snapshot.momentum.state is MomentumState.INSUFFICIENT_DATA
    assert snapshot.volatility.state is VolatilityState.INSUFFICIENT_DATA
    assert snapshot.regime.state is RegimeState.INSUFFICIENT_DATA
    assert snapshot.liquidity.available is False
    assert any("100" in warning for warning in snapshot.warnings)


def test_invalid_ohlcv_is_rejected_not_repaired() -> None:
    snapshot = build_snapshot("invalid")
    assert snapshot.validation.status is ValidationStatus.INVALID
    assert snapshot.validation.errors
    assert snapshot.trend.meta.valid is False
    assert snapshot.regime.state is RegimeState.INSUFFICIENT_DATA


def test_stale_data_is_marked_and_regime_is_uncertain() -> None:
    now = fixture_now("uptrend") + timedelta(hours=2)
    snapshot = build_snapshot("uptrend", now=now)
    assert snapshot.is_stale is True
    assert snapshot.validation.status is ValidationStatus.STALE
    assert snapshot.regime.state is RegimeState.UNCERTAIN
    assert any("stale" in warning.lower() for warning in snapshot.warnings)


def test_future_and_forming_candles_are_excluded() -> None:
    snapshot = build_snapshot("future_forming", exclude_last=2)
    assert snapshot.provenance.candle_count == 140
    assert snapshot.provenance.last_closed_candle_time <= snapshot.generated_at
    assert any("excluded" in warning for warning in snapshot.warnings)


def test_future_candles_cannot_change_a_snapshot() -> None:
    now = fixture_now("uptrend")
    base = fixture_candles("uptrend")
    extended = base + [
        replace(base[-1], time=base[-1].time + 900),
        replace(base[-1], time=base[-1].time + 1800),
    ]
    builder = MarketContextBuilder(stale_after_seconds=120, clock=lambda: now)
    without_future = builder.build(
        symbol="BTCUSDT",
        timeframe="M15",
        candles=base,
        provider="binance",
        source="fixture",
        fetched_at=now,
    )
    with_future = builder.build(
        symbol="BTCUSDT",
        timeframe="M15",
        candles=extended,
        provider="binance",
        source="fixture",
        fetched_at=now,
    )
    assert with_future.snapshot_id == without_future.snapshot_id
    assert with_future.provenance.input_hash == without_future.provenance.input_hash
    assert with_future.provenance.candle_count == without_future.provenance.candle_count


def test_snapshot_is_deterministic_but_request_ids_differ() -> None:
    first = build_snapshot("sideways")
    second = build_snapshot("sideways")
    assert first.snapshot_id == second.snapshot_id
    assert first.request_id != second.request_id
    assert first.trend.model_dump() == second.trend.model_dump()
    assert first.regime.model_dump() == second.regime.model_dump()
