from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.analysis.service import AnalysisService
from app.core.config import Settings
from app.persistence.db import Database
from app.persistence.repositories import (
    MarketSnapshotRepository,
    StrategyEvaluationRepository,
    TradePlanRepository,
)
from app.risk.service import RiskService
from app.strategies.service import StrategyService
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


def _client(make_client, planning_service):  # type: ignore[no-untyped-def]
    return make_client(
        analysis=planning_service._analysis,
        strategies=planning_service._strategies,
        risk=planning_service._risk,
        trade_planning=planning_service,
    )


def test_current_plan_endpoint_returns_review_gated_geometry(make_client, planning_service) -> None:  # type: ignore[no-untyped-def]
    client = _client(make_client, planning_service)
    response = client.get("/api/v1/planning/current")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "PLAN_REVIEW_REQUIRED"
    assert body["strategy_validation_status"] == "PENDING"
    assert body["execution_eligibility"] == "REVIEW_REQUIRED"
    assert body["plan_validation_status"] == "VALID"
    assert body["risk_validation_status"] == "VALID"
    assert body["position_size"] is None
    assert body["position_size_status"] == "NOT_CALCULATED"
    assert body["plan"]["plan_status"] == "PLAN_REVIEW_REQUIRED"
    assert body["plan"]["actual_fill_price"] is None
    assert body["plan"]["position_size"] is None
    assert body["plan"]["strategy_validation_status"] == "PENDING"
    assert body["plan"]["execution_eligibility"] == "REVIEW_REQUIRED"
    assert Decimal(str(body["plan"]["stop_loss"])) < Decimal(str(body["plan"]["suggested_entry"]))
    assert [target["label"] for target in body["plan"]["take_profits"]] == ["TP1", "TP2", "TP3"]
    assert all("order" not in key for key in body["plan"])

    second = client.get("/api/v1/planning/current")
    assert second.json()["cached"] is True


def test_plan_lookup_and_risk_endpoint(make_client, planning_service) -> None:  # type: ignore[no-untyped-def]
    client = _client(make_client, planning_service)
    current = client.get("/api/v1/planning/current").json()
    plan_id = current["plan"]["plan_id"]

    stored = client.get(f"/api/v1/planning/plans/{plan_id}")
    assert stored.status_code == 200, stored.text
    assert stored.json()["plan_id"] == plan_id

    risk = client.get("/api/v1/risk/current")
    assert risk.status_code == 200, risk.text
    body = risk.json()
    assert body["position_size"] is None
    assert body["position_size_status"] == "NOT_CALCULATED"
    assert body["strategy_validation_status"] == "PENDING"
    assert body["execution_eligibility"] == "REVIEW_REQUIRED"
    assert body["assessment"]["passed"] is True


def test_planning_endpoints_reject_bad_scope_and_unknown_plan(make_client, planning_service) -> None:  # type: ignore[no-untyped-def]
    client = _client(make_client, planning_service)
    for path in (
        "/api/v1/planning/current?symbol=ETHUSDT",
        "/api/v1/risk/current?timeframe=H1",
    ):
        response = client.get(path)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "UNSUPPORTED_SCOPE"

    missing = client.get("/api/v1/planning/plans/plan_missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_planning_services_are_optional(make_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def explode(*args, **kwargs):
        raise RuntimeError("planning init failure")

    monkeypatch.setattr("app.container.TradePlanningService", explode)
    client = make_client()
    planning = client.get("/api/v1/planning/current")
    assert planning.status_code == 503
    assert planning.json()["error"]["code"] == "TRADE_PLANNING_UNAVAILABLE"

    risk = client.get("/api/v1/risk/current")
    assert risk.status_code == 503
    assert risk.json()["error"]["code"] == "RISK_UNAVAILABLE"

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/market/context").status_code in {200, 503}
