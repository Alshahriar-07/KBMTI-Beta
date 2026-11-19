"""Repository helpers on top of the SQLite database."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.market_data.candles import Candle
from app.persistence.db import Database


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self._db.query_one("SELECT value FROM app_settings WHERE key = ?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value), utc_now_iso()),
        )

    def all(self) -> dict[str, Any]:
        rows = self._db.query("SELECT key, value FROM app_settings")
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = row["value"]
        return result


class CandleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert_many(self, symbol: str, timeframe: str, candles: Iterable[Candle], source: str = "mt5") -> int:
        rows = [
            (
                symbol,
                timeframe,
                candle.time,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                int(candle.tick_volume),
                int(candle.spread),
                int(candle.real_volume),
                source,
            )
            for candle in candles
        ]
        return self._db.executemany(
            "INSERT INTO market_candles "
            "(symbol, timeframe, timestamp_utc, open, high, low, close, tick_volume, spread, real_volume, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol, timeframe, timestamp_utc, source) DO UPDATE SET "
            "open = excluded.open, high = excluded.high, low = excluded.low, close = excluded.close, "
            "tick_volume = excluded.tick_volume, spread = excluded.spread, real_volume = excluded.real_volume",
            rows,
        )

    def recent(self, symbol: str, timeframe: str, limit: int = 500, source: str = "mt5") -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT timestamp_utc, open, high, low, close, tick_volume, spread, real_volume, source "
            "FROM market_candles WHERE symbol = ? AND timeframe = ? AND source = ? "
            "ORDER BY timestamp_utc DESC LIMIT ?",
            (symbol, timeframe, source, limit),
        )
        return list(reversed(rows))

    def count(self, symbol: str, timeframe: str, source: str = "mt5") -> int:
        row = self._db.query_one(
            "SELECT COUNT(*) AS total FROM market_candles WHERE symbol = ? AND timeframe = ? AND source = ?",
            (symbol, timeframe, source),
        )
        return int(row["total"]) if row else 0

    def delete_before(self, cutoff_epoch: int) -> int:
        return self._db.execute("DELETE FROM market_candles WHERE timestamp_utc < ?", (cutoff_epoch,))


class TickRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(self, symbol: str, timestamp: int, bid: float | None, ask: float | None, last: float | None) -> None:
        self._db.execute(
            "INSERT INTO market_ticks (symbol, timestamp_utc, bid, ask, last) VALUES (?, ?, ?, ?, ?)",
            (symbol, timestamp, bid, ask, last),
        )

    def delete_before(self, cutoff_epoch: int) -> int:
        return self._db.execute("DELETE FROM market_ticks WHERE timestamp_utc < ?", (cutoff_epoch,))


class SignalRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(self, snapshot: dict[str, Any]) -> int:
        return self._db.execute(
            "INSERT INTO signal_snapshots "
            "(symbol, timeframe, timestamp_utc, label, direction, score, engine, freshness, evidence_json, invalidation_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot["symbol"],
                snapshot["timeframe"],
                snapshot["timestamp_utc"],
                snapshot["label"],
                snapshot["direction"],
                float(snapshot["score"]),
                snapshot["engine"],
                snapshot["freshness"],
                json.dumps(snapshot.get("evidence", [])),
                json.dumps(snapshot.get("invalidation", [])),
            ),
        )

    def recent(self, limit: int = 50, symbol: str | None = None) -> list[dict[str, Any]]:
        if symbol:
            rows = self._db.query(
                "SELECT * FROM signal_snapshots WHERE symbol = ? ORDER BY timestamp_utc DESC LIMIT ?",
                (symbol, limit),
            )
        else:
            rows = self._db.query(
                "SELECT * FROM signal_snapshots ORDER BY timestamp_utc DESC LIMIT ?", (limit,)
            )
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json") or "[]")
            row["invalidation"] = json.loads(row.pop("invalidation_json") or "[]")
        return rows


class ForecastRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def insert_run(self, run: dict[str, Any]) -> str:
        run_id = run.get("id") or uuid.uuid4().hex
        self._db.execute(
            "INSERT INTO forecast_runs "
            "(id, provider, model_id, tokenizer_id, symbol, timeframe, created_at, input_last_bar_at, "
            " input_candle_count, horizon, latency_ms, runtime, status, warnings_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                run["provider"],
                run["model_id"],
                run.get("tokenizer_id"),
                run["symbol"],
                run["timeframe"],
                run.get("created_at") or utc_now_iso(),
                run.get("input_last_bar_at"),
                int(run.get("input_candle_count") or 0),
                int(run.get("horizon") or 0),
                run.get("latency_ms"),
                run.get("runtime"),
                run.get("status", "pending"),
                json.dumps(run.get("warnings", [])),
            ),
        )
        return run_id

    def insert_output(self, run_id: str, payload: dict[str, Any]) -> None:
        self._db.execute(
            "UPDATE forecast_runs SET output_json = ? WHERE id = ?",
            (json.dumps(payload), run_id),
        )

    def insert_candles(self, run_id: str, candles: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                run_id,
                index,
                candle["time"],
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
            )
            for index, candle in enumerate(candles)
        ]
        self._db.executemany(
            "INSERT INTO forecast_candles (forecast_run_id, sequence, timestamp_utc, open, high, low, close) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT id, provider, model_id, tokenizer_id, symbol, timeframe, created_at, "
            "input_last_bar_at, input_candle_count, horizon, latency_ms, runtime, status, warnings_json "
            "FROM forecast_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        for row in rows:
            row["warnings"] = json.loads(row.pop("warnings_json") or "[]")
        return rows

    def latest_run(self) -> dict[str, Any] | None:
        rows = self.list_runs(limit=1)
        return self.get_run(rows[0]["id"]) if rows else None

    def successful_for_bar(
        self, symbol: str, timeframe: str, input_last_bar_at: int
    ) -> dict[str, Any] | None:
        """Return the immutable forecast already stored for this closed bar."""
        row = self._db.query_one(
            "SELECT id FROM forecast_runs WHERE symbol = ? AND timeframe = ? "
            "AND input_last_bar_at = ? AND status = 'ok' ORDER BY created_at DESC LIMIT 1",
            (symbol, timeframe, int(input_last_bar_at)),
        )
        return self.get_run(row["id"]) if row else None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._db.query_one("SELECT * FROM forecast_runs WHERE id = ?", (run_id,))
        if not row:
            return None
        row["warnings"] = json.loads(row.pop("warnings_json") or "[]")
        raw_output = row.pop("output_json", None)
        row["output"] = json.loads(raw_output) if raw_output else None
        row["candles"] = self._db.query(
            "SELECT sequence, timestamp_utc, open, high, low, close FROM forecast_candles "
            "WHERE forecast_run_id = ? ORDER BY sequence",
            (run_id,),
        )
        row["evaluation"] = self.evaluations(run_id)
        return row

    # ---------------------------------------------------------- evaluation
    def upsert_evaluation(self, run_id: str, rows: Iterable[dict[str, Any]]) -> int:
        payload = [
            (
                run_id,
                int(row["step"]),
                int(row["target_ts"]),
                float(row["actual_open"]),
                float(row["actual_high"]),
                float(row["actual_low"]),
                float(row["actual_close"]),
                float(row["predicted_open"]),
                float(row["predicted_high"]),
                float(row["predicted_low"]),
                float(row["predicted_close"]),
                float(row["open_abs_error"]),
                float(row["high_abs_error"]),
                float(row["low_abs_error"]),
                float(row["abs_error"]),
                float(row["pct_error"]),
                row["predicted_direction"],
                row["actual_direction"],
                1 if row["direction_correct"] else 0,
                1 if row["direction_correct"] else 0,
                1 if row["in_band"] else 0,
                row.get("evaluated_at") or utc_now_iso(),
            )
            for row in rows
        ]
        return self._db.executemany(
            "INSERT INTO forecast_evaluations "
            "(forecast_run_id, step, target_ts, actual_open, actual_high, actual_low, actual_close, "
            " predicted_open, predicted_high, predicted_low, predicted_close, open_abs_error, "
            " high_abs_error, low_abs_error, abs_error, pct_error, predicted_direction, "
            " actual_direction, direction_correct, success, in_band, evaluated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(forecast_run_id, step) DO UPDATE SET "
            "actual_open = excluded.actual_open, actual_high = excluded.actual_high, "
            "actual_low = excluded.actual_low, actual_close = excluded.actual_close, "
            "predicted_open = excluded.predicted_open, predicted_high = excluded.predicted_high, "
            "predicted_low = excluded.predicted_low, predicted_close = excluded.predicted_close, "
            "open_abs_error = excluded.open_abs_error, high_abs_error = excluded.high_abs_error, "
            "low_abs_error = excluded.low_abs_error, abs_error = excluded.abs_error, "
            "pct_error = excluded.pct_error, predicted_direction = excluded.predicted_direction, "
            "actual_direction = excluded.actual_direction, "
            "direction_correct = excluded.direction_correct, success = excluded.success, "
            "in_band = excluded.in_band, evaluated_at = excluded.evaluated_at",
            payload,
        )

    def evaluations(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT step, target_ts, actual_open, actual_high, actual_low, actual_close, "
            "predicted_open, predicted_high, predicted_low, predicted_close, "
            "open_abs_error, high_abs_error, low_abs_error, abs_error, pct_error, "
            "predicted_direction, actual_direction, direction_correct, success, in_band, "
            "evaluated_at FROM forecast_evaluations WHERE forecast_run_id = ? ORDER BY step",
            (run_id,),
        )
        for row in rows:
            row["direction_correct"] = bool(row["direction_correct"])
            row["success"] = bool(row["success"])
            row["in_band"] = bool(row["in_band"])
        return rows

    def evaluations_recent(self, limit: int = 24) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT e.forecast_run_id, e.step, e.target_ts, e.actual_open, e.actual_high, "
            "e.actual_low, e.actual_close, e.predicted_open, e.predicted_high, e.predicted_low, "
            "e.predicted_close, e.abs_error, e.pct_error, e.predicted_direction, "
            "e.actual_direction, e.direction_correct, e.success, e.evaluated_at, "
            "r.created_at, r.model_id FROM forecast_evaluations e "
            "JOIN forecast_runs r ON r.id = e.forecast_run_id "
            "WHERE r.symbol IN ('BTC/USDT', 'BTCUSDT') AND r.timeframe = 'M15' "
            "ORDER BY e.target_ts DESC, e.forecast_run_id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
        for row in rows:
            row["direction_correct"] = bool(row["direction_correct"])
            row["success"] = bool(row["success"])
            row["target_time"] = datetime.fromtimestamp(row["target_ts"], tz=UTC).isoformat()
        return rows

    def evaluation_summary(self) -> dict[str, Any]:
        row = self._db.query_one(
            "SELECT COUNT(*) AS steps, COUNT(DISTINCT forecast_run_id) AS runs, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successes, "
            "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failures, "
            "AVG(abs_error) AS close_mae, AVG(pct_error) AS close_mape, "
            "AVG(success) AS direction_accuracy, "
            "AVG(CASE WHEN actual_direction = 'bullish' THEN success END) AS bullish_accuracy, "
            "AVG(CASE WHEN actual_direction = 'bearish' THEN success END) AS bearish_accuracy, "
            "AVG(in_band) AS band_coverage FROM forecast_evaluations"
        )
        if not row or not row.get("steps"):
            return {
                "runs_evaluated": 0,
                "steps_evaluated": 0,
                "successful": 0,
                "failed": 0,
                "close_mae": None,
                "close_mape": None,
                "direction_accuracy": None,
                "bullish_accuracy": None,
                "bearish_accuracy": None,
                "band_coverage": None,
                "last_evaluated": None,
                "doji_threshold": 0.0002,
            }
        last = self._db.query_one(
            "SELECT target_ts, actual_direction, predicted_direction, success, abs_error, "
            "actual_close, predicted_close FROM forecast_evaluations "
            "ORDER BY target_ts DESC, evaluated_at DESC LIMIT 1"
        )
        last_evaluated = None
        if last:
            last_evaluated = dict(last)
            last_evaluated["success"] = bool(last_evaluated["success"])
            last_evaluated["target_time"] = datetime.fromtimestamp(
                last_evaluated["target_ts"], tz=UTC
            ).isoformat()
        return {
            "runs_evaluated": int(row["runs"] or 0),
            "steps_evaluated": int(row["steps"] or 0),
            "successful": int(row["successes"] or 0),
            "failed": int(row["failures"] or 0),
            "close_mae": round(float(row["close_mae"]), 4) if row["close_mae"] is not None else None,
            "close_mape": round(float(row["close_mape"]), 6) if row["close_mape"] is not None else None,
            "direction_accuracy": round(float(row["direction_accuracy"]), 4)
            if row["direction_accuracy"] is not None
            else None,
            "bullish_accuracy": round(float(row["bullish_accuracy"]), 4)
            if row["bullish_accuracy"] is not None
            else None,
            "bearish_accuracy": round(float(row["bearish_accuracy"]), 4)
            if row["bearish_accuracy"] is not None
            else None,
            "band_coverage": round(float(row["band_coverage"]), 4)
            if row["band_coverage"] is not None
            else None,
            "last_evaluated": last_evaluated,
            "doji_threshold": 0.0002,
        }


class ChatRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_conversation(self, title: str = "New conversation") -> dict[str, Any]:
        conversation_id = uuid.uuid4().hex
        now = utc_now_iso()
        self._db.execute(
            "INSERT INTO chat_conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, title, now, now),
        )
        return {"id": conversation_id, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT c.id, c.title, c.created_at, c.updated_at, "
            "(SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = c.id) AS message_count "
            "FROM chat_conversations c ORDER BY c.updated_at DESC"
        )

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT id, title, created_at, updated_at FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        )

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        self._db.execute(
            "UPDATE chat_conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, utc_now_iso(), conversation_id),
        )

    def touch_conversation(self, conversation_id: str) -> None:
        self._db.execute(
            "UPDATE chat_conversations SET updated_at = ? WHERE id = ?",
            (utc_now_iso(), conversation_id),
        )

    def delete_conversation(self, conversation_id: str) -> None:
        self._db.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,))
        self._db.execute("DELETE FROM chat_conversations WHERE id = ?", (conversation_id,))

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message_id = uuid.uuid4().hex
        now = utc_now_iso()
        self._db.execute(
            "INSERT INTO chat_messages (id, conversation_id, role, content, context_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, conversation_id, role, content, json.dumps(context) if context else None, now),
        )
        self.touch_conversation(conversation_id)
        return {
            "id": message_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "context": context,
            "created_at": now,
        }

    def list_messages(self, conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT id, conversation_id, role, content, context_json, created_at FROM chat_messages "
            "WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC LIMIT ?",
            (conversation_id, limit),
        )
        for row in rows:
            raw = row.pop("context_json")
            row["context"] = json.loads(raw) if raw else None
        return rows

    def clear_messages(self, conversation_id: str) -> None:
        self._db.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,))
        self.touch_conversation(conversation_id)


class MarketSnapshotRepository:
    """Append-only storage for immutable market-intelligence snapshots.

    The full typed payload is stored as JSON; the scalar columns exist only for
    scope/time queries and audit. Re-inserting the same deterministic snapshot id
    is a no-op, so restarts cannot duplicate a snapshot.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(
        self,
        *,
        snapshot_id: str,
        symbol: str,
        timeframe: str,
        provider: str,
        generated_at: str,
        data_as_of: str,
        is_stale: bool,
        feature_version: str,
        validation_status: str,
        payload: dict[str, Any],
    ) -> bool:
        rowcount = self._db.execute(
            "INSERT INTO market_snapshots "
            "(snapshot_id, symbol, timeframe, provider, generated_at, data_as_of, is_stale, "
            "feature_version, validation_status, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(snapshot_id) DO NOTHING",
            (
                snapshot_id,
                symbol,
                timeframe,
                provider,
                generated_at,
                data_as_of,
                1 if is_stale else 0,
                feature_version,
                validation_status,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                utc_now_iso(),
            ),
        )
        return rowcount == 1

    def latest(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        row = self._db.query_one(
            "SELECT payload_json, created_at FROM market_snapshots "
            "WHERE symbol = ? AND timeframe = ? ORDER BY data_as_of DESC, created_at DESC LIMIT 1",
            (symbol.upper(), timeframe.upper()),
        )
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        payload["persisted_at"] = row["created_at"]
        return payload

    def get(self, snapshot_id: str) -> dict[str, Any] | None:
        row = self._db.query_one(
            "SELECT payload_json, created_at FROM market_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        payload["persisted_at"] = row["created_at"]
        return payload

    def count(self, symbol: str | None = None, timeframe: str | None = None) -> int:
        if symbol and timeframe:
            row = self._db.query_one(
                "SELECT COUNT(*) AS total FROM market_snapshots WHERE symbol = ? AND timeframe = ?",
                (symbol.upper(), timeframe.upper()),
            )
        else:
            row = self._db.query_one("SELECT COUNT(*) AS total FROM market_snapshots")
        return int(row["total"]) if row else 0
