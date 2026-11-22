from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.learning.repository import LearningRepository
from app.learning.service import LearningService
from app.persistence.db import Database
from app.persistence.repositories import MarketSnapshotRepository


def _seed_snapshots(settings: Settings, count: int = 40) -> None:
    database = Database(settings.db_path)
    repository = MarketSnapshotRepository(database)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(count):
        at = start + timedelta(minutes=15 * index)
        payload = {
            "snapshot_id": f"api-s{index:03d}",
            "data_as_of": at.isoformat(),
            "generated_at": at.isoformat(),
            "symbol": "BTCUSDT",
            "timeframe": "M15",
            "validation_status": "OK",
            "is_stale": False,
            "feature_version": "market-intelligence-1.0.0",
            "last_price": 30000 + index,
            "trend": {"state": "BULLISH"},
            "structure": {"state": "UPTREND"},
            "momentum": {"state": "BULLISH"},
            "volatility": {"state": "NORMAL"},
            "regime": {"state": "TRENDING_UP"},
        }
        repository.insert(
            snapshot_id=payload["snapshot_id"],
            symbol="BTCUSDT",
            timeframe="M15",
            provider="fixture",
            generated_at=payload["generated_at"],
            data_as_of=payload["data_as_of"],
            is_stale=False,
            feature_version=payload["feature_version"],
            validation_status="OK",
            payload=payload,
        )


@pytest.fixture
def learning(settings: Settings) -> LearningService:
    database = Database(settings.db_path)
    database.initialize()
    return LearningService(
        repository=LearningRepository(database),
        snapshots=MarketSnapshotRepository(database),
    )


def test_learning_api_dataset_and_approval_flow(make_client, learning, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    _seed_snapshots(settings)
    client = make_client(learning=learning)
    status = client.get("/api/v1/learning/status")
    assert status.status_code == 200, status.text
    assert status.json()["execution"] == "DISABLED"
    assert status.json()["training_available"] is False

    prepared = client.post("/api/v1/learning/datasets/prepare", json={"limit": 40, "purge": 2})
    assert prepared.status_code == 200, prepared.text
    manifest = prepared.json()
    assert manifest["audit"]["valid"] is True
    assert manifest["status"] == "VALID"
    dataset_id = manifest["dataset_id"]

    job = client.post(
        "/api/v1/learning/jobs",
        json={"dataset_id": dataset_id, "requested_by": "tester"},
    )
    assert job.status_code == 200, job.text
    job_id = job.json()["job_id"]
    assert job.json()["status"] == "AWAITING_APPROVAL"
    approved = client.post(
        f"/api/v1/learning/jobs/{job_id}/approve",
        json={"actor": "operator", "note": "reviewed"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["job"]["status"] == "APPROVED_NOT_RUN"
    assert approved.json()["execution"] == "DISABLED"

    first = client.post("/api/v1/learning/models", json={"name": "candidate-a"}).json()
    second = client.post("/api/v1/learning/models", json={"name": "candidate-b"}).json()
    active = client.post(
        f"/api/v1/learning/models/{first['model_id']}/promote",
        json={"actor": "operator"},
    )
    assert active.status_code == 200, active.text
    assert active.json()["status"] == "ACTIVE"
    active2 = client.post(
        f"/api/v1/learning/models/{second['model_id']}/promote",
        json={"actor": "operator"},
    )
    assert active2.json()["metrics"]["previous_model_id"] == first["model_id"]
    rolled = client.post("/api/v1/learning/models/rollback", json={"actor": "operator"})
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["active"]["model_id"] == first["model_id"]

    paths = set(client.get("/openapi.json").json()["paths"])
    forbidden = [
        path for path in paths if any(token in path for token in ("order", "trade", "position", "buy", "sell"))
    ]
    assert forbidden == []
