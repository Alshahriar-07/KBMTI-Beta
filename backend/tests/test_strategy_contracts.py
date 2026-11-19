from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.strategies.config import CONFIG_VERSION, STRATEGY_ID, STRATEGY_VERSION
from app.strategies.contracts import StrategyDecision, StrategyDirection, TrendPullbackEvaluation
from app.strategies.trend_pullback import evaluate_trend_pullback
from tests.strategy_fixtures import awaiting_momentum_long, confirmed_long, confirmed_short

FORBIDDEN_ORDER_FIELDS = {
    "entry",
    "entry_price",
    "stop",
    "stop_loss",
    "target",
    "take_profit",
    "leverage",
    "position_size",
    "quantity",
    "risk",
    "risk_percent",
    "order",
    "order_type",
}


@pytest.mark.parametrize("snapshot", [confirmed_long(), confirmed_short(), awaiting_momentum_long()])
def test_evaluation_contract_contains_no_order_fields(snapshot) -> None:  # type: ignore[no-untyped-def]
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    payload = evaluation.model_dump(mode="json")
    assert FORBIDDEN_ORDER_FIELDS.isdisjoint(payload)
    assert FORBIDDEN_ORDER_FIELDS.isdisjoint(evaluation.model_fields)
    assert payload["strategy_id"] == STRATEGY_ID
    assert payload["strategy_version"] == STRATEGY_VERSION
    assert payload["config_version"] == CONFIG_VERSION
    assert payload["market_snapshot_id"] == snapshot.snapshot_id
    assert payload["market_feature_version"] == snapshot.feature_version
    assert payload["symbol"] == "BTCUSDT"
    assert payload["timeframe"] == "M15"
    assert payload["reference_price"] == snapshot.last_price


def test_quality_is_an_explicit_non_probability_score() -> None:
    snapshot = confirmed_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    assert evaluation.quality.is_probability is False
    assert 0 <= evaluation.quality.score <= 100
    assert "probability" in evaluation.quality.basis.lower()
    assert "not a probability" in evaluation.quality.basis.lower()
    assert evaluation.quality.label.value in {"LOW", "MEDIUM", "HIGH"}


def test_non_candidates_have_zero_quality_and_no_direction() -> None:
    snapshot = awaiting_momentum_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    assert evaluation.decision is StrategyDecision.WAIT
    assert evaluation.direction is StrategyDirection.NONE
    assert evaluation.quality.score == 0
    assert evaluation.quality.label.value == "LOW"


def test_evaluation_is_deterministic_for_the_same_snapshot() -> None:
    snapshot = confirmed_long()
    first = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    second = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    assert first.evaluation_id == second.evaluation_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    later = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at + timedelta(minutes=5))
    assert later.evaluation_id == first.evaluation_id
    assert later.valid_until == first.valid_until


def test_candidate_lifetime_is_two_closed_bars_and_wait_is_one() -> None:
    snapshot = confirmed_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    assert evaluation.valid_until == evaluation.data_as_of + timedelta(minutes=30)

    waiting = evaluate_trend_pullback(awaiting_momentum_long(), evaluated_at=snapshot.generated_at)
    assert waiting.valid_until == waiting.data_as_of + timedelta(minutes=15)


def test_contract_is_frozen() -> None:
    evaluation: TrendPullbackEvaluation = evaluate_trend_pullback(confirmed_long())
    with pytest.raises(ValidationError):
        evaluation.decision = StrategyDecision.NO_TRADE  # type: ignore[misc]
