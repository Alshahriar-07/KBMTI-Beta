"""Tool Engine: validate, authorise, execute, truncate, time-box.

Execution happens in a worker thread so a slow tool cannot hang the request forever. A
timed-out worker is abandoned rather than killed (Python cannot kill a thread) and the
result is reported as a timeout — never as success. Every result is truncated to the
spec's ``max_result_chars`` and returned as data; nothing here interprets model output.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.kie.contracts import ToolCall, ToolResult
from app.kie.tools.registry import ToolRegistry


class ToolEngine:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def execute(self, call: ToolCall, *, confirmed: bool = False) -> ToolResult:
        started = time.perf_counter()
        try:
            spec = self.registry.validate(call)
            self.registry.authorize(spec, confirmed=confirmed)
        except Exception as exc:  # noqa: BLE001 - validation/authorisation failures are results too
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                content="",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error=str(getattr(exc, "message", exc)),
            )

        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["value"] = self.registry.handler(call.name)(call.arguments)
            except Exception as exc:  # noqa: BLE001 - a tool failure is data, not a crash
                box["error"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=run, name=f"kie-tool-{call.name}", daemon=True)
        worker.start()
        worker.join(timeout=spec.timeout_s)
        duration = (time.perf_counter() - started) * 1000.0

        if worker.is_alive():
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                content="",
                duration_ms=duration,
                error=f"timeout after {spec.timeout_s:.0f}s",
            )
        if "error" in box:
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                content="",
                duration_ms=duration,
                error=str(box["error"]),
            )

        content, truncated = self._serialize(box.get("value"), spec.max_result_chars)
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            content=content,
            duration_ms=duration,
            truncated=truncated,
        )

    @staticmethod
    def _serialize(value: Any, limit: int) -> tuple[str, bool]:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
            except (TypeError, ValueError):
                text = str(value)
        if len(text) <= limit:
            return text, False
        # Mark the cut so the model cannot mistake a truncated payload for complete data.
        return text[: max(0, limit - 3)] + "...", True
