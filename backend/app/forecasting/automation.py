"""Event-driven closed-candle forecast automation.

The market WebSocket owns candle closure. Its listener calls
``notify_closed`` with the exact exchange bar timestamp; this loop wakes
immediately instead of waiting for a polling interval. A slow inference runs on
this dedicated thread, never on the Binance receiver or the API event loop.

The recovery tick exists only to pick up state after a restart, a missed close
frame or a transient failure. When a recent bar already has an immutable
forecast, recovery does not touch Binance history or the model.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.errors import ForecastUnavailableError
from app.forecasting.service import ForecastService
from app.persistence.repositories import ForecastRepository

logger = logging.getLogger(__name__)

PATRON_SYMBOL_BINANCE = "BTCUSDT"
PATRON_TIMEFRAME = "M15"
PATRON_HORIZON = 6
EVALUATION_RUN_LIMIT = 50
RECOVERY_SECONDS = 30.0

STATE_WAITING = "waiting_for_candle_close"
STATE_EVALUATING = "evaluating_previous_forecast"
STATE_PREPARING = "preparing_model_input"
STATE_GENERATING = "generating_forecast"
STATE_UPDATED = "forecast_updated"
STATE_FAILED = "forecast_failed"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _epoch_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


class ForecastAutomation:
    """Background owner of the closed-candle forecast cycle."""

    def __init__(
        self,
        *,
        forecast: ForecastService,
        repository: ForecastRepository,
        settings: Settings,
        latest_bar: Callable[[], int | None] | None = None,
    ) -> None:
        self.forecast = forecast
        self.repository = repository
        self.settings = settings
        self._latest_bar = latest_bar
        self.poll_seconds = max(2.0, float(settings.forecast_poll_seconds))
        self.recovery_seconds = RECOVERY_SECONDS
        self._retry_seconds = max(30.0, self.poll_seconds * 4)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._trigger_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cycle_lock = threading.Lock()
        self._last_evaluated_bar: int | None = None
        self._last_triggered_bar: int | None = None
        self._pending_bar: int | None = None
        self._trigger_received_at: str | None = None
        self._trigger_received_monotonic: float | None = None
        self._failure_monotonic = 0.0
        self._reset_counters()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.forecast_auto_enabled)

    def _reset_counters(self) -> None:
        self._cycles = 0
        self._forecasts = 0
        self._skipped = 0
        self._steps_evaluated = 0
        self._failures = 0
        self._last_cycle_at: str | None = None
        self._last_forecast_at: str | None = None
        self._last_forecast_bar_at: str | None = None
        self._last_evaluated_at: str | None = None
        self._last_error: str | None = None
        self._evaluation_error: str | None = None
        self._waiting_for: str | None = None
        self._state = STATE_WAITING
        self._last_trigger_at: str | None = None
        self._last_trigger_bar_at: str | None = None
        self._queue_wait_ms: float | None = None
        self._evaluation_ms: float | None = None
        self._forecast_ms: float | None = None
        self._cycle_ms: float | None = None
        self._trigger_to_forecast_ms: float | None = None
        self._last_inference_ms: float | None = None

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if not self.enabled:
            logger.info("Automatic forecasting is disabled by configuration.")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="kbmti-forecast-automation",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Automatic 15m PATRON forecasting started (event-driven, recovery %.0fs)",
            self.recovery_seconds,
        )

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=10.0)
        self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def notify_closed(self, bar: int, received_at: str | None = None) -> bool:
        """Wake the cycle for one confirmed candle-close identity.

        Duplicate close frames, reconnect replays and manual API calls all end
        up with the same symbol/timeframe/bar identity and are collapsed here.
        """

        try:
            identity = int(bar)
        except (TypeError, ValueError):
            return False
        with self._trigger_lock:
            if self._last_triggered_bar is not None and identity <= self._last_triggered_bar:
                return False
            if self._pending_bar is not None and identity <= self._pending_bar:
                return False
            self._pending_bar = identity
            self._trigger_received_at = received_at or _iso_now()
            self._trigger_received_monotonic = time.monotonic()
        self._wake.set()
        self._state = STATE_EVALUATING
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # pragma: no cover - run_once already normalizes errors
                logger.exception("Automatic forecast loop failed")
            timeout = 2.0 if self._waiting_for else self.recovery_seconds
            self._wake.wait(timeout)
            self._wake.clear()

    def _consume_trigger(self) -> tuple[int | None, str | None, float | None]:
        with self._trigger_lock:
            bar = self._pending_bar
            received_at = self._trigger_received_at
            received_monotonic = self._trigger_received_monotonic
            self._pending_bar = None
            self._trigger_received_at = None
            self._trigger_received_monotonic = None
        return bar, received_at, received_monotonic

    # -------------------------------------------------------------------- cycle
    def run_once(self) -> dict[str, Any]:
        """Run a single closed-candle cycle. Safe for tests to call directly."""

        if not self.enabled:
            return {"status": "disabled"}
        with self._cycle_lock:
            started = time.monotonic()
            self._cycles += 1
            self._last_cycle_at = _iso_now()
            trigger_bar, trigger_at, trigger_monotonic = self._consume_trigger()
            if trigger_bar is not None:
                self._last_triggered_bar = max(self._last_triggered_bar or 0, trigger_bar)
                self._last_trigger_bar_at = _epoch_iso(trigger_bar)
                self._last_trigger_at = trigger_at or _iso_now()
                self._queue_wait_ms = (
                    round((started - trigger_monotonic) * 1000.0, 2)
                    if trigger_monotonic is not None
                    else None
                )
            outcome = "idle"
            try:
                outcome = self._cycle(trigger_bar)
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                self._failures += 1
                self._failure_monotonic = time.monotonic()
                self._last_error = str(exc)
                self._state = STATE_FAILED
                outcome = "error"
                logger.warning("Automatic forecast cycle failed: %s", exc)
            finally:
                self._cycle_ms = round((time.monotonic() - started) * 1000.0, 2)
                if trigger_monotonic is not None:
                    self._trigger_to_forecast_ms = round(
                        (time.monotonic() - trigger_monotonic) * 1000.0, 2
                    )
            logger.debug("Forecast automation cycle %s in %.0f ms", outcome, self._cycle_ms)
            return {"status": outcome, **self._counters()}

    def _cycle(self, trigger_bar: int | None = None) -> str:
        candles = None
        bar = trigger_bar

        # The cheap path: ask the live Binance provider for the last confirmed
        # bar. Recovery must not make a REST request when nothing changed.
        if bar is None and self._latest_bar is not None:
            try:
                bar = self._latest_bar()
            except Exception:  # pragma: no cover - provider fallback below
                bar = None

        if bar is None:
            candles = self.forecast.closed_candles(
                limit=max(520, self.settings.forecast_history_bars),
                force=trigger_bar is not None,
            )
            if not candles:
                raise ForecastUnavailableError(
                    "Waiting for closed Binance BTC/USDT 15m candles before forecasting."
                )
            bar = int(candles[-1].time)

        self._waiting_for = None
        self._last_triggered_bar = max(self._last_triggered_bar or 0, bar)

        # Score matured forecasts once per newly closed bar, before asking for
        # the next one. Evaluation failures must not block new forecasts.
        if bar != self._last_evaluated_bar:
            self._state = STATE_EVALUATING
            evaluation_started = time.monotonic()
            try:
                result = self.forecast.evaluate(limit_runs=EVALUATION_RUN_LIMIT)
                self._last_evaluated_bar = bar
                self._last_evaluated_at = result.get("evaluated_at") or _iso_now()
                self._steps_evaluated += int(result.get("steps_evaluated") or 0)
                self._evaluation_error = None
            except Exception as exc:  # noqa: BLE001 - keep generating forecasts
                self._evaluation_error = str(exc)
                logger.warning("Automatic forecast evaluation failed: %s", exc)
            finally:
                self._evaluation_ms = round((time.monotonic() - evaluation_started) * 1000.0, 2)

        latest = self.repository.list_runs(limit=1)
        stored = latest[0] if latest else None
        if (
            stored is not None
            and stored.get("status") == "ok"
            and stored.get("input_last_bar_at") == bar
        ):
            self._skipped += 1
            self._state = STATE_WAITING
            return "unchanged"

        # Back off after a real inference failure instead of writing an error
        # run every recovery tick.
        if self._failure_monotonic and time.monotonic() - self._failure_monotonic < self._retry_seconds:
            self._skipped += 1
            self._state = STATE_WAITING
            return "backoff"

        status = self.forecast.status()
        if not status.get("ai_available"):
            self._waiting_for = str(status.get("message") or "PATRON is not ready.")
            self._skipped += 1
            self._state = STATE_WAITING
            return "model_waiting"

        if candles is None:
            self._state = STATE_PREPARING
            candles = self.forecast.closed_candles(
                limit=max(520, self.settings.forecast_history_bars),
                force=trigger_bar is not None,
            )
            if not candles:
                raise ForecastUnavailableError(
                    "Waiting for closed Binance BTC/USDT 15m candles before forecasting."
                )
            fetched_bar = int(candles[-1].time)
            if fetched_bar != bar:
                # The cached page was older than the confirmed close. Refresh
                # once; the forecast stays keyed to the exchange's latest bar.
                candles = self.forecast.closed_candles(
                    limit=max(520, self.settings.forecast_history_bars), force=True
                )
                bar = int(candles[-1].time)
                self._last_triggered_bar = max(self._last_triggered_bar or 0, bar)

        self._state = STATE_GENERATING
        forecast_started = time.monotonic()
        run = self.forecast.run_forecast(
            symbol=PATRON_SYMBOL_BINANCE,
            timeframe=PATRON_TIMEFRAME,
            horizon=PATRON_HORIZON,
            candles=candles,
            dedupe=True,
        )
        self._forecast_ms = round((time.monotonic() - forecast_started) * 1000.0, 2)
        self._last_inference_ms = run.get("latency_ms")
        self._forecasts += 1
        self._last_forecast_at = run.get("created_at") or _iso_now()
        self._last_forecast_bar_at = _epoch_iso(run.get("input_last_bar_at"))
        self._last_error = None
        self._state = STATE_UPDATED
        return "forecast"

    # ------------------------------------------------------------------- status
    def _counters(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "mode": "event_driven",
            "poll_seconds": self.poll_seconds,
            "recovery_seconds": self.recovery_seconds,
            "state": self._state,
            "cycles": self._cycles,
            "forecasts": self._forecasts,
            "skipped": self._skipped,
            "steps_evaluated": self._steps_evaluated,
            "failures": self._failures,
            "last_cycle_at": self._last_cycle_at,
            "last_forecast_at": self._last_forecast_at,
            "last_forecast_bar_at": self._last_forecast_bar_at,
            "last_evaluated_at": self._last_evaluated_at,
            "last_trigger_at": self._last_trigger_at,
            "last_trigger_bar_at": self._last_trigger_bar_at,
            "queue_wait_ms": self._queue_wait_ms,
            "evaluation_ms": self._evaluation_ms,
            "forecast_ms": self._forecast_ms,
            "inference_ms": self._last_inference_ms,
            "cycle_ms": self._cycle_ms,
            "trigger_to_forecast_ms": self._trigger_to_forecast_ms,
            "last_error": self._last_error,
            "evaluation_error": self._evaluation_error,
            "waiting_for": self._waiting_for,
        }

    def status(self) -> dict[str, Any]:
        return self._counters()
