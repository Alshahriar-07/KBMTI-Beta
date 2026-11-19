"""Market session orchestration: one controlled MT5 lifecycle, state and caches.

The service never initializes or shuts down MT5 per request. One poller owns the
session, serializes IPC through the gateway lock, checks health on a bounded
cadence, reconnects with exponential backoff, and exposes an explicit state plus
independent capability flags.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import STAGE, Settings
from app.core.errors import (
    ApiError,
    MT5AccountUnavailableError,
    MT5BrokerDisconnectedError,
    MT5DataError,
    MT5DisconnectedError,
    MT5NotInstalledError,
    MT5TerminalNotFoundError,
    ValidationError,
)
from app.core.timeframes import TIMEFRAME_SECONDS, Timeframe, parse_timeframe
from app.market_data.broadcaster import Broadcaster
from app.market_data.candles import (
    TIME_BASIS_SERVER,
    TIME_BASIS_UTC,
    Candle,
    clean_candles,
    epoch_to_iso,
    mark_forming,
    shift_candles,
    shift_rows_to_utc,
)
from app.market_data.mt5_gateway import MT5Gateway
from app.market_data.providers.base import MarketDataProvider, MarketEventListener
from app.market_data.state import STATE_LABELS, ConnectionState
from app.market_data.symbols import discover_btc_symbols, is_btc_like
from app.market_data.terminal_discovery import normalize_path, validate_terminal_executable
from app.persistence.repositories import CandleRepository, SettingsRepository, TickRepository

logger = logging.getLogger(__name__)

TICK_VOLUME_NOTE = (
    "MT5 tick_volume is the broker's count of price updates for the bar, not exchange-traded volume."
)
DISCONNECTED_HINT = (
    "MetaTrader 5 is not connected. Open and log in to the terminal, then use Connect."
)
MIN_HISTORY_CANDLES = 500
MAX_HISTORY_CANDLES = 1500
HEALTH_CHECK_SECONDS = 5.0
SYMBOL_REFRESH_SECONDS = 60.0
CANDIDATE_CACHE_SECONDS = 60.0


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _price(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


class MarketService(MarketDataProvider):
    """Owns the MT5 session. Every public method is safe to call from API threads."""

    provider_id = "mt5"
    provider_name = "MetaTrader 5"

    def __init__(
        self,
        settings: Settings,
        gateway: MT5Gateway,
        candles_repo: CandleRepository,
        ticks_repo: TickRepository,
        settings_repo: SettingsRepository,
        broadcaster: Broadcaster | None = None,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.candles_repo = candles_repo
        self.ticks_repo = ticks_repo
        self.settings_repo = settings_repo
        self.broadcaster = broadcaster or Broadcaster()

        # Serializes all MT5 operations, state transitions and cache mutations.
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._auto_connect = True

        self._state = ConnectionState.NOT_CONFIGURED
        self._state_reason: str | None = "MetaTrader 5 has not been initialized yet."
        self._terminal_connected = False
        self._broker_connected = False
        self._account_available = False
        self._symbol_available = False
        self._tick_available = False
        self._history_available = False
        self._market_data_ready = False
        self._terminal_info: dict[str, Any] = {}
        self._account_info: dict[str, Any] = {}
        self._terminal_info_snapshot: dict[str, Any] = {}
        self._last_error: str | None = None
        self._last_error_code: int | None = None
        self._last_error_description: str | None = None
        self._last_error_stage: str | None = None
        self._last_error_detail: dict[str, Any] | None = None
        self._last_successful_update: str | None = None
        self._last_successful_wall = 0.0
        self._last_tick_at: str | None = None
        self._last_history_at: str | None = None
        self._server_offset: int | None = None
        self._time_basis = TIME_BASIS_SERVER

        self._terminal_candidates: list[dict[str, Any]] = []
        self._terminal_candidates_wall = 0.0
        self._resolved_terminal_path: str | None = None

        self._symbol: str | None = settings_repo.get("market.symbol")
        self._symbol_info: dict[str, Any] = {}
        self._symbol_error: str | None = None
        self._timeframe: Timeframe = parse_timeframe(
            settings_repo.get("market.timeframe") or settings.default_timeframe
        )
        stored_limit = settings_repo.get("market.candle_limit")
        self._candle_limit = int(stored_limit) if isinstance(stored_limit, (int, float)) else settings.default_candle_limit
        self._candle_limit = max(60, min(MAX_HISTORY_CANDLES, self._candle_limit))

        self._candles: list[Candle] = []
        self._forming: Candle | None = None
        self._candle_source = "mt5"
        self._candles_fetched_wall = 0.0
        self._candles_warnings: list[str] = []
        self._history_requested = 0
        self._history_returned = 0

        self._quote: dict[str, Any] | None = None
        self._quote_wall = 0.0
        self._daily: dict[str, Any] | None = None
        self._daily_wall = 0.0

        self._symbol_cache: list[dict[str, Any]] = []
        self._symbol_cache_wall = 0.0
        self._symbol_cache_error: str | None = None
        self._symbol_cache_total = 0

        self._reconnect_attempts = 0
        self._next_retry_wall = 0.0
        self._last_tick_persisted = 0.0
        self._last_status_json = ""
        self._health_wall = 0.0
        self._started_at = time.time()
        self._warnings: list[str] = []
        self._connect_timeout_ms = self._initial_timeout()
        self._listeners: list[MarketEventListener] = []

    @property
    def candle_limit(self) -> int:
        return self._candle_limit

    def subscribe(self, listener: MarketEventListener):  # type: ignore[no-untyped-def]
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def get_connection_status(self) -> dict[str, Any]:
        return self.status()

    def get_symbols(self, refresh: bool = False) -> dict[str, Any]:
        return self.discover_symbols(refresh=refresh)

    def get_historical_candles(self, timeframe: str, limit: int) -> list[Candle]:
        with self._lock:
            parsed = parse_timeframe(timeframe)
            if parsed != self._timeframe:
                self.set_timeframe(parsed.value)
            if self._broker_connected:
                self._fetch_candles(force=True)
            return list(self._candles[-max(1, min(int(limit), MAX_HISTORY_CANDLES)) :])

    def _initial_timeout(self) -> int:
        stored = self.settings_repo.get("mt5.connect_timeout_ms")
        if isinstance(stored, (int, float)):
            return max(1_000, min(120_000, int(stored)))
        return max(1_000, min(120_000, int(getattr(self.settings, "mt5_connect_timeout_ms", 15_000))))

    # --------------------------------------------------------------- lifecycle
    def apply_retention(self) -> None:
        now = int(time.time())
        candle_days = int(self.settings_repo.get("data.candle_retention_days", 30) or 30)
        tick_days = int(self.settings_repo.get("data.tick_retention_days", 7) or 7)
        try:
            self.candles_repo.delete_before(now - candle_days * 86400)
            self.ticks_repo.delete_before(now - tick_days * 86400)
        except Exception:  # pragma: no cover - non-critical maintenance
            logger.exception("Retention cleanup failed")

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._auto_connect = False
            try:
                self.gateway.shutdown()
            except Exception:  # pragma: no cover - best effort
                pass
            self._terminal_connected = False
            self._broker_connected = False
            self._account_available = False
            self._market_data_ready = False
            self._quote = None
            self._set_state(ConnectionState.NOT_CONFIGURED, "The backend is shutting down.")

    async def run(self) -> None:
        self.broadcaster.bind_loop(asyncio.get_running_loop())
        self.apply_retention()
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.poll_once)
            except Exception:  # pragma: no cover - loop must survive
                logger.exception("Market poll failed unexpectedly")
            await asyncio.sleep(max(0.5, self.settings.poll_interval_seconds))

    # ------------------------------------------------------------------ state
    def _set_state(self, state: ConnectionState, reason: str | None = None) -> None:
        self._state = state
        self._state_reason = reason
        self._market_data_ready = state == ConnectionState.MARKET_DATA_READY

    def _record_error(self, exc: BaseException, stage: str) -> None:
        if isinstance(exc, ApiError):
            message = exc.message
            details = exc.details
        else:  # pragma: no cover - defensive
            message = str(exc)
            details = {}
        code = details.get("code") if isinstance(details, dict) else None
        description = details.get("description") if isinstance(details, dict) else None
        self._last_error = message
        self._last_error_code = int(code) if isinstance(code, int) else None
        self._last_error_description = str(description) if description else None
        self._last_error_stage = stage
        self._last_error_detail = details if isinstance(details, dict) else None

    def _clear_error(self) -> None:
        self._last_error = None
        self._last_error_code = None
        self._last_error_description = None
        self._last_error_stage = None
        self._last_error_detail = None

    def _schedule_retry(self, now: float | None = None) -> None:
        self._reconnect_attempts = min(self._reconnect_attempts + 1, 20)
        delay = min(30.0, float(2 ** min(self._reconnect_attempts, 5)))
        self._next_retry_wall = (now or time.time()) + delay

    # ------------------------------------------------------------- discovery
    def _refresh_candidates(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if not force and self._terminal_candidates and now - self._terminal_candidates_wall < CANDIDATE_CACHE_SECONDS:
            return self._terminal_candidates
        try:
            candidates = self.gateway.terminal_candidates()
            self._terminal_candidates = [candidate.to_dict() for candidate in candidates]
            self._terminal_candidates_wall = now
        except Exception:  # pragma: no cover - filesystem/psutil dependent
            logger.debug("Terminal discovery failed", exc_info=True)
            self._terminal_candidates = []
        return self._terminal_candidates

    def _configured_terminal_path(self) -> str | None:
        stored = self.settings_repo.get("mt5.terminal_path")
        env = os.environ.get("KBMTI_MT5_TERMINAL_PATH")
        return normalize_path(stored or env or self.gateway.terminal_path)

    def _resolve_terminal_path(self, force_discovery: bool = False) -> str | None:
        configured = self._configured_terminal_path()
        if configured:
            valid, reason = validate_terminal_executable(configured)
            if not valid:
                self._set_state(ConnectionState.TERMINAL_NOT_FOUND, reason)
                self._last_error = reason
                self._last_error_stage = "discovery"
                return None
            self._resolved_terminal_path = configured
            return configured

        candidates = self._refresh_candidates(force=force_discovery)
        paths = [str(item["path"]) for item in candidates if item.get("path")]
        if not paths:
            self._set_state(
                ConnectionState.TERMINAL_NOT_FOUND,
                "No MetaTrader 5 installation was found. Select terminal64.exe manually in Settings.",
            )
            self._last_error = self._state_reason
            self._last_error_stage = "discovery"
            return None
        if len(paths) > 1:
            self._set_state(
                ConnectionState.NOT_CONFIGURED,
                f"{len(paths)} MetaTrader 5 terminals were detected. Select the exact terminal in Settings.",
            )
            self._last_error = self._state_reason
            self._last_error_stage = "discovery"
            return None
        self._resolved_terminal_path = paths[0]
        return paths[0]

    # -------------------------------------------------------------- connection
    def connect(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            self._auto_connect = True
            if self._broker_connected and not force:
                return self.status()
            if force:
                self._close_session()
            self._attempt_connect(bypass_backoff=True, manual=True)
            if self._broker_connected and self._symbol:
                self._poll_connected()
            return self.status()

    def reconnect(self) -> dict[str, Any]:
        return self.connect(force=True)

    def _close_session(self) -> None:
        try:
            self.gateway.shutdown()
        except Exception:  # pragma: no cover - best effort
            pass
        self._terminal_connected = False
        self._broker_connected = False
        self._account_available = False
        self._tick_available = False
        self._market_data_ready = False
        self._quote = None
        self._quote_wall = 0.0
        self._health_wall = 0.0

    def _attempt_connect(self, bypass_backoff: bool = False, manual: bool = False) -> None:
        now = time.time()
        if self._stop.is_set():
            return
        if self._broker_connected:
            return
        if not manual and not self._auto_connect:
            return
        if not bypass_backoff and now < self._next_retry_wall:
            self._set_state(
                ConnectionState.RECONNECTING,
                f"Waiting {max(1, round(self._next_retry_wall - now))}s before the next terminal attempt.",
            )
            return
        if not self.gateway.package_available():
            self._record_error(MT5NotInstalledError(), "package")
            self._set_state(ConnectionState.ERROR, "The MetaTrader5 Python package is not installed.")
            self._schedule_retry(now)
            return

        path = self._resolve_terminal_path(force_discovery=manual)
        if not path:
            self._schedule_retry(now)
            return

        self._set_state(ConnectionState.INITIALIZING, f"Attaching to {Path(path).name}…")
        try:
            info = self.gateway.initialize(path, timeout_ms=self._connect_timeout_ms)
        except MT5TerminalNotFoundError as exc:
            self._record_error(exc, "terminal_discovery")
            self._set_state(ConnectionState.TERMINAL_NOT_FOUND, exc.message)
            self._schedule_retry(now)
            return
        except MT5BrokerDisconnectedError as exc:
            self._record_error(exc, "broker")
            self._terminal_connected = False
            self._broker_connected = False
            self._account_available = False
            self._set_state(ConnectionState.BROKER_DISCONNECTED, exc.message)
            self._schedule_retry(now)
            return
        except MT5AccountUnavailableError as exc:
            self._record_error(exc, "account")
            self._terminal_connected = False
            self._broker_connected = False
            self._account_available = False
            self._set_state(ConnectionState.ERROR, exc.message)
            self._schedule_retry(now)
            return
        except MT5NotInstalledError as exc:
            self._record_error(exc, "package")
            self._set_state(ConnectionState.ERROR, exc.message)
            self._schedule_retry(now)
            return
        except MT5DisconnectedError as exc:
            self._record_error(exc, "initialization")
            self._terminal_connected = False
            self._broker_connected = False
            self._account_available = False
            self._set_state(ConnectionState.RECONNECTING, exc.message)
            self._schedule_retry(now)
            return
        except Exception as exc:  # pragma: no cover - defensive
            self._record_error(exc, "initialization")
            self._set_state(ConnectionState.ERROR, f"Unexpected MT5 initialization error: {exc}")
            self._schedule_retry(now)
            return

        self._terminal_connected = True
        self._broker_connected = True
        self._account_available = True
        self._terminal_info = info
        self._terminal_info_snapshot = dict(info)
        try:
            self._account_info = self.gateway.account_info()
        except Exception:  # pragma: no cover - defensive
            self._account_info = {}
        self._resolved_terminal_path = path
        self._reconnect_attempts = 0
        self._next_retry_wall = 0.0
        self._health_wall = now
        self._clear_error()
        self._set_state(ConnectionState.TERMINAL_CONNECTED, "Terminal IPC and broker session verified.")
        self._refresh_candidates(force=True)
        logger.info("MT5 session ready for %s", path)
        self._ensure_symbol_after_connect()

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self._auto_connect = False
            self._close_session()
            self._last_error = "Disconnected by user."
            self._last_error_stage = "manual"
            self._set_state(ConnectionState.NOT_CONFIGURED, "Detached by user. Click Connect to reattach.")
            return self.status()

    def poll_once(self) -> None:
        with self._lock:
            if self._stop.is_set() or not self._auto_connect:
                self._publish()
                return
            if not self._broker_connected:
                self._attempt_connect()
            if self._broker_connected:
                self._poll_connected()
            self._publish()

    def _apply_health_failure(self, health: dict[str, Any]) -> None:
        error = health.get("error") or {}
        message = str(error.get("message") or "The MetaTrader 5 session is no longer usable.")
        self._terminal_connected = bool(health.get("terminal_connected"))
        self._broker_connected = bool(health.get("broker_connected"))
        self._account_available = bool(health.get("account_available"))
        self._terminal_info_snapshot = dict(self._terminal_info or health.get("terminal") or {})
        if health.get("terminal") and not self._terminal_info_snapshot:
            self._terminal_info_snapshot = dict(health["terminal"])
        self._tick_available = False
        self._market_data_ready = False
        self._quote = None
        self._quote_wall = 0.0
        self._last_error = message
        self._last_error_code = error.get("code")
        self._last_error_description = error.get("description")
        self._last_error_stage = "health"
        self._last_error_detail = error if isinstance(error, dict) else None
        try:
            self.gateway.shutdown()
        except Exception:  # pragma: no cover
            pass
        if not self._terminal_connected:
            self._set_state(ConnectionState.RECONNECTING, message)
        elif not self._broker_connected:
            self._set_state(ConnectionState.BROKER_DISCONNECTED, message)
        else:
            self._set_state(ConnectionState.ERROR, message)
        self._schedule_retry()

    def _handle_disconnect(self, exc: ApiError) -> None:
        self._record_error(exc, "market_data")
        self._terminal_connected = False
        self._broker_connected = False
        self._account_available = False
        self._tick_available = False
        self._market_data_ready = False
        self._quote = None
        try:
            self.gateway.shutdown()
        except Exception:  # pragma: no cover
            pass
        self._set_state(ConnectionState.RECONNECTING, exc.message)
        self._schedule_retry()

    # ------------------------------------------------------------------ symbols
    def _ensure_symbol_after_connect(self) -> None:
        if not self._symbol:
            self.discover_symbols(refresh=True)
            self._set_state(
                ConnectionState.SYMBOL_NOT_SELECTED,
                "Select the exact BTC instrument exposed by this broker.",
            )
            return
        try:
            info = self.gateway.symbol(self._symbol)
        except MT5DisconnectedError as exc:
            self._handle_disconnect(exc)
            return
        except ApiError as exc:
            self._record_error(exc, "symbol")
            info = None
        if not info:
            self._symbol_available = False
            self._symbol_info = {}
            self._symbol_error = (
                f"Saved symbol '{self._symbol}' is not available on this broker. Select another instrument."
            )
            self.discover_symbols(refresh=True)
            self._set_state(ConnectionState.SYMBOL_NOT_SELECTED, self._symbol_error)
            return
        self._symbol_info = info
        self._symbol_available = True
        self._symbol_error = None
        if not info.get("visible"):
            try:
                self.gateway.ensure_symbol_visible(self._symbol)
                self._symbol_info = self.gateway.symbol(self._symbol) or info
            except ApiError:
                pass
        self._set_state(ConnectionState.WAITING_FOR_MARKET_DATA, "Symbol verified; waiting for the first tick.")
        self._poll_connected()

    def discover_symbols(self, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            if not refresh and self._symbol_cache and now - self._symbol_cache_wall < self.settings.symbol_cache_seconds:
                return self._symbol_payload()
            if not self._broker_connected:
                self._attempt_connect(bypass_backoff=False)
            if not self._broker_connected:
                self._symbol_cache = []
                self._symbol_cache_error = self._last_error or "MetaTrader 5 is not connected."
                self._symbol_cache_wall = now
                return self._symbol_payload()
            try:
                raw_symbols = self.gateway.symbols()
                self._symbol_cache_total = len(raw_symbols)
                self._symbol_cache = discover_btc_symbols(raw_symbols)
                self._symbol_cache_wall = now
                self._symbol_cache_error = None
                if not self._symbol_cache:
                    self._symbol_cache_error = (
                        f"No BTC-like instruments were found among {len(raw_symbols)} broker symbols."
                    )
                    if not self._symbol:
                        self._set_state(ConnectionState.SYMBOL_NOT_SELECTED, self._symbol_cache_error)
                logger.info(
                    "Discovered %s BTC-like symbols among %s broker symbols",
                    len(self._symbol_cache),
                    len(raw_symbols),
                )
            except MT5DisconnectedError as exc:
                self._handle_disconnect(exc)
                self._symbol_cache_error = exc.message
                self._symbol_cache = []
            except ApiError as exc:
                self._record_error(exc, "symbol_discovery")
                self._symbol_cache_error = exc.message
                self._symbol_cache = []
            return self._symbol_payload()

    def _symbol_payload(self) -> dict[str, Any]:
        return {
            "connected": self._broker_connected,
            "state": self._state.value,
            "symbols": self._symbol_cache,
            "count": len(self._symbol_cache),
            "total_broker_symbols": self._symbol_cache_total,
            "selected_symbol": self._symbol,
            "error": self._symbol_cache_error,
            "note": (
                "Candidates are ranked broker instruments. Confirm the exact BTC/USD instrument; KBMTI never substitutes one automatically."
                if self._symbol_cache
                else None
            ),
            "fetched_at": epoch_to_iso(int(self._symbol_cache_wall)) if self._symbol_cache_wall else None,
        }

    def symbol_details(self, name: str) -> dict[str, Any]:
        with self._lock:
            if not self._broker_connected:
                self._attempt_connect()
            if not self._broker_connected:
                raise MT5DisconnectedError(self._last_error or "MetaTrader 5 is not connected.")
            info = self.gateway.symbol(name)
            if not info:
                raise ValidationError(f"Symbol '{name}' was not found on this broker server.")
            enriched = dict(info)
            enriched["btc_like"] = is_btc_like(
                info.get("name", ""), info.get("description", ""), info.get("path", "")
            )
            return enriched

    def select_symbol(self, name: str) -> dict[str, Any]:
        cleaned = (name or "").strip()
        if not cleaned:
            raise ValidationError("A symbol name is required.")
        with self._lock:
            if not self._broker_connected:
                self._attempt_connect()
            if not self._broker_connected:
                raise MT5DisconnectedError(self._last_error or "MetaTrader 5 is not connected.")
            try:
                selected = self.gateway.select_symbol(cleaned)
            except MT5DisconnectedError as exc:
                self._handle_disconnect(exc)
                raise
            except ApiError as exc:
                self._record_error(exc, "symbol_selection")
                self._symbol_error = exc.message
                if "not found" in exc.message.lower():
                    raise ValidationError(exc.message, exc.details) from exc
                raise

            info = selected["symbol"]
            self._symbol = cleaned
            self._symbol_info = info
            self._symbol_available = True
            self._symbol_error = None
            btc_like = is_btc_like(info.get("name", ""), info.get("description", ""), info.get("path", ""))
            self._warnings = (
                []
                if btc_like
                else [f"'{cleaned}' does not look like a BTC instrument. Data will still be read, but KBMTI is a BTC workspace."]
            )
            self.settings_repo.set("market.symbol", cleaned)
            self._reset_candles()
            self._on_tick(selected["tick"])
            self._poll_connected()
            return {"selected_symbol": cleaned, "btc_like": btc_like, "status": self.status()}

    def set_timeframe(self, value: str) -> dict[str, Any]:
        try:
            timeframe = parse_timeframe(value)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        with self._lock:
            self._timeframe = timeframe
            self.settings_repo.set("market.timeframe", timeframe.value)
            self._reset_candles()
            if self._broker_connected and self._symbol:
                self._poll_connected()
            return {"timeframe": timeframe.value, "status": self.status()}

    def set_candle_limit(self, limit: int) -> int:
        clamped = max(60, min(MAX_HISTORY_CANDLES, int(limit)))
        with self._lock:
            self._candle_limit = clamped
            self.settings_repo.set("market.candle_limit", clamped)
            self._reset_candles()
            return clamped

    def set_connect_timeout(self, timeout_ms: int) -> int:
        clamped = max(1_000, min(120_000, int(timeout_ms)))
        with self._lock:
            self._connect_timeout_ms = clamped
            self.settings_repo.set("mt5.connect_timeout_ms", clamped)
            self.gateway.set_timeout_ms(clamped)
            return clamped

    def select_terminal(self, path: str | None) -> dict[str, Any]:
        with self._lock:
            if path is None or not str(path).strip():
                self.settings_repo.set("mt5.terminal_path", None)
                self.gateway.set_terminal_path(None)
                self._resolved_terminal_path = None
                self._terminal_candidates_wall = 0.0
                self._close_session()
                self._auto_connect = True
                self._attempt_connect(bypass_backoff=True, manual=True)
                return self.status()

            valid, reason = validate_terminal_executable(path)
            if not valid:
                raise ValidationError(reason or "The selected file is not a MetaTrader 5 terminal.")
            normalized = normalize_path(path)
            assert normalized is not None
            self.settings_repo.set("mt5.terminal_path", normalized)
            self.gateway.set_terminal_path(normalized)
            self._resolved_terminal_path = normalized
            self._terminal_candidates_wall = 0.0
            self._close_session()
            self._reconnect_attempts = 0
            self._next_retry_wall = 0.0
            self._auto_connect = True
            self._attempt_connect(bypass_backoff=True, manual=True)
            if self._broker_connected and self._symbol:
                self._poll_connected()
            return self.status()

    def _reset_candles(self) -> None:
        self._candles = []
        self._forming = None
        self._candles_fetched_wall = 0.0
        self._candles_warnings = []
        self._history_available = False
        self._history_requested = 0
        self._history_returned = 0
        self._daily = None
        self._daily_wall = 0.0

    # -------------------------------------------------------------------- polls
    def _poll_connected(self) -> None:
        if not self._broker_connected:
            return
        now_wall = time.time()
        if now_wall - self._health_wall >= HEALTH_CHECK_SECONDS:
            health = self.gateway.health()
            self._health_wall = now_wall
            if not health.get("connected"):
                self._apply_health_failure(health)
                return
            self._terminal_info = health.get("terminal") or self._terminal_info
            self._terminal_info_snapshot = dict(self._terminal_info)
            self._account_info = health.get("account") or self._account_info
            self._account_available = True
            self._terminal_connected = True
            self._broker_connected = True

        if not self._symbol:
            self._set_state(ConnectionState.SYMBOL_NOT_SELECTED, "No BTC instrument is selected.")
            return

        tick: dict[str, Any] | None = None
        try:
            tick = self.gateway.tick(self._symbol)
        except MT5DisconnectedError as exc:
            self._handle_disconnect(exc)
            return
        except MT5DataError as exc:
            self._record_error(exc, "tick")
            self._tick_available = False
            self._warnings = ["No tick received for the selected symbol."]
            tick = None

        if tick is not None:
            self._on_tick(tick)
            self._warnings = [warning for warning in self._warnings if "No tick" not in warning]
            now_wall = time.time()
            if now_wall - self._last_tick_persisted >= 5.0:
                try:
                    self.ticks_repo.insert(
                        self._symbol,
                        int(tick["time"]),
                        tick.get("bid"),
                        tick.get("ask"),
                        tick.get("last"),
                    )
                    self._last_tick_persisted = now_wall
                except Exception:  # pragma: no cover
                    logger.debug("Tick persistence failed", exc_info=True)

        if not self._symbol_info or now_wall - self._daily_wall > SYMBOL_REFRESH_SECONDS:
            try:
                info = self.gateway.symbol(self._symbol)
                if info:
                    self._symbol_info = info
                    self._symbol_available = True
            except ApiError:
                pass

        if now_wall - self._daily_wall >= SYMBOL_REFRESH_SECONDS:
            try:
                self._daily = self.gateway.daily_reference(self._symbol)
            except ApiError:
                self._daily = None
            self._daily_wall = now_wall

        if not self._candles or now_wall - self._candles_fetched_wall >= self.settings.candle_refresh_seconds:
            self._fetch_candles()

        self._decide_state()

    def _decide_state(self) -> None:
        if not self._terminal_connected:
            self._set_state(ConnectionState.RECONNECTING, self._last_error or "Terminal IPC is unavailable.")
            return
        if not self._broker_connected:
            self._set_state(ConnectionState.BROKER_DISCONNECTED, self._last_error or "Broker session is disconnected.")
            return
        if not self._symbol or not self._symbol_available:
            self._set_state(
                ConnectionState.SYMBOL_NOT_SELECTED,
                self._symbol_error or "Select the exact BTC instrument exposed by this broker.",
            )
            return
        freshness, reason = self.freshness()
        if freshness == "fresh" and self._history_available and (self._candles or self._forming):
            self._set_state(ConnectionState.MARKET_DATA_READY, "Live tick and candle history are available.")
            return
        self._set_state(
            ConnectionState.WAITING_FOR_MARKET_DATA,
            reason or "Waiting for the first valid tick and candle history. The market may be closed.",
        )

    # --------------------------------------------------------------- market data
    def _estimate_server_offset(self, raw_tick_time: int) -> int:
        raw = int(round((raw_tick_time - time.time()) / 60.0) * 60)
        snapped = int(round(raw / 900.0) * 900)
        if abs(raw - snapped) <= 120:
            return snapped
        return raw

    def _on_tick(self, tick: dict[str, Any]) -> None:
        raw_time = int(tick.get("time") or 0)
        if raw_time <= 0:
            return
        previous = self._server_offset
        offset = previous if previous is not None else self._estimate_server_offset(raw_time)
        if previous is None or abs(offset - previous) >= 60:
            delta = -offset if previous is None else previous - offset
            if self._candles:
                self._candles = shift_candles(self._candles, delta)
            if self._forming:
                self._forming = replace(
                    self._forming,
                    time=self._forming.time + delta,
                    server_time=self._forming.server_time or self._forming.time,
                )
            self._server_offset = offset
            self._time_basis = TIME_BASIS_UTC
            self._daily_wall = 0.0

        self._quote = tick
        self._quote_wall = time.time()
        self._tick_available = True
        self._last_tick_at = epoch_to_iso(raw_time - offset)
        self._last_successful_update = _iso_now()
        self._last_successful_wall = time.time()
        if self._last_error_stage in {"tick", "health", "market_data"}:
            self._clear_error()
        self._update_forming_from_tick(tick)

    def _update_forming_from_tick(self, tick: dict[str, Any]) -> None:
        if self._server_offset is None:
            return
        raw_time = int(tick.get("time") or 0)
        if raw_time <= 0:
            return
        price = _price(tick.get("last")) or _price(tick.get("bid")) or _price(tick.get("ask"))
        if price <= 0:
            return
        step = TIMEFRAME_SECONDS[self._timeframe]
        utc_time = raw_time - self._server_offset
        bar_start = utc_time - (utc_time % step)

        if self._forming and bar_start < self._forming.time:
            return
        if self._forming and bar_start == self._forming.time:
            self._forming = replace(
                self._forming,
                high=max(self._forming.high, price),
                low=min(self._forming.low, price),
                close=price,
            )
            return
        if self._forming and bar_start > self._forming.time:
            self._finalize_forming()
            self._forming = Candle(
                time=bar_start,
                open=price,
                high=price,
                low=price,
                close=price,
                tick_volume=0,
            )
            self._history_available = True
            return
        if self._candles and self._candles[-1].time == bar_start:
            existing = self._candles.pop()
            self._forming = replace(
                existing,
                high=max(existing.high, price),
                low=min(existing.low, price),
                close=price,
            )
            return
        if not self._candles or self._candles[-1].time < bar_start:
            self._forming = Candle(
                time=bar_start,
                open=price,
                high=price,
                low=price,
                close=price,
                tick_volume=0,
            )
            self._history_available = True

    def _finalize_forming(self) -> None:
        if not self._forming or not self._symbol:
            return
        candle = self._forming
        self._candles.append(candle)
        self._candles = self._candles[-MAX_HISTORY_CANDLES:]
        self._forming = None
        try:
            self.candles_repo.upsert_many(self._symbol, self._timeframe.value, [candle], source="mt5")
        except Exception:  # pragma: no cover - cache writes are best effort
            logger.debug("Candle finalize write failed", exc_info=True)

    def _fetch_candles(self, force: bool = False) -> None:
        if not self._symbol or not self._broker_connected:
            return
        requested = max(MIN_HISTORY_CANDLES, self._candle_limit + 5)
        requested = min(requested, MAX_HISTORY_CANDLES)
        try:
            rows = self.gateway.rates(self._symbol, self._timeframe, requested)
        except MT5DisconnectedError as exc:
            self._handle_disconnect(exc)
            return
        except MT5DataError as exc:
            self._record_error(exc, "history")
            self._candles_warnings = [exc.message]
            self._history_available = False
            return

        if not rows:
            self._candles_warnings = [
                f"No candle history was returned for {self._symbol} {self._timeframe.value}. Nothing has been fabricated."
            ]
            self._history_available = False
            self._candles_fetched_wall = time.time()
            return

        if self._server_offset is not None:
            rows = shift_rows_to_utc(rows, self._server_offset)

        cleaned, warnings = clean_candles(rows)
        reference_epoch = None
        if self._quote and self._quote.get("time") and self._server_offset is not None:
            reference_epoch = int(self._quote["time"]) - self._server_offset
        completed, forming = mark_forming(cleaned, TIMEFRAME_SECONDS[self._timeframe], reference_epoch)

        if len(rows) < requested:
            warnings.append(
                f"The broker returned {len(rows)} of {requested} requested {self._timeframe.value} candles."
            )
        if not completed and not forming:
            warnings.append("No valid candles remained after integrity checks.")

        self._candles = completed[-self._candle_limit :]
        self._forming = forming
        self._candle_source = "mt5"
        self._candles_fetched_wall = time.time()
        self._candles_warnings = warnings
        self._history_requested = requested
        self._history_returned = len(cleaned)
        self._history_available = bool(completed or forming)
        self._last_history_at = _iso_now()
        self._last_successful_update = _iso_now()
        self._last_successful_wall = time.time()

        if completed:
            try:
                self.candles_repo.upsert_many(self._symbol, self._timeframe.value, completed[-50:], source="mt5")
            except Exception:  # pragma: no cover - cache writes are best effort
                logger.debug("Candle cache write failed", exc_info=True)

    def _load_cached_candles(self) -> None:
        if not self._symbol:
            return
        try:
            rows = self.candles_repo.recent(self._symbol, self._timeframe.value, self._candle_limit, source="mt5")
        except Exception:  # pragma: no cover
            rows = []
        if not rows:
            return
        candles = [
            Candle(
                time=int(row["timestamp_utc"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                tick_volume=int(row["tick_volume"] or 0),
                spread=int(row["spread"] or 0),
                real_volume=int(row["real_volume"] or 0),
            )
            for row in rows
        ]
        self._candles = candles
        self._forming = None
        self._candle_source = "local_cache"
        self._history_available = bool(candles)
        self._candles_warnings = [
            "MT5 is disconnected. Candles below come from KBMTI's local cache of earlier broker data."
        ]

    # ------------------------------------------------------------------- state
    def _tick_lag_seconds(self) -> float | None:
        if not self._quote or self._server_offset is None:
            return None
        server_now = time.time() + self._server_offset
        return max(0.0, server_now - float(self._quote.get("time", 0)))

    def freshness(self) -> tuple[str, str | None]:
        if not self._broker_connected:
            return "unavailable", self._last_error or "MetaTrader 5 is not connected."
        if not self._symbol:
            return "unavailable", "No symbol selected."
        if not self._quote:
            return "unavailable", "Waiting for the first tick from the broker feed."
        lag = self._tick_lag_seconds()
        if lag is None:
            return "unavailable", "Tick timing is unavailable."
        if lag > self.settings.stale_after_seconds:
            return "stale", f"No new tick for {int(lag)} seconds (threshold {int(self.settings.stale_after_seconds)}s)."
        return "fresh", None

    def _utc_epoch(self, raw_epoch: int | None) -> int | None:
        if not raw_epoch:
            return None
        return int(raw_epoch) - (self._server_offset or 0)

    def status(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            if not self._terminal_candidates:
                self._refresh_candidates()
            freshness, reason = self.freshness()
            last_error = self._last_error or (None if self._broker_connected else DISCONNECTED_HINT)
            return {
                "stage": STAGE,
                "provider": self.provider_id,
                "provider_label": self.provider_name,
                "source": "mt5",
                "rest_connected": self._broker_connected,
                "ws_connected": False,
                "state": self._state.value,
                "state_label": STATE_LABELS[self._state],
                "state_reason": self._state_reason,
                "operational": self._state == ConnectionState.MARKET_DATA_READY,
                "package_available": self.gateway.package_available(),
                "package_version": self.gateway.package_version(),
                "connected": self._broker_connected and self._terminal_connected,
                "terminal_connected": self._terminal_connected,
                "broker_connected": self._broker_connected,
                "account_available": self._account_available,
                "symbol_available": self._symbol_available,
                "tick_available": self._tick_available,
                "history_available": self._history_available,
                "market_data_ready": self._market_data_ready,
                "terminal": self._terminal_info or self._terminal_info_snapshot,
                "terminal_paths": [str(item["path"]) for item in self._terminal_candidates if item.get("path")],
                "terminal_candidates": self._terminal_candidates,
                "configured_terminal_path": self._configured_terminal_path(),
                "resolved_terminal_path": self._resolved_terminal_path,
                "account": self._account_info or {"available": False},
                "selected_symbol": self._symbol,
                "symbol_info": self._symbol_info,
                "symbol_error": self._symbol_error,
                "timeframe": self._timeframe.value,
                "last_error": last_error,
                "last_error_code": self._last_error_code,
                "last_error_description": self._last_error_description,
                "last_error_stage": self._last_error_stage,
                "last_error_detail": self._last_error_detail,
                "reconnect_attempts": self._reconnect_attempts,
                "next_retry_seconds": max(0, round(self._next_retry_wall - now)) if not self._broker_connected else 0,
                "poll_interval_seconds": self.settings.poll_interval_seconds,
                "connect_timeout_ms": self._connect_timeout_ms,
                "stale_after_seconds": self.settings.stale_after_seconds,
                "freshness": freshness,
                "freshness_reason": reason,
                "time_basis": self._time_basis,
                "server_offset_seconds": self._server_offset,
                "candle_count": len(self._candles),
                "history_requested": self._history_requested,
                "history_returned": self._history_returned,
                "history_warnings": self._candles_warnings,
                "last_successful_update": self._last_successful_update,
                "last_tick_at": self._last_tick_at,
                "last_history_at": self._last_history_at,
                "warnings": list(dict.fromkeys(self._warnings + self._candles_warnings)),
                "ai_available": False,
                "uptime_seconds": round(now - self._started_at),
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            freshness, reason = self.freshness()
            info = self._symbol_info or {}
            quote = self._quote or {}
            bid = _price(quote.get("bid"))
            ask = _price(quote.get("ask"))
            point = _price(info.get("point"))
            digits = int(info.get("digits") or 0)
            spread_price = round(ask - bid, max(digits, 6)) if bid and ask else None
            spread_points = None
            if spread_price is not None and point:
                spread_points = int(round(spread_price / point))

            daily_change = None
            daily_change_pct = None
            daily_reference_time = None
            reference_close = None
            if self._daily:
                reference_close = _price(self._daily.get("close"))
                daily_reference_time = epoch_to_iso(self._utc_epoch(int(self._daily.get("time") or 0)))
            raw_tick_time = int(quote.get("time") or 0)
            tick_time = self._utc_epoch(raw_tick_time)
            price = quote.get("last") or (bid if bid else (self._candles[-1].close if self._candles else None))
            if reference_close and price:
                daily_change = round(float(price) - reference_close, 8)
                daily_change_pct = round((float(price) - reference_close) / reference_close * 100.0, 4)

            last_completed = self._candles[-1] if self._candles else None
            data_state = (
                "cached"
                if (not self._broker_connected and self._candles)
                else ("live" if self._market_data_ready else ("stale" if self._broker_connected else "unavailable"))
            )
            return {
                "provider": self.provider_id,
                "provider_label": self.provider_name,
                "source": "mt5",
                "connected": self._broker_connected and self._terminal_connected,
                "state": self._state.value,
                "operational": self._state == ConnectionState.MARKET_DATA_READY,
                "state_reason": self._state_reason,
                "symbol": self._symbol,
                "symbol_description": info.get("description") or None,
                "timeframe": self._timeframe.value,
                "bid": bid or None,
                "ask": ask or None,
                "last": float(price) if price else None,
                "spread_points": spread_points,
                "spread_price": spread_price,
                "digits": digits,
                "point": point or None,
                "tick_time": tick_time,
                "tick_time_server": raw_tick_time or None,
                "tick_time_iso": epoch_to_iso(tick_time),
                "tick_lag_seconds": round(self._tick_lag_seconds() or 0, 1) if self._quote else None,
                "candle_time": last_completed.time if last_completed else None,
                "candle_time_iso": epoch_to_iso(last_completed.time) if last_completed else None,
                "forming_candle_time": self._forming.time if self._forming else None,
                "tick_volume": last_completed.tick_volume if last_completed else None,
                "daily_change": daily_change,
                "daily_change_percent": daily_change_pct,
                "daily_reference_close": reference_close,
                "daily_reference_time": daily_reference_time,
                "candle_count": len(self._candles),
                "data_state": data_state,
                "stale_reason": reason,
                "last_update": _iso_now(),
                "last_successful_update": self._last_successful_update,
                "server_offset_seconds": self._server_offset,
                "time_basis": self._time_basis,
                "tick_volume_note": TICK_VOLUME_NOTE,
                "warnings": list(dict.fromkeys(self._warnings + (self._candles_warnings if self._candles else []))),
                "candle_source": self._candle_source,
            }

    def candle_series(self, limit: int | None = None, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._symbol is None:
                return self._empty_series("Select a BTC symbol to load candle history.")
            if self._broker_connected and (force or not self._candles):
                self._fetch_candles(force=force)
            if not self._candles and not self._broker_connected:
                self._load_cached_candles()
            requested = max(1, min(limit or self._candle_limit, MAX_HISTORY_CANDLES))
            candles = self._candles[-requested:]
            data_state = (
                "cached"
                if self._candle_source == "local_cache"
                else ("live" if self._market_data_ready else ("stale" if self._broker_connected else "unavailable"))
            )
            return {
                "symbol": self._symbol,
                "timeframe": self._timeframe.value,
                "count": len(candles),
                "candles": [candle.to_dict() for candle in candles],
                "forming_candle": self._forming.to_dict() if self._forming else None,
                "source": self._candle_source,
                "connected": self._broker_connected,
                "data_state": data_state,
                "stale_reason": self._state_reason,
                "time_basis": self._time_basis,
                "server_offset_seconds": self._server_offset,
                "warnings": self._candles_warnings,
                "tick_volume_note": TICK_VOLUME_NOTE,
                "history_requested": self._history_requested,
                "history_returned": self._history_returned,
                "fetched_at": _iso_now(),
            }

    def _empty_series(self, message: str) -> dict[str, Any]:
        return {
            "symbol": self._symbol,
            "timeframe": self._timeframe.value,
            "count": 0,
            "candles": [],
            "forming_candle": None,
            "source": "none",
            "connected": self._broker_connected,
            "data_state": "unavailable",
            "stale_reason": message,
            "time_basis": self._time_basis,
            "server_offset_seconds": self._server_offset,
            "warnings": [message],
            "tick_volume_note": TICK_VOLUME_NOTE,
            "history_requested": 0,
            "history_returned": 0,
            "fetched_at": _iso_now(),
        }

    def completed_candles(self, force: bool = False) -> list[Candle]:
        with self._lock:
            if self._broker_connected and (force or not self._candles):
                self._fetch_candles(force=force)
            return list(self._candles)

    # -------------------------------------------------------------- diagnostics
    def terminal_payload(self) -> dict[str, Any]:
        with self._lock:
            candidates = self._refresh_candidates(force=True)
            return {
                "configured_path": self._configured_terminal_path(),
                "resolved_path": self._resolved_terminal_path,
                "candidates": candidates,
                "detected_paths": [str(item["path"]) for item in candidates],
                "state": self._state.value,
                "connected": self._broker_connected,
                "terminal": self._terminal_info or self._terminal_info_snapshot,
                "account": self._account_info or {"available": False},
            }

    def history_check(self, count: int = MIN_HISTORY_CANDLES) -> dict[str, Any]:
        with self._lock:
            if not self._broker_connected:
                raise MT5DisconnectedError(self._last_error or "MetaTrader 5 is not connected.")
            if not self._symbol:
                raise ValidationError("Select a symbol before checking candle history.")
            requested = max(1, min(int(count), MAX_HISTORY_CANDLES))
            tick_reference: int | None = None
            try:
                tick = self.gateway.tick(self._symbol)
                raw = int(tick.get("time") or 0)
                if raw and self._server_offset is None:
                    self._server_offset = self._estimate_server_offset(raw)
                if raw and self._server_offset is not None:
                    tick_reference = raw - self._server_offset
            except MT5DisconnectedError as exc:
                self._handle_disconnect(exc)
                raise
            except ApiError:
                tick_reference = None

            checks: list[dict[str, Any]] = []
            warnings: list[str] = []
            for timeframe in Timeframe:
                row: dict[str, Any] = {
                    "timeframe": timeframe.value,
                    "requested": requested,
                    "returned": 0,
                    "valid": 0,
                    "completed": 0,
                    "forming": None,
                    "latest": None,
                    "warnings": [],
                    "error": None,
                }
                try:
                    rows = self.gateway.rates(self._symbol, timeframe, requested)
                    row["returned"] = len(rows)
                    if self._server_offset is not None:
                        rows = shift_rows_to_utc(rows, self._server_offset)
                    cleaned, clean_warnings = clean_candles(rows)
                    completed, forming = mark_forming(
                        cleaned, TIMEFRAME_SECONDS[timeframe], tick_reference
                    )
                    row["valid"] = len(cleaned)
                    row["completed"] = len(completed)
                    row["forming"] = forming.to_dict() if forming else None
                    row["latest"] = epoch_to_iso(cleaned[-1].time) if cleaned else None
                    row["warnings"] = clean_warnings
                    if not rows:
                        row["warnings"].append("The broker returned no candles for this timeframe.")
                except MT5DisconnectedError as exc:
                    self._handle_disconnect(exc)
                    row["error"] = exc.message
                    checks.append(row)
                    break
                except ApiError as exc:
                    row["error"] = exc.message
                checks.append(row)
                warnings.extend(f"{timeframe.value}: {warning}" for warning in row["warnings"])

            return {
                "symbol": self._symbol,
                "requested": requested,
                "time_basis": self._time_basis,
                "server_offset_seconds": self._server_offset,
                "checks": checks,
                "warnings": warnings,
                "check_at": _iso_now(),
            }

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            freshness, freshness_reason = self.freshness()
            terminal = self._terminal_info or self._terminal_info_snapshot
            account = self._account_info or {"available": False}
            error = self._last_error_detail or {}
            code = self._last_error_code
            description = self._last_error_description
            error_message = self._last_error

            def check(
                check_id: str,
                label: str,
                ok: bool,
                detail: str,
                *,
                warn: bool = False,
            ) -> dict[str, Any]:
                status = "pass" if ok else ("warn" if warn else "fail")
                return {
                    "id": check_id,
                    "label": label,
                    "ok": ok,
                    "status": status,
                    "detail": detail,
                    "error_code": None if ok else code,
                    "error_description": None if ok else description,
                    "error_message": None if ok else error_message,
                }

            terminal_path = self._resolved_terminal_path or self._configured_terminal_path()
            candidate_count = len(self._terminal_candidates)
            checks = [
                check(
                    "package",
                    "Python MT5 package",
                    self.gateway.package_available(),
                    f"MetaTrader5 {self.gateway.package_version() or 'version unknown'}",
                ),
                check(
                    "terminal_discovery",
                    "Terminal executable discovery",
                    bool(terminal_path),
                    terminal_path or f"{candidate_count} candidate(s) detected; none selected.",
                    warn=bool(candidate_count),
                ),
                check(
                    "initialization",
                    "Terminal initialization",
                    self._terminal_connected,
                    "mt5.initialize() verified" if self._terminal_connected else (self._state_reason or "Not initialized."),
                ),
                check(
                    "ipc",
                    "Terminal IPC",
                    bool(terminal),
                    f"{terminal.get('name') or 'terminal'} build {terminal.get('build') or 'unknown'}"
                    if terminal
                    else "No terminal_info() available.",
                ),
                check(
                    "broker",
                    "Broker connection",
                    bool(terminal.get("connected")) and self._broker_connected,
                    f"Connected to {account.get('server') or 'broker server'}"
                    if terminal.get("connected") and self._broker_connected
                    else "terminal_info.connected is false or unavailable.",
                ),
                check(
                    "account",
                    "Account information",
                    bool(account.get("available")),
                    f"{account.get('login_masked') or 'login hidden'} @ {account.get('server') or 'unknown server'}"
                    if account.get("available")
                    else "account_info() returned nothing; log in to the terminal.",
                ),
                check(
                    "symbol",
                    "Selected symbol availability",
                    bool(self._symbol and self._symbol_available),
                    f"{self._symbol} · {self._symbol_info.get('description') or 'no description'}"
                    if self._symbol
                    else "No symbol selected.",
                ),
                check(
                    "tick",
                    "Live tick availability",
                    bool(self._tick_available and freshness == "fresh"),
                    (
                        f"bid {self._quote.get('bid')} / ask {self._quote.get('ask')} · lag {freshness}"
                        if self._quote
                        else (freshness_reason or "No tick received.")
                    ),
                    warn=bool(self._quote and freshness == "stale"),
                ),
                check(
                    "history",
                    "Historical candle availability",
                    bool(self._candles or self._forming),
                    f"{len(self._candles)} completed bars · {self._history_returned}/{self._history_requested} returned"
                    if (self._candles or self._forming)
                    else "No candle history loaded.",
                ),
                check(
                    "last_update",
                    "Last successful data update",
                    bool(self._last_successful_update),
                    self._last_successful_update or "No successful market data update yet.",
                ),
            ]
            return {
                "state": self._state.value,
                "state_label": STATE_LABELS[self._state],
                "state_reason": self._state_reason,
                "operational": self._state == ConnectionState.MARKET_DATA_READY,
                "checks": checks,
                "package": {
                    "available": self.gateway.package_available(),
                    "version": self.gateway.package_version(),
                },
                "terminal_discovery": {
                    "configured_path": self._configured_terminal_path(),
                    "resolved_path": self._resolved_terminal_path,
                    "candidates": self._terminal_candidates,
                    "error": self._last_error if self._last_error_stage == "discovery" else None,
                },
                "terminal": terminal,
                "account": account,
                "symbol": {
                    "name": self._symbol,
                    "info": self._symbol_info,
                    "available": self._symbol_available,
                    "error": self._symbol_error,
                },
                "tick": {
                    "available": self._tick_available,
                    "freshness": freshness,
                    "reason": freshness_reason,
                    "quote": self._quote,
                    "last_tick_at": self._last_tick_at,
                },
                "history": {
                    "available": self._history_available,
                    "count": len(self._candles),
                    "forming": self._forming.to_dict() if self._forming else None,
                    "requested": self._history_requested,
                    "returned": self._history_returned,
                    "warnings": self._candles_warnings,
                    "last_history_at": self._last_history_at,
                },
                "last_successful_update": self._last_successful_update,
                "last_error": error_message,
                "last_error_code": code,
                "last_error_description": description,
                "last_error_stage": self._last_error_stage,
                "last_error_detail": error,
                "recovery": {
                    "reconnect_attempts": self._reconnect_attempts,
                    "next_retry_seconds": max(0, round(self._next_retry_wall - time.time()))
                    if not self._broker_connected
                    else 0,
                    "connect_timeout_ms": self._connect_timeout_ms,
                },
                "time_basis": self._time_basis,
                "server_offset_seconds": self._server_offset,
                "checked_at": _iso_now(),
            }

    def test_connection(
        self,
        terminal_path: str | None = None,
        symbol: str | None = None,
        include_history: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if terminal_path is not None:
                self.select_terminal(terminal_path)
            else:
                self.connect(force=True)

            symbols: dict[str, Any] | None = None
            if self._broker_connected:
                symbols = self.discover_symbols(refresh=True)

            if symbol and self._broker_connected:
                try:
                    self.select_symbol(symbol)
                except ApiError as exc:
                    self._record_error(exc, "test_selection")

            history: dict[str, Any] | None = None
            if include_history and self._broker_connected and self._symbol:
                try:
                    history = self.history_check()
                except ApiError as exc:
                    self._record_error(exc, "test_history")
            return {
                "status": self.status(),
                "symbols": symbols or self._symbol_payload(),
                "history": history,
                "diagnostics": self.diagnostics(),
            }

    # ------------------------------------------------------------------ events
    def _publish(self) -> None:
        try:
            snapshot = self.snapshot()
            status = self.status()
        except Exception:  # pragma: no cover
            return
        self.broadcaster.publish({"type": "market", "payload": snapshot})
        status_json = json.dumps(status, default=str, sort_keys=True)
        if status_json != self._last_status_json:
            self._last_status_json = status_json
            self.broadcaster.publish({"type": "status", "payload": status})
        for listener in list(self._listeners):
            try:
                listener({"type": "market", "payload": snapshot})
            except Exception:  # pragma: no cover - listeners must not break polling
                logger.debug("MT5 market listener failed", exc_info=True)


class MT5MarketDataProvider(MarketService):
    """Explicit provider adapter for the optional MetaTrader 5 source."""

    provider_id = "mt5"
    provider_name = "MetaTrader 5"
