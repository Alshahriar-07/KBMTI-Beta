"""Persistence for datasets, backtests, training jobs and model versions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.persistence.db import Database


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class LearningRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def insert_dataset(self, manifest: Any) -> None:
        payload = manifest.model_dump(mode="json")
        self._db.execute(
            "INSERT INTO dataset_versions (dataset_id, name, manifest_hash, status, created_at, "
            "summary_json, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                manifest.dataset_id,
                manifest.name,
                manifest.manifest_hash,
                manifest.status,
                manifest.created_at.isoformat(),
                json.dumps(manifest.summary, separators=(",", ":"), sort_keys=True),
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
            ),
        )
        self._db.executemany(
            "INSERT INTO dataset_cases (dataset_id, case_id, split, data_as_of, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    manifest.dataset_id,
                    case.case_id,
                    case.split.value,
                    case.data_as_of.isoformat(),
                    json.dumps(case.model_dump(mode="json"), separators=(",", ":"), sort_keys=True),
                )
                for case in manifest.cases
            ],
        )

    def datasets(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT dataset_id, name, manifest_hash, status, created_at, summary_json "
            "FROM dataset_versions ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
        for row in rows:
            row["summary"] = json.loads(row.pop("summary_json"))
        return rows

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        row = self._db.query_one(
            "SELECT payload_json FROM dataset_versions WHERE dataset_id = ?", (dataset_id,)
        )
        return json.loads(row["payload_json"]) if row else None

    def count_datasets(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS total FROM dataset_versions")
        return int(row["total"]) if row else 0

    def insert_backtest(self, report: Any) -> None:
        payload = report.model_dump(mode="json")
        self._db.execute(
            "INSERT INTO backtest_runs (backtest_id, created_at, status, config_json, metrics_json, "
            "trades_json, warnings_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report.backtest_id,
                report.created_at.isoformat(),
                report.status,
                json.dumps(payload["config"], separators=(",", ":"), sort_keys=True),
                json.dumps(payload["metrics"], separators=(",", ":"), sort_keys=True),
                json.dumps(payload["trades"], separators=(",", ":"), sort_keys=True),
                json.dumps(payload["warnings"], separators=(",", ":")),
            ),
        )

    def backtests(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT backtest_id, created_at, status, metrics_json, warnings_json "
            "FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        )
        for row in rows:
            row["metrics"] = json.loads(row.pop("metrics_json"))
            row["warnings"] = json.loads(row.pop("warnings_json"))
        return rows

    def get_backtest(self, backtest_id: str) -> dict[str, Any] | None:
        row = self._db.query_one("SELECT * FROM backtest_runs WHERE backtest_id = ?", (backtest_id,))
        if not row:
            return None
        for key in ("config_json", "metrics_json", "trades_json", "warnings_json"):
            row[key.replace("_json", "")] = json.loads(row.pop(key))
        return row

    def count_backtests(self) -> int:
        row = self._db.query_one("SELECT COUNT(*) AS total FROM backtest_runs")
        return int(row["total"]) if row else 0

    # -- models -------------------------------------------------------------
    def insert_model(self, row: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT INTO model_versions (model_id, name, status, base_model, artifact_path, "
            "metrics_json, approved_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["model_id"],
                row["name"],
                row["status"],
                row["base_model"],
                row.get("artifact_path"),
                json.dumps(row.get("metrics") or {}, separators=(",", ":"), sort_keys=True),
                row.get("approved_by"),
                row["created_at"],
                row["updated_at"],
            ),
        )

    def models(self) -> list[dict[str, Any]]:
        rows = self._db.query("SELECT * FROM model_versions ORDER BY created_at DESC")
        for row in rows:
            row["metrics"] = json.loads(row.pop("metrics_json"))
        return rows

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        row = self._db.query_one("SELECT * FROM model_versions WHERE model_id = ?", (model_id,))
        if row:
            row["metrics"] = json.loads(row.pop("metrics_json"))
        return row

    def update_model(self, model_id: str, updates: dict[str, Any]) -> bool:
        allowed = {"status", "approved_by", "updated_at", "artifact_path", "metrics_json"}
        fields = [(key, value) for key, value in updates.items() if key in allowed]
        if not fields:
            return False
        assignments = ", ".join(f"{key} = ?" for key, _ in fields)
        values = [value for _, value in fields]
        values.extend([_now(), model_id])
        return self._db.execute(
            f"UPDATE model_versions SET {assignments}, updated_at = ? WHERE model_id = ?", values
        ) == 1

    def active_model(self) -> dict[str, Any] | None:
        row = self._db.query_one(
            "SELECT * FROM model_versions WHERE status = 'ACTIVE' ORDER BY updated_at DESC LIMIT 1"
        )
        if row:
            row["metrics"] = json.loads(row.pop("metrics_json"))
        return row

    def insert_job(self, row: dict[str, Any]) -> None:
        self._db.execute(
            "INSERT INTO training_jobs (job_id, status, dataset_id, config_json, requested_by, "
            "approved_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["job_id"],
                row["status"],
                row.get("dataset_id"),
                json.dumps(row.get("config") or {}, separators=(",", ":"), sort_keys=True),
                row["requested_by"],
                row.get("approved_by"),
                row["created_at"],
                row["updated_at"],
            ),
        )

    def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT * FROM training_jobs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        )
        for row in rows:
            row["config"] = json.loads(row.pop("config_json"))
        return rows

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._db.query_one("SELECT * FROM training_jobs WHERE job_id = ?", (job_id,))
        if row:
            row["config"] = json.loads(row.pop("config_json"))
        return row

    def update_job(self, job_id: str, updates: dict[str, Any]) -> bool:
        allowed = {"status", "approved_by", "updated_at"}
        fields = [(key, value) for key, value in updates.items() if key in allowed]
        if not fields:
            return False
        assignments = ", ".join(f"{key} = ?" for key, _ in fields)
        values = [value for _, value in fields]
        values.extend([_now(), job_id])
        return self._db.execute(
            f"UPDATE training_jobs SET {assignments}, updated_at = ? WHERE job_id = ?", values
        ) == 1


__all__ = ["LearningRepository"]
