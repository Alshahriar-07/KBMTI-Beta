"""Controlled learning service: datasets, backtests, jobs and model promotion."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.errors import ApiError, NotFoundError, ValidationError
from app.learning.backtest import Backtester
from app.learning.contracts import (
    BacktestConfig,
    BacktestReport,
    DatasetManifest,
    DatasetPrepareRequest,
    LearningStatus,
    ModelRegisterRequest,
    TrainingJobRequest,
)
from app.learning.dataset import DatasetBuilder
from app.learning.repository import LearningRepository
from app.persistence.repositories import CandleRepository, MarketSnapshotRepository
from app.trade_journal.repository import JournalRepository


class LearningService:
    def __init__(
        self,
        *,
        repository: LearningRepository,
        snapshots: MarketSnapshotRepository | None = None,
        candles: CandleRepository | None = None,
        journal: JournalRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._snapshots = snapshots
        self._candles = candles
        self._journal = journal
        self._clock = clock or (lambda: datetime.now(UTC))
        self._datasets = DatasetBuilder()
        self._backtester = Backtester()

    def status(self) -> LearningStatus:
        approved = len(self._journal.approved_cases(limit=500)) if self._journal else 0
        reviewed = 0
        if self._journal:
            rows = self._journal.list_trades(limit=500)
            reviewed = sum(1 for row in rows if self._journal.get_review(row["trade_id"]) is not None)
        return LearningStatus(
            enabled=True,
            datasets=self._repository.count_datasets(),
            backtests=self._repository.count_backtests(),
            approved_outcomes=approved,
            paper_trade_gate={
                "reviewed_outcomes": reviewed,
                "approved_for_dataset": approved,
                "required_reviewed": 20,
                "required_days": 14,
                "passed": False,
                "reason": "The gate requires at least 20 reviewed cost-aware paper outcomes over 14+ days.",
            },
            training_available=False,
            training_reason=(
                "Local LoRA training is not enabled: the RX 580 / Vulkan inference stack has no "
                "verified PyTorch training path in this environment. See LORA_FEASIBILITY.md."
            ),
            generated_at=self._clock(),
        )

    def prepare_dataset(self, request: DatasetPrepareRequest) -> DatasetManifest:
        if self._snapshots is None:
            raise ApiError("DATASET_SOURCE_UNAVAILABLE", "Stored snapshots are unavailable.", 503)
        snapshots = self._snapshots.recent(limit=request.limit)
        if not snapshots:
            raise ValidationError(
                "No market snapshots are stored. Run /api/v1/market/analysis first; the builder "
                "does not fabricate cases."
            )
        manifest = self._datasets.build(
            snapshots,
            name=request.name,
            train_fraction=request.train_fraction,
            validation_fraction=request.validation_fraction,
            purge=request.purge,
        )
        self._repository.insert_dataset(manifest)
        return manifest

    def datasets(self, limit: int = 50) -> dict[str, Any]:
        rows = self._repository.datasets(limit)
        return {"datasets": rows, "count": len(rows)}

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        row = self._repository.get_dataset(dataset_id)
        if row is None:
            raise NotFoundError(f"Dataset '{dataset_id}' was not found.", {"dataset_id": dataset_id})
        return row

    def run_backtest(self, *, limit: int, config: BacktestConfig | None = None) -> BacktestReport:
        if self._candles is None:
            raise ApiError("CANDLE_SOURCE_UNAVAILABLE", "Stored candles are unavailable.", 503)
        cfg = config or BacktestConfig()
        rows = self._candles.recent(cfg.symbol, cfg.timeframe, limit=limit, source="binance")
        if len(rows) < cfg.window_bars + 20:
            fallback = self._candles.recent(cfg.symbol, cfg.timeframe, limit=limit, source="mt5")
            if len(fallback) > len(rows):
                rows = fallback
        if not rows:
            raise ValidationError(
                "No stored candles are available. Start the market feed or import BTCUSDT M15 "
                "history first; the backtester does not synthesize prices."
            )
        try:
            report = self._backtester.run(rows, config=cfg)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        self._repository.insert_backtest(report)
        return report

    def backtests(self, limit: int = 20) -> dict[str, Any]:
        rows = self._repository.backtests(limit)
        return {"backtests": rows, "count": len(rows)}

    def get_backtest(self, backtest_id: str) -> dict[str, Any]:
        row = self._repository.get_backtest(backtest_id)
        if row is None:
            raise NotFoundError(f"Backtest '{backtest_id}' was not found.", {"backtest_id": backtest_id})
        return row

    # -- model registry -----------------------------------------------------
    def models(self) -> dict[str, Any]:
        rows = self._repository.models()
        active = self._repository.active_model()
        return {
            "models": rows,
            "active": active,
            "count": len(rows),
            "note": (
                "No model can be promoted without an explicit operator action. The base Qwen "
                "weights are never overwritten by this registry."
            ),
        }

    def register_model(self, request: ModelRegisterRequest) -> dict[str, Any]:
        now = self._clock().isoformat()
        row = {
            "model_id": f"model_{uuid.uuid4().hex[:16]}",
            "name": request.name,
            "status": "CANDIDATE",
            "base_model": request.base_model,
            "artifact_path": request.artifact_path,
            "metrics": request.metrics,
            "approved_by": None,
            "created_at": now,
            "updated_at": now,
        }
        self._repository.insert_model(row)
        return self._repository.get_model(row["model_id"]) or row

    def promote_model(self, model_id: str, actor: str) -> dict[str, Any]:
        model = self._repository.get_model(model_id)
        if model is None:
            raise NotFoundError(f"Model '{model_id}' was not found.", {"model_id": model_id})
        if model["status"] not in {"CANDIDATE", "INACTIVE"}:
            raise ValidationError(f"Model status {model['status']} cannot be promoted.")
        if not actor.strip():
            raise ValidationError("An explicit operator identity is required for promotion.")
        previous = self._repository.active_model()
        if previous and previous["model_id"] != model_id:
            self._repository.update_model(previous["model_id"], {"status": "INACTIVE"})
            model["metrics"] = {**model["metrics"], "previous_model_id": previous["model_id"]}
        self._repository.update_model(
            model_id,
            {
                "status": "ACTIVE",
                "approved_by": actor.strip(),
                "metrics_json": json.dumps(model["metrics"], separators=(",", ":"), sort_keys=True),
                "updated_at": self._clock().isoformat(),
            },
        )
        return self._repository.get_model(model_id) or model

    def rollback_model(self, actor: str) -> dict[str, Any]:
        active = self._repository.active_model()
        if active is None:
            raise ValidationError("There is no active model to roll back.")
        previous_id = (active.get("metrics") or {}).get("previous_model_id")
        if not previous_id:
            raise ValidationError("The active model has no recorded rollback target.")
        previous = self._repository.get_model(str(previous_id))
        if previous is None:
            raise NotFoundError("The recorded rollback target no longer exists.")
        self._repository.update_model(active["model_id"], {"status": "INACTIVE", "approved_by": actor})
        self._repository.update_model(previous["model_id"], {"status": "ACTIVE", "approved_by": actor})
        return {
            "rolled_back_from": active["model_id"],
            "active": self._repository.get_model(previous["model_id"]),
            "actor": actor,
        }

    # -- jobs ---------------------------------------------------------------
    def request_job(self, request: TrainingJobRequest) -> dict[str, Any]:
        dataset = self._repository.get_dataset(request.dataset_id)
        if dataset is None:
            raise NotFoundError(f"Dataset '{request.dataset_id}' was not found.")
        if dataset.get("status") != "VALID":
            raise ValidationError("Only a VALID dataset can be attached to a training job.")
        now = self._clock().isoformat()
        row = {
            "job_id": f"job_{uuid.uuid4().hex[:16]}",
            "status": "AWAITING_APPROVAL",
            "dataset_id": request.dataset_id,
            "config": request.config,
            "requested_by": request.requested_by,
            "approved_by": None,
            "created_at": now,
            "updated_at": now,
        }
        self._repository.insert_job(row)
        return row

    def jobs(self, limit: int = 20) -> dict[str, Any]:
        rows = self._repository.jobs(limit)
        return {
            "jobs": rows,
            "count": len(rows),
            "note": "Jobs remain approval-gated and no local LoRA execution is enabled.",
        }

    def approve_job(self, job_id: str, actor: str) -> dict[str, Any]:
        job = self._repository.get_job(job_id)
        if job is None:
            raise NotFoundError(f"Training job '{job_id}' was not found.")
        if job["status"] != "AWAITING_APPROVAL":
            raise ValidationError(f"Job status {job['status']} cannot be approved here.")
        if not actor.strip():
            raise ValidationError("An explicit operator identity is required for approval.")
        self._repository.update_job(
            job_id,
            {
                "status": "APPROVED_NOT_RUN",
                "approved_by": actor.strip(),
                "updated_at": self._clock().isoformat(),
            },
        )
        return {
            "job": self._repository.get_job(job_id),
            "execution": "DISABLED",
            "reason": "Local LoRA training is not enabled on this hardware; approval does not start a run.",
        }


__all__ = ["LearningService"]
