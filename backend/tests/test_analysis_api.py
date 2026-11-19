from __future__ import annotations

import pytest

from app.analysis.service import AnalysisService
from app.core.config import Settings
from app.persistence.db import Database
from app.persistence.repositories import MarketSnapshotRepository
from tests.analysis_fixtures import StaticCandleSource, fixture_candles, fixture_now


@pytest.fixture
def analysis_service(settings: Settings) -> AnalysisService:
    database = Database(settings.db_path)
    database.initialize()
    return AnalysisService(
        source=StaticCandleSource(fixture_candles("uptrend")),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: fixture_now("uptrend"),
        cache_seconds=0.0,
    )


def test_market_context_endpoint(make_client, analysis_service) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    response = client.get("/api/v1/market/context")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "BTCUSDT"
    assert body["timeframe"] == "M15"
    assert body["scope"]["supported"] is True
    assert body["validation"]["status"] == "OK"
    assert body["trend_state"] in {"BULLISH", "STRONG_BULLISH"}
    assert body["structure_state"] == "UPTREND"
    assert body["regime_state"] == "TRENDING_UP"
    assert body["data_as_of"] and body["generated_at"]
    assert body["provenance"]["source"] == "fixture"
    assert body["provenance"]["candle_count"] == 180
    assert body["feature_version"]
    assert body["snapshot_id"].startswith("mkt_")
    assert body["warnings"] == [] or isinstance(body["warnings"], list)


def test_market_analysis_endpoint_returns_full_bundle(make_client, analysis_service) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    response = client.get("/api/v1/market/analysis?symbol=btcusdt&timeframe=m15")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provenance"]["candle_count"] == 180
    assert body["provenance"]["input_hash"]
    assert body["trend"]["meta"]["valid"] is True
    assert body["structure"]["events"]
    assert body["structure"]["levels"]
    assert body["momentum"]["meta"]["version"].startswith("momentum-")
    assert body["volatility"]["atr14"] is not None
    assert body["regime"]["reasons"]
    assert body["validation"]["checks"]


def test_analysis_endpoints_reject_unsupported_scope(make_client, analysis_service) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    for path in (
        "/api/v1/market/context?symbol=ETHUSDT&timeframe=M15",
        "/api/v1/market/analysis?symbol=BTCUSDT&timeframe=H1",
    ):
        response = client.get(path)
        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "UNSUPPORTED_SCOPE"
        assert error["details"]["supported"] is False


def test_analysis_endpoints_are_unavailable_without_the_service(make_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def explode(*args, **kwargs):
        raise RuntimeError("analysis init failure")

    monkeypatch.setattr("app.container.AnalysisService", explode)
    client = make_client()
    response = client.get("/api/v1/market/context")
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "MARKET_ANALYSIS_UNAVAILABLE"
    assert client.get("/api/v1/health").status_code == 200


def test_existing_endpoints_remain_compatible(make_client, analysis_service) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    for path in (
        "/api/v1/health",
        "/api/v1/market/snapshot",
        "/api/v1/market/candles",
        "/api/v1/indicators",
        "/api/v1/signals/current",
        "/api/v1/forecast/status",
        "/api/v1/chat/suggestions",
        "/api/v1/kie/status",
        "/api/v1/system/status",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"


def test_context_request_is_persisted(make_client, analysis_service, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    response = client.get("/api/v1/market/context")
    assert response.status_code == 200
    repository = MarketSnapshotRepository(Database(settings.db_path))
    stored = repository.latest("BTCUSDT", "M15")
    assert stored is not None
    assert stored["snapshot_id"] == response.json()["snapshot_id"]


def test_refresh_query_is_supported(make_client, analysis_service) -> None:  # type: ignore[no-untyped-def]
    client = make_client(analysis=analysis_service)
    first = client.get("/api/v1/market/context?refresh=true")
    second = client.get("/api/v1/market/analysis?refresh=true")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["snapshot_id"] == second.json()["snapshot_id"]
