from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.analysis.service import AnalysisService
from app.core.config import Settings
from app.core.errors import ApiError
from app.outcomes.analyzer import analyze_outcome
from app.outcomes.service import OutcomeService
from app.persistence.db import Database
from app.persistence.repositories import (
    CandleRepository,
    MarketSnapshotRepository,
    StrategyEvaluationRepository,
    TradePlanRepository,
)
from app.risk.service import RiskService
from app.strategies.service import StrategyService
from app.trade_journal.contracts import (
    OutcomeReviewRequest,
    OutcomeReviewStatus,
    SetupActionRequest,
    SetupActionType,
    TradeCreateRequest,
    TradeEventRequest,
    TradeEventType,
    TradeMode,
)
from app.trade_journal.repository import JournalRepository
from app.trade_journal.service import JournalService
from app.trade_planning.service import TradePlanningService
from tests.analysis_fixtures import StaticCandleSource
from tests.strategy_fixtures import build_cycle_candles

CANDLES = build_cycle_candles(1, [-16.0] * 4 + [9.0] * 3)
NOW = datetime.fromtimestamp(int(CANDLES[-1].time) + 930, UTC)


def _stack(settings: Settings):
    database = Database(settings.db_path)
    database.initialize()
    analysis = AnalysisService(
        source=StaticCandleSource(CANDLES),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: NOW,
        cache_seconds=0.0,
    )
    strategies = StrategyService(
        analysis=analysis,
        repository=StrategyEvaluationRepository(database),
        clock=lambda: NOW,
    )
    planning = TradePlanningService(
        analysis=analysis,
        strategies=strategies,
        risk=RiskService(clock=lambda: NOW),
        repository=TradePlanRepository(database),
        clock=lambda: NOW,
    )
    repository = JournalRepository(database)
    journal = JournalService(
        planning=planning,
        repository=repository,
        candles=CandleRepository(database),
        clock=lambda: NOW,
    )
    outcomes = OutcomeService(journal=repository, candles=CandleRepository(database), clock=lambda: NOW)
    return planning, journal, outcomes, repository


def _accepted_trade(settings: Settings):
    planning, journal, outcomes, repository = _stack(settings)
    plan = planning.current().plan
    assert plan is not None
    journal.record_setup_action(
        plan.plan_id,
        SetupActionType.ACCEPT,
        SetupActionRequest(actor="tester", note="paper review"),
    )
    record = journal.create_record(
        TradeCreateRequest(plan_id=plan.plan_id, mode=TradeMode.PAPER, notes="paper")
    )
    return plan, journal, outcomes, repository, record


def test_setup_must_be_accepted_before_record(settings: Settings) -> None:
    planning, journal, _outcomes, _repository = _stack(settings)
    plan = planning.current().plan
    assert plan is not None
    with pytest.raises(ApiError) as exc:
        journal.create_record(TradeCreateRequest(plan_id=plan.plan_id))
    assert exc.value.status_code == 409
    assert exc.value.code == "SETUP_NOT_ACCEPTED"


def test_paper_record_monitoring_and_tp_outcome(settings: Settings) -> None:
    plan, journal, outcomes, _repository, record = _accepted_trade(settings)
    assert record.actual_entry == plan.suggested_entry
    assert record.position_size is None
    assert record.position_size_status == "NOT_CALCULATED"
    assert record.mode is TradeMode.PAPER

    hold = journal.monitor(record.trade_id, record.actual_entry)
    assert hold.guidance.value == "HOLD"

    stop_hit = journal.monitor(record.trade_id, plan.stop_loss)
    assert stop_hit.guidance.value == "STOP_HIT"
    assert stop_hit.invalidation_triggered is True

    closed = journal.append_event(
        record.trade_id,
        TradeEventRequest(event_type=TradeEventType.TP_HIT, price=plan.take_profits[0].price, note="TP1"),
    )
    assert closed.status.value == "CLOSED"
    assert closed.outcome.value == "SUCCESS"
    assert closed.r_multiple is not None and closed.r_multiple > Decimal("0")
    assert closed.events[-1].event_type is TradeEventType.TP_HIT

    outcome = outcomes.get_outcome(closed.trade_id)
    assert outcome.category.value == "SUCCESS"
    assert outcome.findings and any(item.code == "TARGET_REACHED" for item in outcome.findings)
    assert "not evidence of edge" in str(outcome.sample_warning)

    with pytest.raises(ApiError) as exc:
        journal.append_event(
            record.trade_id,
            TradeEventRequest(event_type=TradeEventType.NOTE, note="late"),
        )
    assert exc.value.code == "RECORD_CLOSED"


def test_stop_outcome_and_review_eligibility(settings: Settings) -> None:
    plan, journal, outcomes, _repository, record = _accepted_trade(settings)
    stopped = journal.append_event(
        record.trade_id,
        TradeEventRequest(event_type=TradeEventType.STOP_HIT, price=plan.stop_loss),
    )
    assert stopped.outcome.value == "LOSS"
    assert stopped.r_multiple is not None and stopped.r_multiple < Decimal("0")

    pending = outcomes.review(
        stopped.trade_id,
        OutcomeReviewRequest(status=OutcomeReviewStatus.REVIEWED, reviewer="reviewer", note="checked"),
    )
    assert pending.dataset_eligible is False

    approved = outcomes.review(
        stopped.trade_id,
        OutcomeReviewRequest(
            status=OutcomeReviewStatus.APPROVED_FOR_DATASET,
            reviewer="reviewer",
            note="evidence checked",
        ),
    )
    assert approved.dataset_eligible is True
    assert approved.status is OutcomeReviewStatus.APPROVED_FOR_DATASET
    assert any(finding.code == "STOP_LOSS_HIT" for finding in approved.findings)
    assert any(finding.code == "STRATEGY_UNVALIDATED" for finding in approved.findings)


def test_patron_alignment_is_evidence_not_causation() -> None:
    trade = {
        "trade_id": "rec_test",
        "direction": "LONG",
        "actual_entry": "100",
        "planned_entry": "100",
        "stop_loss": "90",
        "exit_price": "110",
        "fees": "0",
        "slippage": "0",
        "status": "CLOSED",
        "mode": "PAPER",
        "opened_at": "2026-01-01T00:00:00+00:00",
        "closed_at": "2026-01-01T01:00:00+00:00",
        "strategy_validation_status": "PENDING",
    }
    aligned = analyze_outcome(
        trade=trade,
        events=[{"event_id": "e", "event_type": "TP_HIT"}],
        patron_alignment={"forecast_id": "f1", "evaluated_steps": 3, "predicted_direction": "SHORT"},
    )
    finding = next(item for item in aligned.findings if item.code == "PATRON_FORECAST_CONFLICT")
    assert finding.confidence == "probable"
    assert "not proof of causation" in finding.message
    assert aligned.category.value == "SUCCESS"


def test_invalidated_record_is_not_a_loss_or_dataset_case(settings: Settings) -> None:
    _plan, journal, outcomes, _repository, record = _accepted_trade(settings)
    expired = journal.append_event(
        record.trade_id,
        TradeEventRequest(event_type=TradeEventType.INVALIDATED, note="structure broke"),
    )
    assert expired.status.value == "EXPIRED"
    outcome = outcomes.get_outcome(expired.trade_id)
    assert outcome.category.value == "INVALID_SETUP"
    review = outcomes.review(
        expired.trade_id,
        OutcomeReviewRequest(
            status=OutcomeReviewStatus.APPROVED_FOR_DATASET,
            reviewer="reviewer",
            note="invalid setup",
        ),
    )
    assert review.dataset_eligible is False
