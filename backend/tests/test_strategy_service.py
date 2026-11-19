from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.errors import NotFoundError, UnsupportedScopeError
from app.persistence.db import Database
from app.persistence.repositories import StrategyEvaluationRepository
from app.strategies.config import STRATEGY_ID
from app.strategies.service import StrategyService
from tests.strategy_fixtures import confirmed_long


class StubAnalysis:
    def __init__(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        self.snapshot_value = snapshot
        self.calls: list[dict[str, object]] = []

    def snapshot(self, *, symbol: str, timeframe: str, refresh: bool = False):  # type: ignore[no-untyped-def]
        self.calls.append({"symbol": symbol, "timeframe": timeframe, "refresh": refresh})
        return self.snapshot_value


class FailingRepository(StrategyEvaluationRepository):
    def insert(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk full")


@pytest.fixture
def service_parts(settings):  # type: ignore[no-untyped-def]
    database = Database(settings.db_path)
    database.initialize()
    return database, StrategyEvaluationRepository(database)


def test_service_reuses_the_phase_one_snapshot_and_persists(service_parts) -> None:  # type: ignore[no-untyped-def]
    database, repository = service_parts
    snapshot = confirmed_long()
    analysis = StubAnalysis(snapshot)
    service = StrategyService(
        analysis=analysis,  # type: ignore[arg-type]
        repository=repository,
        clock=lambda: snapshot.generated_at,
    )

    evaluation = service.evaluate(refresh=True)

    assert analysis.calls == [{"symbol": "BTCUSDT", "timeframe": "M15", "refresh": True}]
    assert evaluation.decision.value == "LONG"
    assert evaluation.market_snapshot_id == snapshot.snapshot_id
    assert repository.count(STRATEGY_ID) == 1

    # Re-evaluating the same closed bar is idempotent.
    service.evaluate()
    assert repository.count(STRATEGY_ID) == 1
    stored = repository.latest(STRATEGY_ID, "BTCUSDT", "M15")
    assert stored is not None
    assert stored["evaluation_id"] == evaluation.evaluation_id
    assert stored["decision"] == "LONG"
    assert database.query_one("SELECT COUNT(*) AS total FROM strategy_evaluations")["total"] == 1


def test_service_catalog_lists_only_implemented_strategies(service_parts) -> None:  # type: ignore[no-untyped-def]
    _, repository = service_parts
    snapshot = confirmed_long()
    service = StrategyService(
        analysis=StubAnalysis(snapshot),  # type: ignore[arg-type]
        repository=repository,
        clock=lambda: snapshot.generated_at,
    )

    catalog = service.catalog()

    assert len(catalog.strategies) == 1
    item = catalog.strategies[0]
    assert item.strategy_id == STRATEGY_ID
    assert item.symbol == "BTCUSDT"
    assert item.timeframe == "M15"
    assert item.status == "active"
    assert item.implemented is True
    assert "no entry, stop or target" in item.description


def test_unknown_strategy_and_unsupported_scope_are_rejected(service_parts) -> None:  # type: ignore[no-untyped-def]
    _, repository = service_parts
    service = StrategyService(analysis=StubAnalysis(confirmed_long()), repository=repository)  # type: ignore[arg-type]

    with pytest.raises(NotFoundError) as not_found:
        service.evaluate(strategy_id="breakout_retest")
    assert not_found.value.code == "NOT_FOUND"

    with pytest.raises(UnsupportedScopeError) as unsupported:
        service.evaluate(symbol="ETHUSDT")
    assert unsupported.value.code == "UNSUPPORTED_SCOPE"

    with pytest.raises(UnsupportedScopeError) as unsupported:
        service.evaluate(timeframe="H1")
    assert unsupported.value.code == "UNSUPPORTED_SCOPE"


def test_persistence_failure_degrades_with_a_warning(settings) -> None:  # type: ignore[no-untyped-def]
    database = Database(settings.db_path)
    database.initialize()
    snapshot = confirmed_long()
    service = StrategyService(
        analysis=StubAnalysis(snapshot),  # type: ignore[arg-type]
        repository=FailingRepository(database),
        clock=lambda: snapshot.generated_at,
    )

    evaluation = service.evaluate()

    assert evaluation.decision.value == "LONG"
    assert any("persistence failed" in warning.lower() for warning in evaluation.warnings)


def test_status_reports_scope_and_evaluation_counts(service_parts) -> None:  # type: ignore[no-untyped-def]
    _, repository = service_parts
    snapshot = confirmed_long()
    service = StrategyService(
        analysis=StubAnalysis(snapshot),  # type: ignore[arg-type]
        repository=repository,
        clock=lambda: datetime(2026, 1, 2, tzinfo=UTC),
    )

    service.evaluate()
    status = service.status()

    assert status["enabled"] is True
    assert status["evaluations"] == 1
    assert status["persisted_evaluations"] == 1
    assert status["last_error"] is None
    assert status["generated_at"].startswith("2026-01-02")
