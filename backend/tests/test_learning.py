from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.evaluation.walk_forward import build_windows
from app.learning.backtest import Backtester
from app.learning.contracts import BacktestConfig, DatasetPrepareRequest, ModelRegisterRequest
from app.learning.dataset import DatasetBuilder
from app.learning.repository import LearningRepository
from app.learning.service import LearningService
from app.persistence.db import Database
from app.persistence.repositories import MarketSnapshotRepository


def _snapshot(index: int) -> dict:
    at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * index)
    return {
        "snapshot_id": f"s{index:03d}",
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


def test_dataset_split_and_manifest_are_leakage_safe() -> None:
    builder = DatasetBuilder()
    manifest = builder.build([_snapshot(i) for i in range(60)], purge=2)
    assert manifest.audit.valid is True
    assert manifest.audit.train_cases > 0
    assert manifest.audit.validation_cases > 0
    assert manifest.audit.test_cases > 0
    assert manifest.audit.purge_cases == 4
    train_times = [case.data_as_of for case in manifest.cases if case.split.value == "TRAIN"]
    test_times = [case.data_as_of for case in manifest.cases if case.split.value == "TEST"]
    assert max(train_times) < min(test_times)
    assert manifest.manifest_hash == builder.build([_snapshot(i) for i in range(60)], purge=2).manifest_hash
    assert manifest.summary["leakage_control"]


def test_duplicate_and_invalid_datasets_are_blocked() -> None:
    rows = [_snapshot(i) for i in range(40)]
    rows.append(_snapshot(10))
    manifest = DatasetBuilder().build(rows)
    assert manifest.audit.valid is False
    assert any("duplicate" in error for error in manifest.audit.errors)
    rows = [_snapshot(i) for i in range(40)]
    rows[0]["validation_status"] = "INVALID"
    blocked = DatasetBuilder().build(rows)
    assert blocked.status == "BLOCKED"


def test_walk_forward_windows_preserve_order_and_gaps() -> None:
    windows = build_windows(100, purge=3, embargo=2)
    window = windows[0]
    assert window.train_start == 0
    assert window.train_end < window.validation_start
    assert window.validation_end < window.test_start
    assert window.test_end == 100
    assert window.validation_start - window.train_end == 5


def test_backtest_reports_chronological_splits_and_metrics() -> None:
    candles = []
    price = 30000.0
    start = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    closes: list[float] = []
    for _cycle in range(30):
        for _ in range(16):
            price += 12.0
            closes.append(price)
        for _ in range(4):
            price -= 8.0
            closes.append(price)
    previous = closes[0] - 12.0
    for index, close in enumerate(closes):
        open_ = previous
        high = max(open_, close) + 5.0 + (index % 3)
        low = min(open_, close) - 4.0 - (index % 2)
        candles.append(
            {
                "time": start + index * 900,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
            }
        )
        previous = close
    report = Backtester().run(
        candles,
        config=BacktestConfig(window_bars=300, max_hold_bars=8, train_fraction=0.6, validation_fraction=0.2),
    )
    assert report.status == "COMPLETE"
    assert report.windows["train"]["count"] > 0
    assert report.windows["test"]["count"] > 0
    assert "not used for parameter selection" in report.sealed_test_note
    assert report.overall.trades >= 0
    if report.overall.trades:
        assert report.overall.expectancy_r is not None
        assert report.overall.by_direction
        assert report.overall.sample_warning


def test_learning_service_cannot_fabricate_a_dataset(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        patron_autoload=False,
        patron_checkpoint=tmp_path / "missing.pt",
        patron_warmup_path=tmp_path / "missing.parquet",
    )
    database = Database(settings.db_path)
    database.initialize()
    service = LearningService(
        repository=LearningRepository(database),
        snapshots=MarketSnapshotRepository(database),
    )
    with pytest.raises(Exception, match="No market snapshots"):
        service.prepare_dataset(DatasetPrepareRequest())
    assert service.status().datasets == 0


def test_model_promotion_requires_actor_and_rollback_restores_previous(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        patron_autoload=False,
        patron_checkpoint=tmp_path / "missing.pt",
        patron_warmup_path=tmp_path / "missing.parquet",
    )
    database = Database(settings.db_path)
    database.initialize()
    service = LearningService(repository=LearningRepository(database))
    first = service.register_model(ModelRegisterRequest(name="adapter-a", metrics={"score": 1}))
    second = service.register_model(ModelRegisterRequest(name="adapter-b", metrics={"score": 2}))
    with pytest.raises(Exception, match="operator identity"):
        service.promote_model(first["model_id"], " ")
    active = service.promote_model(first["model_id"], "operator")
    assert active["status"] == "ACTIVE"
    active2 = service.promote_model(second["model_id"], "operator")
    assert active2["metrics"]["previous_model_id"] == first["model_id"]
    rolled = service.rollback_model("operator")
    assert rolled["active"]["model_id"] == first["model_id"]
