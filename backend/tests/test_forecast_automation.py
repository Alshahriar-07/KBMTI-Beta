"""Closed-candle forecasting, immutable evaluation and restart recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.forecasting.automation import ForecastAutomation
from app.forecasting.base import ForecastOutput, ForecastRequest
from app.forecasting.service import DOJI_THRESHOLD, ForecastService, _direction
from app.market_data.candles import Candle
from app.persistence.db import Database
from app.persistence.repositories import ForecastRepository

START = 1_700_000_000
STEP = 900


def bar(index: int, open_: float, close: float) -> SimpleNamespace:
    return SimpleNamespace(
        open_time=START + index * STEP,
        open_time_ms=(START + index * STEP) * 1000,
        open=open_,
        high=max(open_, close) + 0.5,
        low=min(open_, close) - 0.5,
        close=close,
        trades=10,
        volume=5.0,
    )


def candle(index: int, open_: float, close: float) -> Candle:
    return Candle(
        time=START + index * STEP,
        open=open_,
        high=max(open_, close) + 0.5,
        low=min(open_, close) - 0.5,
        close=close,
    )


class FakeHistory:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.calls = 0

    def recent(
        self, symbol: str, interval: str, limit: int = 520, *, force: bool = False
    ) -> list[SimpleNamespace]:
        self.calls += 1
        return list(self.rows[-limit:])

    def range(
        self, symbol: str, interval: str, start_ms: int, end_ms: int | None = None
    ) -> list[SimpleNamespace]:
        rows = [row for row in self.rows if row.open_time_ms >= start_ms]
        if end_ms is not None:
            rows = [row for row in rows if row.open_time_ms < end_ms]
        return rows


class FakeProvider:
    provider_id = "patron"
    model_id = "patron-1.0.0"
    tokenizer_id = None

    def __init__(self, offsets: list[float] | None = None, ready: bool = True) -> None:
        self.offsets = offsets or [0.001] * 6
        self.ready = ready
        self.runs = 0

    def status(self) -> dict[str, Any]:
        return {
            "stage": 2,
            "provider": "patron",
            "state": "READY" if self.ready else "LOADING",
            "ai_available": self.ready,
            "model_id": self.model_id,
            "tokenizer_id": None,
            "horizon": 6,
            "message": "ready" if self.ready else "loading",
        }

    def run(self, request: ForecastRequest) -> ForecastOutput:
        self.runs += 1
        reference = float(request.candles[-1].close)
        last_time = request.candles[-1].time
        candles: list[Candle] = []
        previous = reference
        for index, offset in enumerate(self.offsets[: request.horizon], start=1):
            close = previous * (1.0 + offset)
            candles.append(
                Candle(
                    time=last_time + STEP * index,
                    open=previous,
                    high=max(previous, close) + 0.5,
                    low=min(previous, close) - 0.5,
                    close=close,
                )
            )
            previous = close
        quantiles = [
            {
                "step": index,
                "close": {"q10": offset - 0.01, "q50": offset, "q90": offset + 0.01},
            }
            for index, offset in enumerate(self.offsets[: request.horizon], start=1)
        ]
        return ForecastOutput(
            candles=candles,
            provider="patron",
            model_id=self.model_id,
            tokenizer_id=None,
            latency_ms=3.0,
            runtime="cpu",
            input_candle_count=len(request.candles),
            input_last_bar_at=last_time,
            metadata={
                "patron": {
                    "symbol": "BTC/USDT",
                    "range_quantiles": quantiles,
                },
                "reference_close": reference,
            },
        )


def build(
    tmp_path: Path,
    rows: list[SimpleNamespace],
    provider: FakeProvider | None = None,
) -> tuple[ForecastService, ForecastRepository, FakeHistory, FakeProvider, Settings]:
    db = Database(tmp_path / "forecast.db")
    db.initialize()
    repository = ForecastRepository(db)
    history = FakeHistory(rows)
    model = provider or FakeProvider()
    settings = Settings(
        data_dir=tmp_path / "data",
        forecast_auto_enabled=True,
        forecast_poll_seconds=5.0,
        patron_autoload=False,
        patron_checkpoint=tmp_path / "missing.pt",
        patron_warmup_path=tmp_path / "missing.parquet",
        patron_config_path=tmp_path / "missing.yaml",
    )
    service = ForecastService(provider=model, repository=repository, history=history)  # type: ignore[arg-type]
    return service, repository, history, model, settings


def seed_rows(count: int = 8) -> list[SimpleNamespace]:
    return [bar(index, 100.0 + index, 100.5 + index) for index in range(count)]


def test_direction_uses_explicit_doji_threshold() -> None:
    assert _direction(100.0, 100.5) == "bullish"
    assert _direction(100.0, 99.5) == "bearish"
    assert _direction(100.0, 100.0 + 100.0 * DOJI_THRESHOLD / 2) == "neutral"
    assert _direction(100.0, 100.0) == "neutral"


def test_automation_generates_once_per_closed_bar(tmp_path: Path) -> None:
    rows = seed_rows()
    service, repository, history, model, settings = build(tmp_path, rows)
    automation = ForecastAutomation(
        forecast=service, repository=repository, settings=settings
    )
    service.automation_status = automation.status

    first = automation.run_once()
    assert first["status"] == "forecast"
    assert model.runs == 1
    runs = repository.list_runs(limit=10)
    assert len(runs) == 1
    assert runs[0]["input_last_bar_at"] == rows[-1].open_time
    original = repository.get_run(runs[0]["id"])
    assert original is not None
    assert [c["close"] for c in original["candles"]] == pytest.approx(
        [rows[-1].close * (1.001 ** (step + 1)) for step in range(6)]
    )

    second = automation.run_once()
    assert second["status"] == "unchanged"
    assert model.runs == 1
    assert len(repository.list_runs(limit=10)) == 1
    assert service.status()["automation"]["running"] is False
    assert service.status()["automation"]["forecasts"] == 1

    # Only a newly closed bar triggers a new forecast.
    history.rows.append(bar(len(history.rows), 108.5, 109.0))
    third = automation.run_once()
    assert third["status"] == "forecast"
    assert model.runs == 2
    assert len(repository.list_runs(limit=10)) == 2


def test_notify_closed_collapses_duplicate_close_identities(tmp_path: Path) -> None:
    rows = seed_rows()
    service, repository, history, model, settings = build(tmp_path, rows)
    automation = ForecastAutomation(forecast=service, repository=repository, settings=settings)
    service.automation_status = automation.status

    bar_time = rows[-1].open_time
    assert automation.notify_closed(bar_time) is True
    assert automation.notify_closed(bar_time) is False
    assert automation.notify_closed(bar_time - STEP) is False

    assert automation.run_once()["status"] == "forecast"
    assert model.runs == 1
    assert automation.notify_closed(bar_time) is False

    history.rows.append(bar(len(history.rows), 108.5, 109.0))
    assert automation.notify_closed(history.rows[-1].open_time) is True
    assert automation.run_once()["status"] == "forecast"
    assert model.runs == 2


def test_forecast_event_sink_receives_the_persisted_run(tmp_path: Path) -> None:
    rows = seed_rows()
    service, repository, _history, _model, settings = build(tmp_path, rows)
    automation = ForecastAutomation(forecast=service, repository=repository, settings=settings)
    events: list[dict[str, Any]] = []
    service.set_event_sink(events.append)

    automation.run_once()

    assert len(events) == 1
    assert events[0]["type"] == "forecast"
    stored = repository.list_runs(limit=1)[0]
    assert events[0]["payload"]["id"] == stored["id"]
    assert events[0]["payload"]["input_last_bar_at"] == rows[-1].open_time


def test_evaluation_scores_ohlc_and_direction_not_proximity(tmp_path: Path) -> None:
    rows = seed_rows()
    # Forecasts: +1% bullish for every step.
    provider = FakeProvider(offsets=[0.01] * 6)
    service, repository, history, _model, settings = build(tmp_path, rows, provider)
    automation = ForecastAutomation(forecast=service, repository=repository, settings=settings)
    automation.run_once()
    run = repository.latest_run()
    assert run is not None
    predicted = {candle["sequence"]: candle for candle in run["candles"]}

    # Step 1 closes bullish, step 2 closes inside the doji threshold, step 3 is
    # left open (no matching actual candle).
    history.rows.append(bar(8, 108.0, 110.0))
    history.rows.append(bar(9, 110.0, 110.0 + 110.0 * DOJI_THRESHOLD / 2))
    automation.run_once()

    detail = repository.get_run(run["id"])
    assert detail is not None
    steps = {row["step"]: row for row in detail["evaluation"]}
    assert set(steps) == {1, 2}
    assert steps[1]["success"] is True
    assert steps[1]["predicted_direction"] == "bullish"
    assert steps[1]["actual_direction"] == "bullish"
    assert steps[1]["predicted_open"] == pytest.approx(float(predicted[0]["open"]))
    assert steps[1]["actual_open"] == 108.0
    assert steps[1]["actual_high"] == pytest.approx(110.5)
    assert steps[1]["open_abs_error"] == pytest.approx(abs(108.0 - predicted[0]["open"]))
    assert steps[2]["success"] is False
    assert steps[2]["actual_direction"] == "neutral"
    assert steps[2]["predicted_direction"] == "bullish"
    # A near predicted price must not create a win: only direction is scored.
    assert steps[2]["abs_error"] >= 0

    summary = repository.evaluation_summary()
    assert summary["steps_evaluated"] == 2
    assert summary["successful"] == 1
    assert summary["failed"] == 1
    assert summary["direction_accuracy"] == pytest.approx(0.5)
    assert summary["last_evaluated"]["success"] is False
    assert summary["doji_threshold"] == DOJI_THRESHOLD

    timeline = repository.evaluations_recent(limit=10)
    assert len(timeline) == 2
    assert timeline[0]["target_time"] == datetime.fromtimestamp(
        START + 9 * STEP, tz=UTC
    ).isoformat()


def test_restart_reuses_persisted_forecast_and_evaluates_pending(tmp_path: Path) -> None:
    rows = seed_rows()
    service, repository, history, model, settings = build(tmp_path, rows)
    automation = ForecastAutomation(forecast=service, repository=repository, settings=settings)
    automation.run_once()
    run_id = repository.list_runs(limit=1)[0]["id"]

    # Restart: a fresh service/automation over the same database.
    restarted_service = ForecastService(
        provider=model, repository=repository, history=history  # type: ignore[arg-type]
    )
    restarted = ForecastAutomation(
        forecast=restarted_service, repository=repository, settings=settings
    )
    restarted.run_once()
    assert model.runs == 1
    assert len(repository.list_runs(limit=10)) == 1

    # One of the stored targets closes while the app was running again.
    history.rows.append(bar(8, 108.0, 109.0))
    restarted.run_once()
    detail = repository.get_run(run_id)
    assert detail is not None
    assert [row["step"] for row in detail["evaluation"]] == [1]
    assert detail["evaluation"][0]["success"] is True
    # The new bar also produced the next immutable forecast.
    assert len(repository.list_runs(limit=10)) == 2


def test_automation_waits_for_model_without_writing_error_runs(tmp_path: Path) -> None:
    rows = seed_rows()
    service, repository, _history, _model, settings = build(
        tmp_path, rows, FakeProvider(ready=False)
    )
    automation = ForecastAutomation(forecast=service, repository=repository, settings=settings)
    result = automation.run_once()
    assert result["status"] == "model_waiting"
    assert result["waiting_for"]
    assert repository.list_runs(limit=10) == []


def test_live_and_timeline_endpoints_expose_the_workspace_payload(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        data_dir=tmp_path / "api",
        patron_autoload=False,
        patron_checkpoint=tmp_path / "missing.pt",
        patron_warmup_path=tmp_path / "missing.parquet",
        patron_config_path=tmp_path / "missing.yaml",
    )
    app = create_app(
        settings=settings,
        binance_history=FakeHistory(seed_rows(12)),  # type: ignore[arg-type]
        start_polling=False,
        configure_logs=False,
    )
    with TestClient(app) as client:
        live = client.get("/api/v1/forecast/live?limit=10")
        assert live.status_code == 200
        body = live.json()
        assert body["symbol"] == "BTC/USDT"
        assert body["timeframe"] == "M15"
        assert len(body["candles"]) == 10
        assert body["latest"] is None
        assert body["forming_candle"] is None
        assert body["market"]["live"] is True
        assert body["market"]["data_state"] != "live"
        assert body["status"]["automation"]["enabled"] is True
        assert body["status"]["automation"]["running"] is False

        timeline = client.get("/api/v1/forecast/timeline")
        assert timeline.status_code == 200
        assert timeline.json()["timeline"] == []

        history = client.get("/api/v1/forecast/history").json()
        assert history["timeline"] == []
        assert history["automation"]["enabled"] is True


def test_live_context_reports_binance_candles_and_pending_pipeline(tmp_path: Path) -> None:
    rows = seed_rows(12)
    service, repository, _history, _model, settings = build(tmp_path, rows)
    automation = ForecastAutomation(forecast=service, repository=repository, settings=settings)
    service.automation_status = automation.status
    automation.run_once()

    payload = service.live_context(limit=10)
    assert payload["symbol"] == "BTC/USDT"
    assert payload["timeframe"] == "M15"
    assert payload["bar_seconds"] == 900
    assert len(payload["candles"]) == 10
    assert payload["candles"][-1]["time"] == rows[-1].open_time
    assert payload["latest"]["id"] == repository.list_runs(limit=1)[0]["id"]
    assert payload["status"]["ai_available"] is True
    assert payload["status"]["automation"]["enabled"] is True
    assert payload["evaluation"]["steps_evaluated"] == 0
    assert payload["timeline"] == []
    assert payload["data_warning"] is None
