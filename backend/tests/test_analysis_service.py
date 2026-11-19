from __future__ import annotations

from datetime import timedelta

import pytest

from app.analysis.contracts import RegimeState, ValidationStatus
from app.analysis.service import AnalysisService
from app.analysis.sources import FallbackCandleSource
from app.core.config import Settings
from app.core.errors import MarketDataUnavailableError, UnsupportedScopeError
from app.persistence.db import Database
from app.persistence.repositories import MarketSnapshotRepository
from tests.analysis_fixtures import StaticCandleSource, fixture_candles, fixture_now


class BrokenRepository:
    def insert(self, **kwargs):
        raise RuntimeError("database unavailable")

    def count(self, symbol=None, timeframe=None):
        return 0


class BrokenSource:
    def fetch(self, symbol: str, timeframe: str, limit: int):
        raise MarketDataUnavailableError("binance down")


def make_service(
    settings: Settings,
    *,
    clock=None,
    repository=None,
    cache_seconds: float = 5.0,
    source=None,
) -> AnalysisService:
    database = Database(settings.db_path)
    database.initialize()
    return AnalysisService(
        source=source or StaticCandleSource(fixture_candles("uptrend")),
        repository=repository if repository is not None else MarketSnapshotRepository(database),
        settings=settings,
        clock=clock or (lambda: fixture_now("uptrend")),
        cache_seconds=cache_seconds,
    )


def test_service_builds_context_and_persists(settings: Settings) -> None:
    service = make_service(settings)
    context = service.context()
    assert context.symbol == "BTCUSDT"
    assert context.timeframe == "M15"
    assert context.validation.status is ValidationStatus.OK
    assert context.snapshot_id.startswith("mkt_")
    repository = MarketSnapshotRepository(Database(settings.db_path))
    assert repository.count("BTCUSDT", "M15") == 1
    stored = repository.latest("BTCUSDT", "M15")
    assert stored is not None
    assert stored["snapshot_id"] == context.snapshot_id
    assert stored["provenance"]["input_hash"]
    assert stored["feature_version"] == context.feature_version


def test_service_reuses_the_cached_snapshot(settings: Settings) -> None:
    source = StaticCandleSource(fixture_candles("uptrend"))
    service = make_service(settings, source=source)
    first = service.context()
    second = service.context()
    assert source.calls == 1
    assert first.snapshot_id == second.snapshot_id
    assert first.request_id != second.request_id
    service.context(refresh=True)
    assert source.calls == 2


def test_cached_snapshot_becomes_stale_without_refetching(settings: Settings) -> None:
    now = [fixture_now("uptrend")]
    source = StaticCandleSource(fixture_candles("uptrend"))
    service = make_service(settings, source=source, clock=lambda: now[0], cache_seconds=300)
    fresh = service.context()
    assert fresh.is_stale is False
    now[0] = now[0] + timedelta(hours=2)
    stale = service.context()
    assert source.calls == 1
    assert stale.is_stale is True
    assert stale.validation.status is ValidationStatus.STALE
    assert stale.regime_state is RegimeState.UNCERTAIN


def test_service_handles_insufficient_and_invalid_data(settings: Settings) -> None:
    short = make_service(settings, source=StaticCandleSource(fixture_candles("insufficient")))
    assert short.context().validation.status is ValidationStatus.INSUFFICIENT_DATA

    invalid = AnalysisService(
        source=StaticCandleSource(fixture_candles("invalid")),
        repository=None,
        settings=settings,
        clock=lambda: fixture_now("invalid"),
    )
    assert invalid.context().validation.status is ValidationStatus.INVALID


def test_service_rejects_unsupported_scope(settings: Settings) -> None:
    service = make_service(settings)
    with pytest.raises(UnsupportedScopeError):
        service.context(symbol="ETHUSDT", timeframe="M15")
    with pytest.raises(UnsupportedScopeError):
        service.context(timeframe="H1")


def test_fallback_source_is_recorded(settings: Settings) -> None:
    fallback = StaticCandleSource(fixture_candles("uptrend"), source="database_cache")
    service = make_service(
        settings,
        source=FallbackCandleSource(BrokenSource(), fallback),
    )
    snapshot = service.snapshot()
    assert snapshot.provenance.source == "database_cache"
    assert any("stored Binance candles" in warning for warning in snapshot.warnings)


def test_persistence_failure_is_non_fatal(settings: Settings) -> None:
    service = make_service(settings, repository=BrokenRepository())
    snapshot = service.snapshot()
    assert snapshot.validation.status is ValidationStatus.OK
    assert any("persistence failed" in warning.lower() for warning in snapshot.warnings)


def test_repository_is_idempotent_for_the_same_snapshot(settings: Settings) -> None:
    database = Database(settings.db_path)
    database.initialize()
    repository = MarketSnapshotRepository(database)
    snapshot = AnalysisService(
        source=StaticCandleSource(fixture_candles("uptrend")),
        repository=None,
        settings=settings,
        clock=lambda: fixture_now("uptrend"),
    ).snapshot()
    payload = snapshot.model_dump(mode="json")
    first = repository.insert(
        snapshot_id=snapshot.snapshot_id,
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        provider=snapshot.provider,
        generated_at=snapshot.generated_at.isoformat(),
        data_as_of=snapshot.data_as_of.isoformat(),
        is_stale=snapshot.is_stale,
        feature_version=snapshot.feature_version,
        validation_status=snapshot.validation.status.value,
        payload=payload,
    )
    second = repository.insert(
        snapshot_id=snapshot.snapshot_id,
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        provider=snapshot.provider,
        generated_at=snapshot.generated_at.isoformat(),
        data_as_of=snapshot.data_as_of.isoformat(),
        is_stale=snapshot.is_stale,
        feature_version=snapshot.feature_version,
        validation_status=snapshot.validation.status.value,
        payload=payload,
    )
    assert first is True
    assert second is False
    assert repository.count() == 1
    assert repository.get(snapshot.snapshot_id) is not None


def test_status_reports_the_configured_scope(settings: Settings) -> None:
    status = make_service(settings).status()
    assert status["scope"] == {"symbol": "BTCUSDT", "timeframe": "M15"}
    assert status["feature_version"]
    assert status["enabled"] is True
