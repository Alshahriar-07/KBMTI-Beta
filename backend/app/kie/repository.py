"""Persistence for KIE runs and tool calls.

Additive on top of the existing SQLite file: two new tables (``kie_runs``,
``kie_tool_calls``) created by ``Database.initialize``. Chat conversations are *not*
touched — Phase B keeps ``/chat/*`` byte-compatible and stores KIE runs separately.
"""

from __future__ import annotations

import json
from typing import Any

from app.persistence.db import Database
from app.persistence.repositories import utc_now_iso


class KieRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------ runs
    def start_run(
        self,
        run_id: str,
        *,
        mode: str,
        backend: str,
        model: str | None,
        request_chars: int,
    ) -> None:
        self._db.execute(
            "INSERT INTO kie_runs (id, mode, backend, model, status, request_chars, created_at) "
            "VALUES (?, ?, ?, ?, 'running', ?, ?)",
            (run_id, mode, backend, model, int(request_chars), utc_now_iso()),
        )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        finish: str | None = None,
        cancelled: bool = False,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        ttft_ms: float | None = None,
        tok_per_s: float | None = None,
        total_ms: float | None = None,
        prompt_truncated: int = 0,
        answer_chars: int = 0,
        error: str | None = None,
    ) -> None:
        self._db.execute(
            "UPDATE kie_runs SET status = ?, finish = ?, cancelled = ?, prompt_tokens = ?, "
            "completion_tokens = ?, ttft_ms = ?, tok_per_s = ?, total_ms = ?, prompt_truncated = ?, "
            "answer_chars = ?, error = ?, completed_at = ? WHERE id = ?",
            (
                status,
                finish,
                1 if cancelled else 0,
                int(prompt_tokens),
                int(completion_tokens),
                ttft_ms,
                tok_per_s,
                total_ms,
                int(prompt_truncated),
                int(answer_chars),
                error,
                utc_now_iso(),
                run_id,
            ),
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._db.query_one("SELECT * FROM kie_runs WHERE id = ?", (run_id,))
        if not row:
            return None
        row["cancelled"] = bool(row["cancelled"])
        row["prompt_truncated"] = bool(row["prompt_truncated"])
        row["tool_calls"] = self.tool_calls(run_id)
        return row

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT id, mode, backend, model, status, finish, cancelled, prompt_tokens, "
            "completion_tokens, ttft_ms, tok_per_s, total_ms, created_at, completed_at "
            "FROM kie_runs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
        for row in rows:
            row["cancelled"] = bool(row["cancelled"])
        return rows

    # ------------------------------------------------------------ tool audit
    def record_tool_call(
        self,
        run_id: str,
        *,
        name: str,
        arguments: dict[str, Any],
        ok: bool,
        error: str | None,
        duration_ms: float,
        truncated: bool = False,
        confirmed_by: str | None = None,
    ) -> None:
        self._db.execute(
            "INSERT INTO kie_tool_calls "
            "(run_id, name, arguments_json, ok, error, duration_ms, truncated, confirmed_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                name,
                json.dumps(arguments, ensure_ascii=False, default=str),
                1 if ok else 0,
                error,
                float(duration_ms),
                1 if truncated else 0,
                confirmed_by,
                utc_now_iso(),
            ),
        )

    def tool_calls(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._db.query(
            "SELECT name, arguments_json, ok, error, duration_ms, truncated, confirmed_by, created_at "
            "FROM kie_tool_calls WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        for row in rows:
            row["arguments"] = json.loads(row.pop("arguments_json") or "{}")
            row["ok"] = bool(row["ok"])
            row["truncated"] = bool(row["truncated"])
        return rows
