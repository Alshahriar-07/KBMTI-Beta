from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.analysis.service import AnalysisService
from app.core.config import Settings
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
from app.trade_journal.repository import JournalRepository
from app.trade_journal.service import JournalService
from app.trade_planning.service import TradePlanningService
from tests.analysis_fixtures import StaticCandleSource
from tests.strategy_fixtures import build_cycle_candles

CANDLES = build_cycle_candles(1, [-16.0] * 4 + [9.0] * 3)
NOW = datetime.fromtimestamp(int(CANDLES[-1].time) + 930, UTC)


@pytest.fixture
def planning_service(settings: Settings) -> TradePlanningService:
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
    return TradePlanningService(
        analysis=analysis,
        strategies=strategies,
        risk=RiskService(clock=lambda: NOW),
        repository=TradePlanRepository(database),
        clock=lambda: NOW,
    )


def _client(make_client, planning_service, settings):  # type: ignore[no-untyped-def]
    database = Database(settings.db_path)
    repository = JournalRepository(database)
    journal = JournalService(
        planning=planning_service,
        repository=repository,
        candles=CandleRepository(database),
        clock=lambda: NOW,
    )
    outcomes = OutcomeService(journal=repository, candles=CandleRepository(database), clock=lambda: NOW)
    return make_client(
        analysis=planning_service._analysis,
        strategies=planning_service._strategies,
        risk=planning_service._risk,
        trade_planning=planning_service,
        journal=journal,
        outcomes=outcomes,
    )


def test_journal_api_lifecycle_and_no_execution_paths(make_client, planning_service, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    client = _client(make_client, planning_service, settings)
    plan = client.get("/api/v1/planning/current").json()["plan"]
    plan_id = plan["plan_id"]

    accepted = client.post(
        f"/api/v1/journal/setups/{plan_id}/actions?action=ACCEPT",
        json={"actor": "api-test", "note": "paper only"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["action"]["action"] == "ACCEPT"
    assert accepted.json()["execution_eligibility"] == "REVIEW_REQUIRED"

    created = client.post(
        "/api/v1/journal/records",
        json={"plan_id": plan_id, "mode": "PAPER", "notes": "api paper"},
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["position_size"] is None
    assert record["position_size_status"] == "NOT_CALCULATED"
    record_id = record["trade_id"]

    monitored = client.get(f"/api/v1/journal/records/{record_id}/monitor?price={record['actual_entry']}")
    assert monitored.status_code == 200, monitored.text
    assert monitored.json()["guidance"] == "HOLD"

    closed = client.post(
        f"/api/v1/journal/records/{record_id}/events",
        json={"event_type": "TP_HIT", "price": plan["take_profits"][0]["price"]},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"

    outcome = client.get(f"/api/v1/journal/outcomes/{record_id}")
    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["category"] == "SUCCESS"

    review = client.post(
        f"/api/v1/journal/outcomes/{record_id}/review",
        json={"status": "APPROVED_FOR_DATASET", "reviewer": "api-reviewer", "note": "checked"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["review"]["dataset_eligible"] is True

    paths = set(client.get("/openapi.json").json()["paths"])
    forbidden = [
        path for path in paths if any(token in path for token in ("order", "trade", "position", "buy", "sell"))
    ]
    assert forbidden == []
    assert "/api/v1/journal/records" in paths
