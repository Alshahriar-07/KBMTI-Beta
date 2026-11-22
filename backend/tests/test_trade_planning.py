from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.analysis.contracts import ValidationStatus
from app.analysis.service import AnalysisService
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.persistence.db import Database
from app.persistence.repositories import (
    MarketSnapshotRepository,
    StrategyEvaluationRepository,
    TradePlanRepository,
)
from app.risk.contracts import PlanValidationStatus, RiskPolicy, RiskValidationStatus, StrategyValidationStatus
from app.risk.engine import assess_risk, execution_eligibility
from app.risk.service import RiskService
from app.strategies.service import StrategyService
from app.strategies.trend_pullback import evaluate_trend_pullback
from app.trade_planning.contracts import PlanStatus
from app.trade_planning.planner import build_geometry
from app.trade_planning.service import TradePlanningService
from tests.analysis_fixtures import StaticCandleSource
from tests.strategy_fixtures import build_cycle_candles, confirmed_long, confirmed_short

LONG_TAIL = [-16.0] * 4 + [9.0] * 3
SHORT_TAIL = LONG_TAIL


def _stack(settings: Settings, candles, *, clock=None, policy=None):
    now = clock or datetime.fromtimestamp(int(candles[-1].time) + 930, UTC)
    database = Database(settings.db_path)
    database.initialize()
    analysis = AnalysisService(
        source=StaticCandleSource(candles),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: now,
        cache_seconds=0.0,
    )
    strategies = StrategyService(
        analysis=analysis,
        repository=StrategyEvaluationRepository(database),
        clock=lambda: now,
    )
    risk = RiskService(policy=policy or RiskPolicy(), clock=lambda: now)
    planning = TradePlanningService(
        analysis=analysis,
        strategies=strategies,
        risk=risk,
        repository=TradePlanRepository(database),
        clock=lambda: now,
    )
    return database, planning, analysis


def _geometry(snapshot=None, **policy_overrides):
    snapshot = snapshot or confirmed_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    policy = RiskPolicy(**policy_overrides)
    result = build_geometry(evaluation=evaluation, snapshot=snapshot, policy=policy)
    assert result.geometry is not None, result.reasons
    return snapshot, evaluation, policy, result.geometry


def test_long_plan_geometry_is_deterministic_and_ordered() -> None:
    snapshot, evaluation, _, geometry = _geometry()

    assert geometry.direction.value == "LONG"
    assert geometry.entry_zone.lower < geometry.entry_zone.upper
    assert geometry.entry_zone.lower <= geometry.suggested_entry <= geometry.entry_zone.upper
    assert geometry.stop_loss < geometry.suggested_entry
    assert geometry.targets[0].price < geometry.targets[1].price < geometry.targets[2].price
    assert all(target.price > geometry.suggested_entry for target in geometry.targets)
    assert all(isinstance(target.price, Decimal) for target in geometry.targets)
    assert geometry.risk_per_unit == geometry.suggested_entry - geometry.stop_loss
    assert [target.label for target in geometry.targets] == ["TP1", "TP2", "TP3"]

    swing_low = next(swing for swing in reversed(snapshot.structure.swings) if swing.kind == "low")
    expected_stop = (Decimal(str(swing_low.price)) - Decimal("0.15") * geometry.atr).quantize(Decimal("0.01"))
    assert geometry.stop_loss == expected_stop
    assert evaluation.direction.value == geometry.direction.value


def test_short_plan_geometry_mirrors_long_rules() -> None:
    snapshot, evaluation, _, geometry = _geometry(confirmed_short())

    assert geometry.direction.value == "SHORT"
    assert geometry.entry_zone.lower <= geometry.suggested_entry <= geometry.entry_zone.upper
    assert geometry.stop_loss > geometry.suggested_entry
    assert geometry.targets[0].price > geometry.targets[1].price > geometry.targets[2].price
    assert all(target.price < geometry.suggested_entry for target in geometry.targets)
    assert geometry.risk_per_unit == geometry.stop_loss - geometry.suggested_entry

    swing_high = next(swing for swing in reversed(snapshot.structure.swings) if swing.kind == "high")
    expected_stop = (Decimal(str(swing_high.price)) + Decimal("0.15") * geometry.atr).quantize(Decimal("0.01"))
    assert geometry.stop_loss == expected_stop
    assert evaluation.direction.value == geometry.direction.value


def test_missing_swing_rejects_geometry() -> None:
    snapshot = confirmed_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    without_lows = snapshot.model_copy(
        update={
            "structure": snapshot.structure.model_copy(
                update={"swings": [swing for swing in snapshot.structure.swings if swing.kind != "low"]}
            )
        }
    )
    result = build_geometry(evaluation=evaluation, snapshot=without_lows)

    assert result.geometry is None
    assert [reason.code for reason in result.reasons] == ["MISSING_STRUCTURAL_LEVEL"]


def test_collapsed_entry_zone_is_rejected() -> None:
    snapshot = confirmed_long()
    evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)
    atr = float(snapshot.volatility.atr14 or 0)
    shifted = snapshot.model_copy(
        update={"trend": snapshot.trend.model_copy(update={"ema21": snapshot.last_price + atr * 5})}
    )
    result = build_geometry(evaluation=evaluation, snapshot=shifted)

    assert result.geometry is None
    assert [reason.code for reason in result.reasons] == ["INVALID_ENTRY_GEOMETRY"]


def test_risk_reward_precision_and_unvalidated_provenance() -> None:
    snapshot, evaluation, policy, geometry = _geometry()
    assessment = assess_risk(
        direction=geometry.direction,
        entry=geometry.suggested_entry,
        stop=geometry.stop_loss,
        targets=[target.price for target in geometry.targets],
        target_conflict=geometry.target_conflict,
        atr=geometry.atr,
        snapshot=snapshot,
        evaluation=evaluation,
        strategy_status=StrategyValidationStatus.PENDING,
        policy=policy,
    )

    assert assessment.passed is True
    assert assessment.validation_status is RiskValidationStatus.VALID
    assert assessment.risk_reward is not None
    assert assessment.risk_reward.rr_tp1 >= Decimal("1.0000")
    assert assessment.risk_reward.rr_tp2 > assessment.risk_reward.rr_tp1
    assert assessment.position_size_status == "NOT_CALCULATED"
    assert assessment.position_size is None
    assert "account_balance_or_equity" in assessment.missing_account_inputs
    strategy_check = next(check for check in assessment.checks if check.name == "strategy_validation")
    assert strategy_check.passed is False and strategy_check.blocking is False
    assert any("PENDING" in warning for warning in assessment.warnings)


def test_excessive_stop_distance_blocks_risk() -> None:
    snapshot, evaluation, _, geometry = _geometry()
    result = assess_risk(
        direction=geometry.direction,
        entry=geometry.suggested_entry,
        stop=geometry.stop_loss,
        targets=[target.price for target in geometry.targets],
        target_conflict=False,
        atr=geometry.atr,
        snapshot=snapshot,
        evaluation=evaluation,
        policy=RiskPolicy(max_stop_distance_atr=0.5),
    )

    assert result.passed is False
    assert "STOP_DISTANCE_EXCEEDED" in [reason.code for reason in result.reasons]


def test_insufficient_risk_reward_is_rejected() -> None:
    snapshot, evaluation, policy, geometry = _geometry()
    risk = geometry.risk_per_unit
    targets = [
        geometry.suggested_entry + risk * Decimal("0.5"),
        geometry.suggested_entry + risk * Decimal("1.5"),
        geometry.suggested_entry + risk * Decimal("2.0"),
    ]
    result = assess_risk(
        direction=geometry.direction,
        entry=geometry.suggested_entry,
        stop=geometry.stop_loss,
        targets=targets,
        target_conflict=False,
        atr=geometry.atr,
        snapshot=snapshot,
        evaluation=evaluation,
        policy=policy,
    )

    assert result.validation_status is RiskValidationStatus.INVALID
    assert "INSUFFICIENT_RISK_REWARD" in [reason.code for reason in result.reasons]


def test_target_structure_conflict_blocks_plan() -> None:
    snapshot, evaluation, _, geometry = _geometry(min_rr_tp1=10.0, tp1_risk_multiple=10.0)
    result = assess_risk(
        direction=geometry.direction,
        entry=geometry.suggested_entry,
        stop=geometry.stop_loss,
        targets=[target.price for target in geometry.targets],
        target_conflict=geometry.target_conflict,
        atr=geometry.atr,
        snapshot=snapshot,
        evaluation=evaluation,
        policy=RiskPolicy(min_rr_tp1=10.0, tp1_risk_multiple=10.0),
    )

    assert geometry.target_conflict is True
    assert result.passed is False
    assert "TARGET_STRUCTURE_CONFLICT" in [reason.code for reason in result.reasons]


def test_stale_and_invalid_snapshots_are_rejected() -> None:
    snapshot, evaluation, policy, geometry = _geometry()
    stale = snapshot.model_copy(update={"is_stale": True})
    stale_result = assess_risk(
        direction=geometry.direction, entry=geometry.suggested_entry, stop=geometry.stop_loss,
        targets=[target.price for target in geometry.targets], target_conflict=False, atr=geometry.atr,
        snapshot=stale, evaluation=evaluation, policy=policy,
    )
    assert "MARKET_DATA_STALE" in [reason.code for reason in stale_result.reasons]

    invalid = snapshot.model_copy(
        update={"validation": snapshot.validation.model_copy(update={"status": ValidationStatus.INVALID})}
    )
    invalid_result = assess_risk(
        direction=geometry.direction, entry=geometry.suggested_entry, stop=geometry.stop_loss,
        targets=[target.price for target in geometry.targets], target_conflict=False, atr=geometry.atr,
        snapshot=invalid, evaluation=evaluation, policy=policy,
    )
    assert "MARKET_DATA_INVALID" in [reason.code for reason in invalid_result.reasons]


def test_unordered_targets_are_rejected() -> None:
    snapshot, evaluation, policy, geometry = _geometry()
    unordered = [geometry.targets[1].price, geometry.targets[0].price, geometry.targets[2].price]
    result = assess_risk(
        direction=geometry.direction, entry=geometry.suggested_entry, stop=geometry.stop_loss,
        targets=unordered, target_conflict=False, atr=geometry.atr, snapshot=snapshot,
        evaluation=evaluation, policy=policy,
    )

    assert "INVALID_TARGET_GEOMETRY" in [reason.code for reason in result.reasons]


def test_no_execution_path_even_for_a_technically_valid_plan() -> None:
    assert (
        execution_eligibility(plan_status="PLAN_REVIEW_REQUIRED", strategy_status=StrategyValidationStatus.PENDING)
        .value
        == "REVIEW_REQUIRED"
    )
    assert (
        execution_eligibility(plan_status="PLAN_READY", strategy_status=StrategyValidationStatus.VALIDATED)
        .value
        == "EXECUTION_DISABLED"
    )
    assert (
        execution_eligibility(plan_status="PLAN_BLOCKED", strategy_status=StrategyValidationStatus.PENDING)
        .value
        == "NOT_ELIGIBLE"
    )


def test_service_builds_review_gated_plan_and_persists_once(settings: Settings) -> None:
    candles = build_cycle_candles(1, LONG_TAIL)
    database, planning, _ = _stack(settings, candles)
    repository = TradePlanRepository(database)

    result = planning.current()
    cached = planning.current()

    assert result.status is PlanStatus.PLAN_REVIEW_REQUIRED
    assert result.plan is not None
    assert result.plan.plan_status is PlanStatus.PLAN_REVIEW_REQUIRED
    assert result.plan.plan_validation_status is PlanValidationStatus.VALID
    assert result.plan.risk_validation_status is RiskValidationStatus.VALID
    assert result.plan.strategy_validation_status is StrategyValidationStatus.PENDING
    assert result.strategy_validation_status is StrategyValidationStatus.PENDING
    assert result.execution_eligibility.value == "REVIEW_REQUIRED"
    assert result.plan.execution_eligibility.value == "REVIEW_REQUIRED"
    assert result.plan.position_size is None
    assert result.plan.position_size_status == "NOT_CALCULATED"
    assert result.plan.actual_fill_price is None
    assert result.plan.risk_reward.rr_tp1 >= Decimal("1.0000")
    assert result.plan.strategy_evaluation_id.startswith("evl_")
    assert result.plan.market_snapshot_id.startswith("mkt_")
    assert result.plan.expires_at > result.plan.data_as_of
    assert cached.cached is True
    assert cached.plan is not None and cached.plan.plan_id == result.plan.plan_id
    assert repository.count() == 1

    stored = planning.get_plan(result.plan.plan_id)
    assert stored.plan_id == result.plan.plan_id
    assert stored.plan_status is PlanStatus.PLAN_REVIEW_REQUIRED


def test_service_builds_mirrored_short_plan(settings: Settings) -> None:
    candles = build_cycle_candles(-1, SHORT_TAIL)
    _, planning, _ = _stack(settings, candles)
    result = planning.current()

    assert result.status is PlanStatus.PLAN_REVIEW_REQUIRED
    assert result.plan is not None
    assert result.plan.direction == "SHORT"
    assert result.plan.stop_loss > result.plan.suggested_entry
    assert all(target.price < result.plan.suggested_entry for target in result.plan.take_profits)


def test_wait_and_no_trade_produce_blocked_results(settings: Settings) -> None:
    for tail, expected in (([-14.0] * 4 + [9.0, 9.0, 4.0], PlanStatus.PLAN_BLOCKED),
                           ([-14.0] * 4 + [6.0], PlanStatus.PLAN_BLOCKED)):
        candles = build_cycle_candles(1, tail)
        _, planning, _ = _stack(settings, candles)
        result = planning.current()
        assert result.status is expected
        assert result.plan is None
        assert result.plan_validation_status is PlanValidationStatus.NOT_EVALUATED
        assert result.risk_validation_status is RiskValidationStatus.NOT_EVALUATED
        assert result.execution_eligibility.value == "NOT_ELIGIBLE"
        assert result.rejection_reasons


def test_expired_candidate_and_stale_data(settings: Settings) -> None:
    candles = build_cycle_candles(1, LONG_TAIL)
    now = datetime.fromtimestamp(int(candles[-1].time) + 930, UTC)
    database = Database(settings.db_path)
    database.initialize()
    analysis = AnalysisService(
        source=StaticCandleSource(candles),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: now,
        cache_seconds=0.0,
    )
    strategies = StrategyService(
        analysis=analysis, repository=StrategyEvaluationRepository(database), clock=lambda: now
    )
    late = TradePlanningService(
        analysis=analysis,
        strategies=strategies,
        risk=RiskService(clock=lambda: now + timedelta(hours=2)),
        repository=TradePlanRepository(database),
        clock=lambda: now + timedelta(hours=2),
    )
    expired = late.current()
    assert expired.status is PlanStatus.PLAN_EXPIRED
    assert expired.plan is None
    assert any(reason.code == "PLAN_EXPIRED" for reason in expired.rejection_reasons)

    stale_now = now + timedelta(minutes=30)
    stale_analysis = AnalysisService(
        source=StaticCandleSource(candles),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: stale_now,
        cache_seconds=0.0,
    )
    stale_strategies = StrategyService(
        analysis=stale_analysis,
        repository=StrategyEvaluationRepository(database),
        clock=lambda: stale_now,
    )
    stale_planning = TradePlanningService(
        analysis=stale_analysis,
        strategies=stale_strategies,
        risk=RiskService(clock=lambda: stale_now),
        repository=TradePlanRepository(database),
        clock=lambda: stale_now,
    )
    stale = stale_planning.current()
    assert stale.status is PlanStatus.PLAN_EXPIRED
    assert any(reason.code == "MARKET_DATA_STALE" for reason in stale.rejection_reasons)


def test_plan_lifecycle_expires_and_never_upgrades(settings: Settings) -> None:
    candles = build_cycle_candles(1, LONG_TAIL)
    now = datetime.fromtimestamp(int(candles[-1].time) + 930, UTC)
    database = Database(settings.db_path)
    database.initialize()
    analysis = AnalysisService(
        source=StaticCandleSource(candles),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: now,
        cache_seconds=0.0,
    )
    strategies = StrategyService(
        analysis=analysis, repository=StrategyEvaluationRepository(database), clock=lambda: now
    )
    clock_box = {"now": now}
    planning = TradePlanningService(
        analysis=analysis,
        strategies=strategies,
        risk=RiskService(clock=lambda: clock_box["now"]),
        repository=TradePlanRepository(database),
        clock=lambda: clock_box["now"],
    )
    plan = planning.current().plan
    assert plan is not None
    clock_box["now"] = plan.expires_at + timedelta(seconds=1)
    refreshed = planning.get_plan(plan.plan_id)

    assert refreshed.plan_status is PlanStatus.PLAN_EXPIRED
    assert refreshed.execution_eligibility.value == "NOT_ELIGIBLE"
    assert any(reason.code == "PLAN_EXPIRED" for reason in refreshed.rejection_reasons)


def test_plan_invalidates_when_price_breaks_stop(settings: Settings) -> None:
    candles = build_cycle_candles(1, LONG_TAIL)
    database, planning, analysis = _stack(settings, candles)
    plan = planning.current().plan
    assert plan is not None
    base_snapshot = analysis.snapshot()

    class LaterAnalysis:
        def __init__(self, snapshot) -> None:  # type: ignore[no-untyped-def]
            self.snapshot_value = snapshot

        def snapshot(self, **kwargs):  # type: ignore[no-untyped-def]
            return self.snapshot_value

    later = base_snapshot.model_copy(
        update={
            "data_as_of": plan.data_as_of + timedelta(minutes=15),
            "last_price": float(plan.stop_loss) - 1.0,
        }
    )
    planning._analysis = LaterAnalysis(later)  # type: ignore[assignment]
    refreshed = planning.get_plan(plan.plan_id)

    assert refreshed.plan_status is PlanStatus.PLAN_INVALID
    assert any(reason.code == "INVALIDATION_TRIGGERED" for reason in refreshed.rejection_reasons)
    assert planning._repository.get(plan.plan_id)["plan_status"] == "PLAN_INVALID"


def test_entry_miss_expires_plan(settings: Settings) -> None:
    candles = build_cycle_candles(1, LONG_TAIL)
    database, planning, analysis = _stack(settings, candles)
    plan = planning.current().plan
    assert plan is not None
    base_snapshot = analysis.snapshot()
    later = base_snapshot.model_copy(
        update={
            "data_as_of": plan.data_as_of + timedelta(minutes=15),
            "last_price": float(plan.entry_zone.upper) + float(base_snapshot.volatility.atr14 or 0) * 2,
        }
    )

    class LaterAnalysis:
        def snapshot(self, **kwargs):  # type: ignore[no-untyped-def]
            return later

    planning._analysis = LaterAnalysis()  # type: ignore[assignment]
    refreshed = planning.get_plan(plan.plan_id)
    assert refreshed.plan_status is PlanStatus.PLAN_EXPIRED
    assert any(reason.code == "ENTRY_MISSED" for reason in refreshed.rejection_reasons)


def test_policy_version_is_recorded(settings: Settings) -> None:
    candles = build_cycle_candles(1, LONG_TAIL)
    policy = RiskPolicy(policy_version="risk-policy-test-9.9.9")
    _, planning, _ = _stack(settings, candles, policy=policy)
    result = planning.current()

    assert result.plan is not None
    assert result.plan.risk_policy_version == "risk-policy-test-9.9.9"
    assert result.risk_policy_version == "risk-policy-test-9.9.9"
    assert result.plan.risk_assessment.policy_version == "risk-policy-test-9.9.9"


def test_missing_plan_is_not_found(settings: Settings) -> None:
    candles = build_cycle_candles(1, LONG_TAIL)
    _, planning, _ = _stack(settings, candles)
    with pytest.raises(NotFoundError):
        planning.get_plan("plan_missing")


def test_persistence_failure_degrades_with_warning(settings: Settings) -> None:
    candles = build_cycle_candles(1, LONG_TAIL)
    now = datetime.fromtimestamp(int(candles[-1].time) + 930, UTC)
    database = Database(settings.db_path)
    database.initialize()
    analysis = AnalysisService(
        source=StaticCandleSource(candles),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: now,
        cache_seconds=0.0,
    )
    strategies = StrategyService(
        analysis=analysis, repository=StrategyEvaluationRepository(database), clock=lambda: now
    )

    class FailingRepository(TradePlanRepository):
        def insert(self, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("disk full")

    planning = TradePlanningService(
        analysis=analysis,
        strategies=strategies,
        risk=RiskService(clock=lambda: now),
        repository=FailingRepository(database),
        clock=lambda: now,
    )
    result = planning.current()

    assert result.plan is not None
    assert any("persistence failed" in warning.lower() for warning in result.warnings)
