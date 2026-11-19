"""Forecast orchestration, persistence and outcome evaluation.

The service runs the configured provider (PATRON), stores the input window and
the complete model payload, and scores matured forecasts against the realised
Binance candle. Predicted values are never substituted with history.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.errors import ForecastUnavailableError
from app.core.timeframes import Timeframe
from app.forecasting.base import (
    ForecastOutput,
    ForecastProvider,
    ForecastRequest,
    validate_forecast_output,
)
from app.market_data.binance_history import BinanceHistoryClient
from app.market_data.candles import Candle
from app.persistence.repositories import ForecastRepository

logger = logging.getLogger(__name__)

# A 15m candle is treated as directionally neutral when its body is at most
# 0.02% of the open. This keeps doji-like candles from being scored as wins by
# accident.
DOJI_THRESHOLD = 0.0002

HISTORY_MESSAGE = (
    "Each run stores the PATRON input window, the full model payload and the derived "
    "display candles. Matured runs are scored against the realised Binance candle."
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ForecastService:
    def __init__(
        self,
        provider: ForecastProvider,
        repository: ForecastRepository,
        history: BinanceHistoryClient | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self._history = history
        self._run_lock = threading.Lock()
        self._last_error: str | None = None
        self._event_sink: Callable[[dict[str, Any]], None] | None = None
        # Set by the automation loop so status reports whether new forecasts are
        # still being produced automatically.
        self.automation_status: Callable[[], dict[str, Any]] | None = None

    def set_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        """Install the low-latency delivery hook used after a run persists."""

        self._event_sink = sink

    # ----------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        status = dict(self.provider.status())
        runs = self.repository.list_runs(limit=1)
        status["last_run_at"] = runs[0]["created_at"] if runs else status.get("last_success_at")
        status["last_error"] = status.get("last_error") or self._last_error
        status["automation"] = (
            self.automation_status()
            if self.automation_status is not None
            else {"enabled": False, "running": False, "message": "Automatic forecasting is off."}
        )
        return status

    def history(self, limit: int = 50) -> dict[str, Any]:
        runs = self.repository.list_runs(limit=max(1, min(limit, 200)))
        return {
            "runs": runs,
            "count": len(runs),
            "evaluation": self.repository.evaluation_summary(),
            "timeline": self.repository.evaluations_recent(limit=24),
            "automation": self.status().get("automation"),
            "message": HISTORY_MESSAGE,
            "ai_available": bool(self.status().get("ai_available")),
            "latest": self.repository.get_run(runs[0]["id"]) if runs else None,
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.repository.get_run(run_id)

    def latest(self) -> dict[str, Any] | None:
        return self.repository.latest_run()

    def timeline(self, limit: int = 24) -> dict[str, Any]:
        rows = self.repository.evaluations_recent(limit=max(1, min(int(limit), 200)))
        return {
            "timeline": rows,
            "count": len(rows),
            "evaluation": self.repository.evaluation_summary(),
            "as_of": _iso_now(),
        }

    def unavailable_message(self) -> str:
        return str(self.provider.status().get("message") or "")

    # -------------------------------------------------------------------- run
    def run_forecast(
        self,
        *,
        symbol: str,
        timeframe: str,
        horizon: int,
        candles: list[Candle],
        dedupe: bool = True,
    ) -> dict[str, Any]:
        try:
            parsed = Timeframe(str(timeframe).strip().upper())
        except ValueError as exc:
            from app.core.errors import ValidationError

            raise ValidationError(str(exc)) from exc

        request = ForecastRequest(
            symbol=symbol,
            timeframe=parsed,
            candles=candles,
            horizon=horizon,
        )
        with self._run_lock:
            started = time.perf_counter()
            # Reject a duplicate job before paying for inference. The provider's
            # per-bar contract matches the last closed input candle.
            if dedupe and candles:
                existing = self.repository.successful_for_bar(
                    "BTC/USDT", parsed.value, int(candles[-1].time)
                ) or self.repository.successful_for_bar(
                    "BTCUSDT", parsed.value, int(candles[-1].time)
                )
                if existing:
                    return existing
            try:
                output = self.provider.run(request)
                validate_forecast_output(output, request)
                if dedupe and output.input_last_bar_at is not None:
                    # One immutable forecast per closed input bar. A repeated
                    # request (manual or automatic) returns the stored run.
                    existing = self.repository.successful_for_bar(
                        _output_symbol(output),
                        parsed.value,
                        int(output.input_last_bar_at),
                    )
                    if existing:
                        return existing
            except Exception as exc:  # noqa: BLE001 - record and re-raise
                self._last_error = str(exc)
                warning = str(exc)
                if isinstance(exc, ForecastUnavailableError):
                    warning = exc.message
                try:
                    self.repository.insert_run(
                        {
                            "provider": getattr(self.provider, "provider_id", "unknown"),
                            "model_id": getattr(self.provider, "model_id", "unknown"),
                            "tokenizer_id": getattr(self.provider, "tokenizer_id", None),
                            "symbol": symbol or "BTCUSDT",
                            "timeframe": parsed.value,
                            "created_at": _iso_now(),
                            "input_last_bar_at": candles[-1].time if candles else None,
                            "input_candle_count": len(candles),
                            "horizon": horizon,
                            "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
                            "runtime": "cpu",
                            "status": "error",
                            "warnings": [warning],
                        }
                    )
                except Exception:  # pragma: no cover - persistence must not hide the cause
                    logger.exception("Could not persist failed forecast run")
                raise
            return self._persist(output, request)

    def _persist(self, output: ForecastOutput, request: ForecastRequest) -> dict[str, Any]:
        run = {
            "provider": output.provider,
            "model_id": output.model_id,
            "tokenizer_id": output.tokenizer_id,
            "symbol": _output_symbol(output),
            "timeframe": request.timeframe.value,
            "created_at": _iso_now(),
            "input_last_bar_at": output.input_last_bar_at,
            "input_candle_count": output.input_candle_count,
            "horizon": len(output.candles),
            "latency_ms": output.latency_ms,
            "runtime": output.runtime,
            "status": "ok",
            "warnings": output.warnings,
        }
        run_id = self.repository.insert_run(run)
        self.repository.insert_candles(
            run_id,
            [
                {
                    "time": candle.time,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                }
                for candle in output.candles
            ],
        )
        payload = output.metadata.get("patron")
        if payload:
            self.repository.insert_output(
                run_id,
                {
                    "patron": payload,
                    "meta": {
                        key: value
                        for key, value in output.metadata.items()
                        if key != "patron"
                    },
                },
            )
        self._last_error = None
        stored = self.repository.get_run(run_id)
        if stored is None:  # pragma: no cover - impossible with a working database
            raise RuntimeError("forecast run disappeared after persistence")
        if self._event_sink is not None:
            try:
                self._event_sink({"type": "forecast", "payload": stored})
            except Exception:  # pragma: no cover - delivery must not fail persistence
                logger.debug("Forecast event delivery failed", exc_info=True)
        return stored

    # ------------------------------------------------------------- data access
    def closed_candles(self, limit: int | None = None, force: bool = False) -> list[Candle]:
        """Return closed Binance BTC/USDT 15m candles (PATRON's contract)."""

        if self._history is None:
            return []
        wanted = max(10, int(limit or 520))
        rows = self._history.recent("BTCUSDT", "15m", limit=wanted, force=force)
        return [
            Candle(
                time=row.open_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                tick_volume=row.trades,
                real_volume=int(row.volume),
                source="binance",
                symbol="BTCUSDT",
            )
            for row in rows
        ]

    def live_context(self, limit: int = 60) -> dict[str, Any]:
        """Everything the forecast workspace needs for one poll.

        Always Binance BTC/USDT 15m, because that is the only series PATRON was
        trained on; the rest of the app may be looking at another venue.
        """

        wanted = max(10, min(int(limit), 200))
        candles = self.closed_candles(limit=max(wanted, 520))
        window = candles[-wanted:]
        return {
            "symbol": "BTC/USDT",
            "timeframe": "M15",
            "bar_seconds": 900,
            "candles": [candle.to_dict() for candle in window],
            "latest": self.latest(),
            "status": self.status(),
            "evaluation": self.repository.evaluation_summary(),
            "timeline": self.repository.evaluations_recent(limit=24),
            "as_of": _iso_now(),
            "data_warning": (
                None
                if len(window) >= wanted
                else f"Binance returned {len(window)} of {wanted} closed 15m candles."
            ),
        }

    # -------------------------------------------------------------- evaluation
    def evaluate(self, limit_runs: int = 50) -> dict[str, Any]:
        """Score matured forecasts against realised Binance candles."""

        if self._history is None:
            raise ForecastUnavailableError(
                "Forecast evaluation needs the Binance history client, which is not configured."
            )

        runs = self.repository.list_runs(limit=max(1, min(limit_runs, 200)))
        if not runs:
            return {
                "evaluated_runs": 0,
                "steps_evaluated": 0,
                "awaiting": 0,
                "summary": self.repository.evaluation_summary(),
            }

        prepared: list[tuple[dict[str, Any], dict[str, Any], dict[int, dict[str, Any]]]] = []
        pending_targets: list[int] = []
        awaiting = 0
        for summary in runs:
            detail = self.repository.get_run(summary["id"])
            if not detail or not detail.get("output"):
                awaiting += 1
                continue
            output_doc = detail["output"]
            payload = output_doc.get("patron") or output_doc
            already = {int(row["target_ts"]) for row in detail.get("evaluation") or []}
            candles = [
                candle
                for candle in detail.get("candles") or []
                if int(candle["timestamp_utc"]) not in already
            ]
            if not candles:
                continue
            quantiles = {
                int(step["step"]): step for step in payload.get("range_quantiles") or []
            }
            prepared.append((detail, output_doc, quantiles))
            pending_targets.extend(int(candle["timestamp_utc"]) for candle in candles)

        if not pending_targets:
            return {
                "evaluated_runs": 0,
                "steps_evaluated": 0,
                "awaiting": awaiting,
                "summary": self.repository.evaluation_summary(),
                "evaluated_at": _iso_now(),
            }

        # One 15m Binance page (1000 bars ≈ 10 days) covers recent forecasts;
        # fall back to a ranged fetch if older predictions are still pending
        # (for example after the app was closed for a while).
        rows = self._history.recent("BTCUSDT", "15m", limit=1000)
        if not rows:
            raise ForecastUnavailableError("Binance returned no candles for forecast evaluation.")
        earliest_needed = min(pending_targets)
        if earliest_needed < rows[0].open_time:
            # Include the bar before the first target so legacy runs without a
            # stored reference close can still be scored.
            rows = self._history.range(
                "BTCUSDT", "15m", (earliest_needed - 900) * 1000, None
            )
        actual_by_open = {row.open_time: row for row in rows}
        earliest = min(actual_by_open) if actual_by_open else 0

        evaluated_runs = 0
        steps_evaluated = 0
        for detail, output_doc, quantiles in prepared:
            # Reference close is stored with the run; fall back to the realised
            # candle immediately before the first forecast step for older runs.
            reference = _reference_close(output_doc, actual_by_open, detail)
            if reference is None:
                awaiting += 1
                continue
            already = {int(row["target_ts"]) for row in detail.get("evaluation") or []}
            rows_to_store: list[dict[str, Any]] = []
            for candle in detail.get("candles") or []:
                step = int(candle["sequence"]) + 1
                target_open = int(candle["timestamp_utc"])
                if target_open in already:
                    continue
                actual = actual_by_open.get(target_open)
                if actual is None or target_open < earliest:
                    awaiting += 1
                    continue
                band = quantiles.get(step)
                if band is None:
                    awaiting += 1
                    continue
                predicted_close = float(candle["close"])
                predicted_open = float(candle["open"])
                predicted_high = float(candle["high"])
                predicted_low = float(candle["low"])
                actual_open = float(actual.open)
                actual_high = float(actual.high)
                actual_low = float(actual.low)
                actual_close = float(actual.close)
                q10 = reference * (1.0 + float(band["close"]["q10"]))
                q90 = reference * (1.0 + float(band["close"]["q90"]))
                predicted_direction = _direction(predicted_open, predicted_close)
                actual_direction = _direction(actual_open, actual_close)
                rows_to_store.append(
                    {
                        "step": step,
                        "target_ts": target_open,
                        "actual_open": actual_open,
                        "actual_high": actual_high,
                        "actual_low": actual_low,
                        "actual_close": actual_close,
                        "predicted_open": predicted_open,
                        "predicted_high": predicted_high,
                        "predicted_low": predicted_low,
                        "predicted_close": predicted_close,
                        "open_abs_error": abs(actual_open - predicted_open),
                        "high_abs_error": abs(actual_high - predicted_high),
                        "low_abs_error": abs(actual_low - predicted_low),
                        "abs_error": abs(actual_close - predicted_close),
                        "pct_error": abs(actual_close - predicted_close) / actual_close
                        if actual_close
                        else 0.0,
                        "predicted_direction": predicted_direction,
                        "actual_direction": actual_direction,
                        "direction_correct": predicted_direction == actual_direction,
                        "in_band": q10 <= actual_close <= q90,
                        "evaluated_at": _iso_now(),
                    }
                )
            if rows_to_store:
                self.repository.upsert_evaluation(detail["id"], rows_to_store)
                evaluated_runs += 1
                steps_evaluated += len(rows_to_store)

        return {
            "evaluated_runs": evaluated_runs,
            "steps_evaluated": steps_evaluated,
            "awaiting": awaiting,
            "summary": self.repository.evaluation_summary(),
            "evaluated_at": _iso_now(),
        }


def _output_symbol(output: ForecastOutput) -> str:
    patron = output.metadata.get("patron") if isinstance(output.metadata, dict) else None
    symbol = patron.get("symbol") if isinstance(patron, dict) else None
    return str(symbol or "BTC/USDT")


def _direction(open_: float, close: float) -> str:
    if not open_:
        return "neutral"
    body = (close - open_) / open_
    if abs(body) <= DOJI_THRESHOLD:
        return "neutral"
    return "bullish" if body > 0 else "bearish"


def _reference_close(
    output_doc: dict[str, Any],
    actual_by_open: dict[int, Any],
    detail: dict[str, Any],
) -> float | None:
    metadata = output_doc.get("meta") if isinstance(output_doc, dict) else None
    if isinstance(metadata, dict) and metadata.get("reference_close"):
        return float(metadata["reference_close"])
    first = (detail.get("candles") or [None])[0]
    if not first:
        return None
    previous = actual_by_open.get(int(first["timestamp_utc"]) - 900)
    return float(previous.close) if previous else None
