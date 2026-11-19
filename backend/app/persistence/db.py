"""SQLite persistence for KBMTI.

A tiny threaded-friendly wrapper: every operation opens its own connection, which
keeps the local single-user workload simple and avoids cross-thread handle issues.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_candles (
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        timestamp_utc INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        tick_volume INTEGER NOT NULL DEFAULT 0,
        spread INTEGER NOT NULL DEFAULT 0,
        real_volume INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'mt5',
        PRIMARY KEY (symbol, timeframe, timestamp_utc, source)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timestamp_utc INTEGER NOT NULL,
        bid REAL,
        ask REAL,
        last REAL,
        source TEXT NOT NULL DEFAULT 'mt5'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_market_ticks_symbol_time ON market_ticks (symbol, timestamp_utc)",
    """
    CREATE TABLE IF NOT EXISTS signal_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        timestamp_utc INTEGER NOT NULL,
        label TEXT NOT NULL,
        direction TEXT NOT NULL,
        score REAL NOT NULL,
        engine TEXT NOT NULL,
        freshness TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        invalidation_json TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_signal_symbol_time ON signal_snapshots (symbol, timeframe, timestamp_utc)",
    """
    CREATE TABLE IF NOT EXISTS indicator_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        timestamp_utc INTEGER NOT NULL,
        name TEXT NOT NULL,
        parameters_json TEXT NOT NULL,
        value_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_runs (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        model_id TEXT NOT NULL,
        tokenizer_id TEXT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        created_at TEXT NOT NULL,
        input_last_bar_at INTEGER,
        input_candle_count INTEGER NOT NULL DEFAULT 0,
        horizon INTEGER NOT NULL DEFAULT 0,
        latency_ms REAL,
        runtime TEXT,
        status TEXT NOT NULL,
        warnings_json TEXT NOT NULL DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_candles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forecast_run_id TEXT NOT NULL REFERENCES forecast_runs (id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        timestamp_utc INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_forecast_candles_run ON forecast_candles (forecast_run_id, sequence)",
    """
    CREATE TABLE IF NOT EXISTS forecast_evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forecast_run_id TEXT NOT NULL REFERENCES forecast_runs (id) ON DELETE CASCADE,
        step INTEGER NOT NULL,
        target_ts INTEGER NOT NULL,
        actual_open REAL,
        actual_high REAL,
        actual_low REAL,
        actual_close REAL NOT NULL,
        predicted_open REAL,
        predicted_high REAL,
        predicted_low REAL,
        predicted_close REAL NOT NULL,
        open_abs_error REAL,
        high_abs_error REAL,
        low_abs_error REAL,
        abs_error REAL NOT NULL,
        pct_error REAL NOT NULL,
        predicted_direction TEXT,
        actual_direction TEXT,
        direction_correct INTEGER NOT NULL,
        success INTEGER,
        in_band INTEGER NOT NULL,
        evaluated_at TEXT NOT NULL,
        UNIQUE (forecast_run_id, step)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_forecast_evaluations_run ON forecast_evaluations (forecast_run_id, step)",
    """
    CREATE TABLE IF NOT EXISTS chat_conversations (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES chat_conversations (id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        context_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages (conversation_id, created_at)",
    # -- KIE (Phase B): additive tables, nothing existing is altered.
    """
    CREATE TABLE IF NOT EXISTS kie_runs (
        id TEXT PRIMARY KEY,
        mode TEXT NOT NULL,
        backend TEXT NOT NULL,
        model TEXT,
        status TEXT NOT NULL,
        finish TEXT,
        cancelled INTEGER NOT NULL DEFAULT 0,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        ttft_ms REAL,
        tok_per_s REAL,
        total_ms REAL,
        prompt_truncated INTEGER NOT NULL DEFAULT 0,
        request_chars INTEGER NOT NULL DEFAULT 0,
        answer_chars INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kie_tool_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES kie_runs (id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        arguments_json TEXT NOT NULL DEFAULT '{}',
        ok INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        duration_ms REAL,
        truncated INTEGER NOT NULL DEFAULT 0,
        confirmed_by TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_kie_runs_created ON kie_runs (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_kie_tool_calls_run ON kie_tool_calls (run_id)",
    # -- Market intelligence (Phase 1): immutable, auditable snapshot records.
    """
    CREATE TABLE IF NOT EXISTS market_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        provider TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        data_as_of TEXT NOT NULL,
        is_stale INTEGER NOT NULL DEFAULT 0,
        feature_version TEXT NOT NULL,
        validation_status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_market_snapshots_scope "
    "ON market_snapshots (symbol, timeframe, data_as_of DESC)",
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            self._ensure_candle_source_primary_key(conn)
            self._ensure_forecast_output_column(conn)
            self._ensure_evaluation_columns(conn)
            conn.commit()

    @staticmethod
    def _ensure_forecast_output_column(conn: sqlite3.Connection) -> None:
        """Store the complete PATRON payload alongside the display candles."""
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(forecast_runs)").fetchall()}
        if columns and "output_json" not in columns:
            conn.execute("ALTER TABLE forecast_runs ADD COLUMN output_json TEXT")

    @staticmethod
    def _ensure_evaluation_columns(conn: sqlite3.Connection) -> None:
        """Add candle-level OHLC/direction fields without losing prior evaluations."""
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(forecast_evaluations)").fetchall()
        }
        additions = {
            "actual_open": "REAL",
            "actual_high": "REAL",
            "actual_low": "REAL",
            "predicted_open": "REAL",
            "predicted_high": "REAL",
            "predicted_low": "REAL",
            "open_abs_error": "REAL",
            "high_abs_error": "REAL",
            "low_abs_error": "REAL",
            "predicted_direction": "TEXT",
            "actual_direction": "TEXT",
            "success": "INTEGER",
        }
        for name, sql_type in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE forecast_evaluations ADD COLUMN {name} {sql_type}")
        # Old rows only had close/direction-relative-to-reference data. Preserve
        # them but make the success count explicit.
        conn.execute("UPDATE forecast_evaluations SET success = direction_correct WHERE success IS NULL")

    @staticmethod
    def _ensure_candle_source_primary_key(conn: sqlite3.Connection) -> None:
        """Migrate pre-provider databases so Binance and MT5 rows stay separate."""
        columns = conn.execute("PRAGMA table_info(market_candles)").fetchall()
        primary_keys = {str(row[1]) for row in columns if int(row[5] or 0) > 0}
        if not columns or "source" in primary_keys:
            return
        conn.execute("ALTER TABLE market_candles RENAME TO market_candles_legacy")
        conn.execute(
            """
            CREATE TABLE market_candles (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp_utc INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                tick_volume INTEGER NOT NULL DEFAULT 0,
                spread INTEGER NOT NULL DEFAULT 0,
                real_volume INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'mt5',
                PRIMARY KEY (symbol, timeframe, timestamp_utc, source)
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO market_candles "
            "(symbol, timeframe, timestamp_utc, open, high, low, close, tick_volume, spread, real_volume, source) "
            "SELECT symbol, timeframe, timestamp_utc, open, high, low, close, tick_volume, spread, real_volume, "
            "COALESCE(source, 'mt5') FROM market_candles_legacy"
        )
        conn.execute("DROP TABLE market_candles_legacy")
        logger = __import__("logging").getLogger(__name__)
        logger.info("Migrated market_candles to provider-aware primary key")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.connection() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        if not rows:
            return 0
        with self.connection() as conn:
            cursor = conn.executemany(sql, rows)
            conn.commit()
            return cursor.rowcount

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in (
            "market_candles",
            "market_ticks",
            "signal_snapshots",
            "forecast_runs",
            "forecast_candles",
            "forecast_evaluations",
            "chat_conversations",
            "chat_messages",
        ):
            row = self.query_one(f"SELECT COUNT(*) AS total FROM {table}")
            counts[table] = int(row["total"]) if row else 0
        return counts

    def integrity_check(self) -> str:
        row = self.query_one("PRAGMA integrity_check")
        return str(row["integrity_check"]) if row else "unknown"

    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0
