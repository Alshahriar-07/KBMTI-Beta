from __future__ import annotations

from app.analysis.contracts import LiquiditySweep, StructureEvent, StructureEventType
from app.strategies.contracts import ConfirmationStatus, QualityLabel, StrategyDecision, StrategyDirection
from app.strategies.trend_pullback import evaluate_trend_pullback
from tests.analysis_fixtures import build_snapshot as build_analysis_snapshot
from tests.strategy_fixtures import (
    awaiting_momentum_long,
    confirmed_long,
    confirmed_short,
    extended_long,
    no_trend_long,
    resistance_too_close_long,
    support_too_close_short,
    volatility_incompatible_long,
)


def test_confirmed_long_is_a_structured_candidate() -> None:
    snapshot = confirmed_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.LONG
    assert evaluation.direction is StrategyDirection.LONG
    assert evaluation.confirmation_status is ConfirmationStatus.CONFIRMED
    assert evaluation.quality.label is QualityLabel.HIGH
    assert evaluation.quality.score >= 75
    assert evaluation.rejection_reasons == []
    assert evaluation.wait_reasons == []
    assert evaluation.eligibility.eligible is False  # eligibility is a gate trace, not the decision
    assert evaluation.eligibility.trend_aligned is True
    assert evaluation.eligibility.structure_intact is True
    assert evaluation.eligibility.regime_compatible is True
    assert evaluation.eligibility.pullback_present is True
    assert evaluation.eligibility.missing_features == []
    assert {check.name for check in evaluation.eligibility.checks} == {
        "snapshot_validation",
        "required_features",
        "regime_compatibility",
        "structure_alignment",
        "pullback_location",
        "momentum_health",
        "confirmation",
        "room_to_resistance",
        "liquidity_conflict",
    }
    assert all(check.passed for check in evaluation.eligibility.checks)
    assert [item.code for item in evaluation.evidence] == [
        "MARKET_SNAPSHOT",
        "TREND_ALIGNED",
        "STRUCTURE_STATE",
        "REGIME",
        "PULLBACK_LOCATION",
        "MOMENTUM",
        "CONFIRMATION",
    ]
    assert all(item.message for item in evaluation.evidence)


def test_confirmed_short_mirrors_every_long_rule() -> None:
    snapshot = confirmed_short()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.SHORT
    assert evaluation.direction is StrategyDirection.SHORT
    assert evaluation.confirmation_status is ConfirmationStatus.CONFIRMED
    assert evaluation.quality.label is QualityLabel.HIGH
    assert evaluation.rejection_reasons == []
    assert evaluation.wait_reasons == []
    assert {check.name for check in evaluation.eligibility.checks} >= {
        "room_to_support",
        "liquidity_conflict",
    }


def test_pullback_without_momentum_confirmation_waits() -> None:
    snapshot = awaiting_momentum_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.WAIT
    assert evaluation.direction is StrategyDirection.NONE
    assert evaluation.confirmation_status is ConfirmationStatus.PENDING
    assert evaluation.rejection_reasons == []
    assert [reason.code for reason in evaluation.wait_reasons] == ["AWAITING_MOMENTUM_CONFIRMATION"]
    assert evaluation.eligibility.pullback_present is True
    assert evaluation.quality.score == 0


def test_price_outside_the_pullback_zone_waits() -> None:
    snapshot = extended_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.WAIT
    assert [reason.code for reason in evaluation.wait_reasons] == ["PULLBACK_NOT_PRESENT"]
    assert evaluation.eligibility.pullback_present is False


def test_confirmed_long_without_room_is_rejected() -> None:
    snapshot = resistance_too_close_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert evaluation.direction is StrategyDirection.NONE
    assert evaluation.confirmation_status is ConfirmationStatus.FAILED
    assert [reason.code for reason in evaluation.rejection_reasons] == ["RESISTANCE_TOO_CLOSE"]
    room = next(check for check in evaluation.eligibility.checks if check.name == "room_to_resistance")
    assert room.passed is False
    assert room.value is not None and room.value < 1.0
    assert evaluation.quality.score == 0


def test_confirmed_short_without_room_is_rejected() -> None:
    snapshot = support_too_close_short()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["SUPPORT_TOO_CLOSE"]
    support = next(check for check in evaluation.eligibility.checks if check.name == "room_to_support")
    assert support.passed is False


def test_extreme_volatility_is_rejected() -> None:
    snapshot = volatility_incompatible_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["VOLATILITY_INCOMPATIBLE"]


def test_neutral_trend_has_no_trade_direction() -> None:
    snapshot = no_trend_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert evaluation.direction is StrategyDirection.NONE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["NO_ESTABLISHED_TREND"]
    assert evaluation.confirmation_status is ConfirmationStatus.NOT_APPLICABLE


def test_insufficient_and_invalid_market_data_fail_safe() -> None:
    insufficient = build_analysis_snapshot("insufficient")
    evaluation = evaluate_trend_pullback(insufficient, evaluated_at=insufficient.generated_at)
    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["INSUFFICIENT_DATA"]
    assert evaluation.quality.score == 0

    invalid = build_analysis_snapshot("invalid")
    evaluation = evaluate_trend_pullback(invalid, evaluated_at=invalid.generated_at)
    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["MARKET_DATA_INVALID"]
    assert evaluation.quality.score == 0


def test_missing_required_feature_is_never_defaulted() -> None:
    snapshot = confirmed_long()
    broken = snapshot.model_copy(
        update={"trend": snapshot.trend.model_copy(update={"ema21": None})}
    )
    evaluation = evaluate_trend_pullback(broken, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["FEATURE_UNAVAILABLE"]
    assert "trend.ema21" in evaluation.eligibility.missing_features
    assert evaluation.quality.score == 0


def test_recent_adverse_choch_invalidates_structure() -> None:
    snapshot = confirmed_long()
    event = StructureEvent(
        type=StructureEventType.CHOCH_DOWN,
        price=snapshot.last_price,
        candle_time=snapshot.data_as_of,
        confirmed=True,
    )
    broken = snapshot.model_copy(
        update={
            "structure": snapshot.structure.model_copy(
                update={"events": [*snapshot.structure.events, event]}
            )
        }
    )
    evaluation = evaluate_trend_pullback(broken, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["STRUCTURE_INVALIDATED"]
    assert evaluation.eligibility.structure_intact is False


def test_confirmed_adverse_sweep_near_price_blocks_the_candidate() -> None:
    snapshot = confirmed_long()
    atr = float(snapshot.volatility.atr14 or 0.0)
    sweep = LiquiditySweep(
        id="sweep_fixture_high",
        kind="high",
        level=snapshot.last_price + atr * 0.25,
        candle_time=snapshot.data_as_of,
        confirmation="CONFIRMED",
    )
    conflicted = snapshot.model_copy(
        update={"liquidity": snapshot.liquidity.model_copy(update={"sweeps": [*snapshot.liquidity.sweeps, sweep]})}
    )
    evaluation = evaluate_trend_pullback(conflicted, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["LIQUIDITY_CONFLICT"]
    assert evaluation.confirmation_status is ConfirmationStatus.FAILED


def test_pullback_beyond_the_slow_ema_is_rejected() -> None:
    snapshot = confirmed_long()
    atr = float(snapshot.volatility.atr14 or 0.0)
    too_deep = snapshot.model_copy(update={"last_price": float(snapshot.trend.ema50 or 0.0) - atr * 0.5})
    evaluation = evaluate_trend_pullback(too_deep, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["PULLBACK_TOO_DEEP"]


def test_close_beyond_the_latest_swing_invalidates_the_pullback() -> None:
    snapshot = confirmed_long()
    atr = float(snapshot.volatility.atr14 or 0.0)
    last_low = next(swing for swing in reversed(snapshot.structure.swings) if swing.kind == "low")
    close = last_low.price - atr * 0.1
    # Keep EMA21 below that close so the slow-EMA/deep-pullback guard does not fire first.
    adjusted = snapshot.model_copy(
        update={
            "last_price": close,
            "trend": snapshot.trend.model_copy(update={"ema21": close - atr * 0.5}),
        }
    )
    evaluation = evaluate_trend_pullback(adjusted, evaluated_at=snapshot.generated_at)

    assert evaluation.decision is StrategyDecision.NO_TRADE
    assert [reason.code for reason in evaluation.rejection_reasons] == ["PULLBACK_INVALIDATED"]
    assert evaluation.eligibility.structure_intact is False
