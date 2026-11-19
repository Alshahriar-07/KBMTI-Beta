from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from app.core.config import Settings
from app.core.errors import ApiError

torch = pytest.importorskip("torch")
pytest.importorskip("patron")

from patron.config import load_config  # noqa: E402
from patron.features.scaler import RobustFeatureScaler  # noqa: E402
from patron.features.schema import FEATURE_ORDER  # noqa: E402
from patron.models.patron_net import build_model, count_parameters  # noqa: E402

from app.patron.service import PatronInferenceService  # noqa: E402

PATRON_CONFIG = Path(__file__).resolve().parents[2] / "PATRON" / "configs" / "model_config.yaml"


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A structurally valid checkpoint with untrained weights (tests only)."""

    path = tmp_path_factory.mktemp("patron") / "best.pt"
    cfg = load_config(PATRON_CONFIG)
    model = build_model(cfg)
    assert count_parameters(model) == 272_618
    scaler = RobustFeatureScaler.fit(
        np.random.default_rng(0).normal(size=(200, len(FEATURE_ORDER))),
        feature_order=FEATURE_ORDER,
        metadata={"fit_split": "test-fixture"},
    )
    torch.save(
        {
            "model_state": model.state_dict(),
            "config": cfg.to_dict(),
            "feature_order": list(FEATURE_ORDER),
            "sequence_length": 96,
            "horizon": 6,
            "quantiles": [0.1, 0.5, 0.9],
            "scaler": scaler.to_dict(),
            "epoch": 1,
            "best_epoch": 1,
            "val_loss": 0.0,
        },
        path,
    )
    return path


@pytest.fixture
def service(checkpoint: Path, tmp_path: Path) -> PatronInferenceService:
    settings = Settings(
        data_dir=tmp_path,
        patron_autoload=False,
        patron_checkpoint=checkpoint,
        patron_config_path=PATRON_CONFIG,
        patron_warmup_path=tmp_path / "missing-warmup.parquet",
        patron_threads=2,
    )
    return PatronInferenceService(settings)


def _rows(count: int = 480) -> list[dict]:
    step = 900
    end = int(time.time() // step) * step
    start = end - count * step
    rng = np.random.default_rng(7)
    close = 60_000.0
    rows: list[dict] = []
    for index in range(count):
        open_price = close
        close = max(1000.0, open_price + rng.normal(0, 12))
        high = max(open_price, close) + abs(rng.normal(0, 6))
        low = min(open_price, close) - abs(rng.normal(0, 6))
        open_ms = (start + index * step) * 1000
        rows.append(
            {
                "open_time_ms": open_ms,
                "close_time_ms": open_ms + step * 1000,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": float(abs(rng.normal(20, 5)) + 1),
                "trades": 100,
            }
        )
    return rows


def test_model_loads_once_and_reports_ready(service: PatronInferenceService) -> None:
    status = service.ensure_loaded()
    assert status["state"] == "READY"
    assert status["ready"] is True
    assert status["trainable_parameters"] == 272_618
    assert status["checkpoint_exists"] is True
    loaded_at = status["loaded_at"]

    again = service.ensure_loaded()
    assert again["loaded_at"] == loaded_at
    assert again["load_ms"] == status["load_ms"]


def test_health_and_info_expose_real_contract(service: PatronInferenceService) -> None:
    service.ensure_loaded()
    health = service.health()
    assert health["status"] == "PASS"
    assert health["ready"] is True
    info = service.info()
    assert info["contract"]["input_candles"] == 96
    assert info["contract"]["warmup_bars"] == 384
    assert info["contract"]["horizon_candles"] == 6
    assert info["capabilities"]["chat"] is False


def test_inference_runs_on_480_contiguous_candles(service: PatronInferenceService) -> None:
    service.ensure_loaded()
    result = service.forecast_from_candles(_rows(480))
    assert result["status"] == "OK"
    assert result["symbol"] == "BTC/USDT"
    assert len(result["range_quantiles"]) == 6
    assert sum(result["barrier_probabilities"].values()) == pytest.approx(1.0, abs=1e-4)
    assert sum(result["momentum"]["class_probabilities"].values()) == pytest.approx(1.0, abs=1e-4)
    assert result["data_quality"]["closed_candles"] == 96
    assert service.status()["last_success_at"] is not None
    assert service.status()["inference_count"] == 1


def test_insufficient_history_is_rejected_without_inventing(service: PatronInferenceService) -> None:
    service.ensure_loaded()
    with pytest.raises(ApiError) as excinfo:
        service.forecast_from_candles(_rows(200))
    assert excinfo.value.code == "PATRON_HISTORY_INSUFFICIENT"


def test_gap_in_history_is_rejected(service: PatronInferenceService) -> None:
    service.ensure_loaded()
    rows = _rows(480)
    rows[100]["open_time_ms"] += 900_000
    with pytest.raises(ApiError) as excinfo:
        service.forecast_from_candles(rows)
    assert excinfo.value.code == "PATRON_HISTORY_GAP"
