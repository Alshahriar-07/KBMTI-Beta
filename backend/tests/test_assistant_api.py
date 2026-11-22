from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.analysis.service import AnalysisService
from app.core.config import Settings
from app.intelligence.service import IntelligenceService
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
def intelligence(settings: Settings) -> IntelligenceService:
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
    return IntelligenceService(
        analysis=analysis,
        strategies=strategies,
        planning=planning,
        kie=None,
        clock=lambda: NOW,
    )


def _client(make_client, service):  # type: ignore[no-untyped-def]
    return make_client(
        analysis=service._analysis,
        strategies=service._strategies,
        risk=service._planning._risk,
        trade_planning=service._planning,
        intelligence=service,
    )


def test_assistant_current_and_knowledge(make_client, intelligence) -> None:  # type: ignore[no-untyped-def]
    client = _client(make_client, intelligence)
    response = client.get("/api/v1/assistant/current?use_qwen=false")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] in {"LONG", "SHORT", "WAIT", "NO_TRADE"}
    assert body["strategy_validation_status"] == "PENDING"
    assert body["execution"] == "DISABLED"
    assert body["position_size"] is None
    assert body["qwen"]["used"] is False
    assert body["knowledge_refs"]

    knowledge = client.get("/api/v1/assistant/knowledge?q=change%20of%20character")
    assert knowledge.status_code == 200, knowledge.text
    assert knowledge.json()["count"] >= 1
    assert knowledge.json()["hits"][0]["refs"][0].startswith("knowledge:")

    status = client.get("/api/v1/assistant/status")
    assert status.status_code == 200
    assert status.json()["strategy_validation_status"] == "PENDING"
    assert status.json()["execution"] == "DISABLED"

    paths = set(client.get("/openapi.json").json()["paths"])
    forbidden = [
        path for path in paths if any(token in path for token in ("order", "trade", "position", "buy", "sell"))
    ]
    assert forbidden == []
    assert "/api/v1/assistant/current" in paths
