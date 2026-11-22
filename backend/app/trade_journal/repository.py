"""SQLite persistence for append-only setup actions and journal records."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.persistence.db import Database


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class JournalRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- setup actions ------------------------------------------------------
    def insert_action(
        self, plan_id: str, action: str, actor: str, note: str | None, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        row = {
            "action_id": uuid.uuid4().hex,
            "plan_id": plan_id,
            "action": action,
            "actor": actor,
            "note": note,
            "created_at": _now(),
            "payload_json": json.dumps(payload or {"plan_id": plan_id, "action": action}, sort_keys=True),
        }
        self._db.execute(
            "INSERT INTO setup_actions (action_id, plan_id, action, actor, note, created_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            tuple(row.values()),
        )
        return row

    def actions(self, plan_id: str) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT action_id, plan_id, action, actor, note, created_at FROM setup_actions "
            "WHERE plan_id = ? ORDER BY created_at, action_id",
            (plan_id,),
        )

    def latest_action(self, plan_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT action_id, plan_id, action, actor, note, created_at FROM setup_actions "
            "WHERE plan_id = ? ORDER BY created_at DESC, action_id DESC LIMIT 1",
            (plan_id,),
        )

    # -- trades -------------------------------------------------------------
    def insert_trade(self, row: dict[str, Any]) -> None:
        columns = (
            "trade_id",
            "plan_id",
            "mode",
            "status",
            "direction",
            "symbol",
            "timeframe",
            "strategy_id",
            "strategy_version",
            "strategy_validation_status",
            "qwen_model_version",
            "planned_entry",
            "actual_entry",
            "stop_loss",
            "tp1",
            "tp2",
            "tp3",
            "exit_price",
            "fees",
            "slippage",
            "outcome",
            "r_multiple",
            "mfe",
            "mae",
            "opened_at",
            "closed_at",
            "notes",
            "payload_json",
            "created_at",
            "updated_at",
        )
        values = [row.get(column) for column in columns]
        self._db.execute(
            f"INSERT INTO journal_trades ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            values,
        )

    def update_trade(self, trade_id: str, updates: dict[str, Any]) -> bool:
        allowed = {
            "status",
            "actual_entry",
            "exit_price",
            "fees",
            "slippage",
            "outcome",
            "r_multiple",
            "mfe",
            "mae",
            "closed_at",
            "notes",
            "updated_at",
            "payload_json",
        }
        fields = [(key, value) for key, value in updates.items() if key in allowed]
        if not fields:
            return False
        assignments = ", ".join(f"{key} = ?" for key, _ in fields)
        values = [value for _, value in fields]
        values.extend([_now(), trade_id])
        rowcount = self._db.execute(
            f"UPDATE journal_trades SET {assignments}, updated_at = ? WHERE trade_id = ?", values
        )
        return rowcount == 1

    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        return self._db.query_one("SELECT * FROM journal_trades WHERE trade_id = ?", (trade_id,))

    def list_trades(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        if status:
            return self._db.query(
                "SELECT * FROM journal_trades WHERE status = ? ORDER BY opened_at DESC, trade_id DESC LIMIT ?",
                (status, limit),
            )
        return self._db.query(
            "SELECT * FROM journal_trades ORDER BY opened_at DESC, trade_id DESC LIMIT ?", (limit,)
        )

    def count_trades(self, status: str | None = None) -> int:
        row = (
            self._db.query_one(
                "SELECT COUNT(*) AS total FROM journal_trades WHERE status = ?", (status,)
            )
            if status
            else self._db.query_one("SELECT COUNT(*) AS total FROM journal_trades")
        )
        return int(row["total"]) if row else 0

    # -- append-only events -------------------------------------------------
    def insert_event(
        self,
        trade_id: str,
        event_type: str,
        *,
        price: str | None,
        note: str | None,
        occurred_at: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "event_id": uuid.uuid4().hex,
            "trade_id": trade_id,
            "event_type": event_type,
            "price": price,
            "note": note,
            "occurred_at": occurred_at,
            "payload_json": json.dumps(payload or {}, sort_keys=True),
            "created_at": _now(),
        }
        self._db.execute(
            "INSERT INTO journal_events (event_id, trade_id, event_type, price, note, occurred_at, "
            "payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(row.values()),
        )
        return row

    def events(self, trade_id: str) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT event_id, trade_id, event_type, price, note, occurred_at, created_at "
            "FROM journal_events WHERE trade_id = ? ORDER BY rowid",
            (trade_id,),
        )

    # -- reviews ------------------------------------------------------------
    def upsert_review(
        self,
        trade_id: str,
        *,
        status: str,
        reviewer: str,
        note: str | None,
        findings: list[dict[str, Any]],
        dataset_eligible: bool,
    ) -> dict[str, Any]:
        now = _now()
        existing = self._db.query_one("SELECT created_at FROM outcome_reviews WHERE trade_id = ?", (trade_id,))
        created = existing["created_at"] if existing else now
        self._db.execute(
            "INSERT INTO outcome_reviews (trade_id, status, reviewer, note, findings_json, dataset_eligible, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(trade_id) DO UPDATE SET status = excluded.status, reviewer = excluded.reviewer, "
            "note = excluded.note, findings_json = excluded.findings_json, "
            "dataset_eligible = excluded.dataset_eligible, updated_at = excluded.updated_at",
            (
                trade_id,
                status,
                reviewer,
                note,
                json.dumps(findings, separators=(",", ":")),
                1 if dataset_eligible else 0,
                created,
                now,
            ),
        )
        return self.get_review(trade_id) or {}

    def get_review(self, trade_id: str) -> dict[str, Any] | None:
        row = self._db.query_one("SELECT * FROM outcome_reviews WHERE trade_id = ?", (trade_id,))
        if row:
            row["findings"] = json.loads(row.pop("findings_json"))
            row["dataset_eligible"] = bool(row["dataset_eligible"])
        return row

    def approved_cases(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT r.* FROM outcome_reviews r WHERE r.status = 'APPROVED_FOR_DATASET' "
            "AND r.dataset_eligible = 1 ORDER BY r.updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        for row in rows:
            row["findings"] = json.loads(row.pop("findings_json"))
            row["dataset_eligible"] = bool(row["dataset_eligible"])
        return rows


__all__ = ["JournalRepository"]
