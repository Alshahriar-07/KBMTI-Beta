from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.analysis.service import AnalysisService
from app.core.config import Settings
from app.persistence.db import Database
from app.persistence.repositories import MarketSnapshotRepository
from app.strategies.config import STRATEGY_ID
from tests.analysis_fixtures import StaticCandleSource
from tests.strategy_fixtures import build_cycle_candles

CANDLES = build_cycle_candles(1, [-16.0] * 4 + [9.0] * 3)
NOW = datetime.fromtimestamp(int(CANDLES[-1].time) + 930, UTC)


@pytest.fixture
def analysis_service(settings: Settings) -> AnalysisService:
    database = Database(settings.db_path)
    database.initialize()
    return AnalysisService(
        source=StaticCandleSource(CANDLES),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: NOW,
        cache_seconds=0.0,
    )


def test_strategy_catalog_endpoint(make_client, analysis_service) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    response = client.get("/api/v1/strategies")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["strategy_id"] for item in body["strategies"]] == [STRATEGY_ID]
    assert body["strategies"][0]["implemented"] is True
    assert body["strategies"][0]["symbol"] == "BTCUSDT"
    assert body["strategies"][0]["timeframe"] == "M15"


def test_trend_pullback_endpoint_returns_a_typed_evaluation(make_client, analysis_service) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    response = client.get("/api/v1/strategies/trend-pullback")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy_id"] == STRATEGY_ID
    assert body["strategy_version"] == "1.0.0"
    assert body["config_version"] == "trend-pullback-config-1.0.0"
    assert body["decision"] == "LONG"
    assert body["direction"] == "LONG"
    assert body["quality"]["is_probability"] is False
    assert body["eligibility"]["pullback_present"] is True
    assert body["evidence"]
    assert body["market_snapshot_id"].startswith("mkt_")
    assert body["market_feature_version"]
    assert body["reference_price"] > 0
    for forbidden in ("entry", "stop_loss", "take_profit", "leverage", "position_size", "quantity"):
        assert forbidden not in body

    persisted = client.app.state.container.strategies.status()
    assert persisted["persisted_evaluations"] == 1


def test_strategy_endpoints_reject_unsupported_scope(make_client, analysis_service) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    for path in (
        "/api/v1/strategies/trend-pullback?symbol=ETHUSDT",
        "/api/v1/strategies/trend-pullback?timeframe=H1",
    ):
        response = client.get(path)
        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "UNSUPPORTED_SCOPE"
        assert error["details"]["supported"] is False


def test_strategy_endpoint_is_unavailable_without_the_service(make_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def explode(*args, **kwargs):
        raise RuntimeError("strategy init failure")

    monkeypatch.setattr("app.container.StrategyService", explode)
    client = make_client()
    response = client.get("/api/v1/strategies/trend-pullback")
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "STRATEGY_UNAVAILABLE"
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/strategies").status_code == 503
