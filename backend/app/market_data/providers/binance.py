"""Binance spot market data provider.

Public market data only: no API keys, no account access and no order endpoints.
Historical candles come from the REST API and live updates from the public
WebSocket stream. The provider owns one reconnecting stream and never falls back
to another provider when Binance is unavailable.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import STAGE, Settings
from app.core.errors import ApiError, MarketDataUnavailableError, ValidationError
from app.core.timeframes import TIMEFRAME_SECONDS, Timeframe, parse_timeframe
from app.market_data.candles import (
    Candle,
    clean_candles,
    epoch_to_iso,
    mark_forming,
)
from app.market_data.providers.base import MarketDataProvider, MarketEventListener
from app.persistence.repositories import CandleRepository, SettingsRepository, TickRepository

logger = logging.getLogger(__name__)

DEFAULT_SYMBOL = "BTCUSDT"
INTERVALS: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
}
QUOTE_ASSETS = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD"}
MAX_HISTORY = 1500
MIN_HISTORY = 500
# The WebSocket is the primary transport. REST is only reconciliation and
# recovery, never a second high-frequency polling loop.
TICKER_RECONCILE_SECONDS = 60.0
HISTORY_RECONCILE_SECONDS = 300.0
RECOVERY_REFRESH_SECONDS = 10.0
MARKET_NOTIFY_MIN_SECONDS = 1.0
TICK_VOLUME_NOTE = (
    "Binance tick_volume is the number of trades in the bar. real_volume is base-asset volume."
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _tick_size_digits(value: Any) -> int:
    text = str(value or "").strip()
    if not text or "e-" in text.lower():
        return 2
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1].rstrip("0"))


class BinanceMarketDataProvider(MarketDataProvider):
    provider_id = "binance"
    provider_name = "Binance"

    def __init__(
        self,
        settings: Settings,
        settings_repo: SettingsRepository,
        candles_repo: CandleRepository,
        ticks_repo: TickRepository,
        http_client: Any | None = None,
        ws_connect: Any | None = None,
    ) -> None:
        self.settings = settings
        self.settings_repo = settings_repo
        self.candles_repo = candles_repo
        self.ticks_repo = ticks_repo
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(settings.binance_timeout_seconds, connect=5.0),
            follow_redirects=True,
        )
        self._ws_connect = ws_connect
        self._lock = threading.RLock()
        self._enabled = True
        self._connected = False
        self._ws_connected = False
        self._state = "DISCONNECTED"
        self._state_reason = "Binance is not connected yet."
        self._last_error: str | None = None
        self._last_error_stage: str | None = None
        self._last_error_detail: dict[str, Any] | None = None
        self._last_successful_update: str | None = None
        self._last_successful_wall = 0.0
        self._last_ws_wall = 0.0
        self._last_history_at: str | None = None
        self._last_history_wall = 0.0
        self._last_ticker_wall = 0.0
        self._last_tick_at: str | None = None
        self._started_at = time.time()

        self._symbol = str(settings_repo.get("binance.symbol") or settings.binance_symbol or DEFAULT_SYMBOL).upper()
        self._timeframe = parse_timeframe(settings_repo.get("market.timeframe") or settings.default_timeframe)
        stored_limit = settings_repo.get("market.candle_limit")
        self._candle_limit = max(
            60,
            min(MAX_HISTORY, int(stored_limit) if isinstance(stored_limit, (int, float)) else settings.default_candle_limit),
        )
        self._candles: list[Candle] = []
        self._forming: Candle | None = None
        self._quote: dict[str, Any] = {}
        self._ticker: dict[str, Any] = {}
        self._symbol_info = self._base_symbol_info()
        self._symbol_available = False
        self._symbol_error: str | None = None
        self._symbol_cache: list[dict[str, Any]] = []
        self._symbol_cache_wall = 0.0
        self._symbol_cache_error: str | None = None
        self._history_requested = 0
        self._history_returned = 0
        self._warnings: list[str] = []
        self._reconnect_attempts = 0
        self._next_retry_wall = 0.0
        self._ws_stop = threading.Event()
        self._ws_thread: threading.Thread | None = None
        self._listeners: list[MarketEventListener] = []
        self._last_tick_persisted = 0.0
        self._http_retries = 2
        self._ws_retry_seconds = 1.0
        self._stop_event = threading.Event()
        self._history_fetch_lock = threading.Lock()
        self._last_market_notify_wall = 0.0
        self._last_kline_at: str | None = None
        self._last_kline_latency_ms: float | None = None
        self._kline_events = 0
        self._last_market_publish_at: str | None = None

    # --------------------------------------------------------------- interface
    @property
    def candle_limit(self) -> int:
        return self._candle_limit

    def subscribe(self, listener: MarketEventListener) -> Any:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:  # pragma: no cover - listeners must not break the provider
                logger.debug("Binance market listener failed", exc_info=True)

    def _notify(self) -> None:
        if not self._listeners:
            return
        try:
            event = {"type": "market", "payload": self.snapshot()}
        except Exception:  # pragma: no cover - listeners must not break the provider
            return
        self._last_market_publish_at = _iso_now()
        self._emit(event)

    def _notify_market(self, force: bool = False) -> None:
        """Publish a full snapshot at a bounded cadence.

        The chart uses the compact `candle` event for high-frequency updates;
        the rest of the UI gets a full snapshot at most twice per second. Closed
        candles bypass the throttle so a confirmed bar is never held back.
        """

        now = time.monotonic()
        if not force and now - self._last_market_notify_wall < MARKET_NOTIFY_MIN_SECONDS:
            return
        self._last_market_notify_wall = now
        self._notify()

    def _notify_candle(
        self,
        candle: Candle,
        closed: bool,
        event_time_ms: int | None = None,
    ) -> None:
        if not self._listeners:
            return
        received_at = time.time()
        latency_ms = None
        if event_time_ms:
            latency_ms = max(0.0, received_at * 1000.0 - float(event_time_ms))
        payload = {
            "symbol": self._symbol,
            "timeframe": self._timeframe.value,
            "closed": bool(closed),
            "candle": candle.to_dict(),
            "exchange_event_ms": event_time_ms,
            "received_at": _iso_now(),
            "receive_latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            # Identity used by the forecast scheduler to reject duplicate closes.
            "close_identity": f"{self._symbol}:{self._timeframe.value}:{candle.time}",
        }
        self._emit({"type": "candle", "payload": payload})

    def _set_error(self, message: str, stage: str, details: dict[str, Any] | None = None) -> None:
        self._last_error = message
        self._last_error_stage = stage
        self._last_error_detail = details
        self._state_reason = message

    def _clear_error(self) -> None:
        self._last_error = None
        self._last_error_stage = None
        self._last_error_detail = None

    def _base_symbol_info(self) -> dict[str, Any]:
        return {
            "name": self._symbol,
            "description": "Bitcoin / TetherUS",
            "path": "Spot",
            "digits": 2,
            "point": 0.01,
            "spread": None,
            "visible": True,
            "currency_base": "BTC",
            "currency_profit": "USDT",
            "btc_like": True,
            "exchange": "Binance Spot",
        }

    # -------------------------------------------------------------------- HTTP
    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        base = self.settings.binance_rest_url.rstrip("/")
        url = path if path.startswith("http") else f"{base}{path}"
        last_error: Exception | None = None
        for attempt in range(self._http_retries):
            try:
                response = self._http.get(url, params=params)
                if hasattr(response, "raise_for_status"):
                    response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001 - normalized into a provider error
                last_error = exc
                if attempt + 1 < self._http_retries:
                    time.sleep(0.4 * (attempt + 1))
        message = f"Binance REST request failed: {last_error}"
        details = {"url": url, "error": str(last_error)}
        raise MarketDataUnavailableError(message, details, code="BINANCE_REST_UNAVAILABLE") from last_error

    # --------------------------------------------------------------- lifecycle
    def connect(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            self._enabled = True
            if self._connected and not force and self._candles:
                self._ensure_ws()
                return self.status()
            self._state = "CONNECTING"
            self._state_reason = "Connecting to Binance public market data."
            try:
                self._refresh_ticker()
                self._refresh_history(force=True)
            except ApiError as exc:
                self._connected = False
                self._state = "ERROR"
                self._set_error(exc.message, "connect", exc.details)
                self._schedule_retry()
                logger.warning("Binance REST connection failed: %s", exc.message)
                return self.status()
            except Exception as exc:  # pragma: no cover - defensive
                self._connected = False
                self._state = "ERROR"
                self._set_error(f"Unexpected Binance connection error: {exc}", "connect")
                self._schedule_retry()
                return self.status()

            self._connected = True
            self._reconnect_attempts = 0
            self._next_retry_wall = 0.0
            self._clear_error()
            self._state = "CONNECTED"
            self._state_reason = "Binance REST history loaded; starting the live stream."
            self._ensure_ws()
            logger.info("Binance spot history loaded for %s %s", self._symbol, self._timeframe.value)
            self._notify()
            return self.status()

    def reconnect(self) -> dict[str, Any]:
        return self.connect(force=True)

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self._enabled = False
            self._stop_ws()
            self._connected = False
            self._ws_connected = False
            self._state = "DISCONNECTED"
            self._state_reason = "Disconnected by user. Click Reconnect to resume Binance data."
            self._set_error("Disconnected by user.", "manual")
            self._notify()
            return self.status()

    def stop(self) -> None:
        with self._lock:
            self._enabled = False
            self._stop_event.set()
            self._stop_ws()
            self._connected = False
            self._ws_connected = False
            self._state = "DISCONNECTED"
            self._state_reason = "The backend is shutting down."

    def _schedule_retry(self) -> None:
        self._reconnect_attempts = min(self._reconnect_attempts + 1, 20)
        delay = min(30.0, float(2 ** min(self._reconnect_attempts, 5)))
        self._next_retry_wall = time.time() + delay

    def poll_once(self) -> None:
        with self._lock:
            if not self._enabled:
                return
            if not self._connected:
                self.connect()
                return
            now = time.time()
            ws_lagging = not self._ws_connected or (
                self._last_ws_wall and now - self._last_ws_wall > self.settings.stale_after_seconds
            )
            recovery_due = now - self._last_history_wall >= RECOVERY_REFRESH_SECONDS
            try:
                if (ws_lagging and recovery_due) or now - self._last_ticker_wall >= TICKER_RECONCILE_SECONDS:
                    self._refresh_ticker()
                if (
                    (ws_lagging and recovery_due)
                    or not self._candles
                    or now - self._last_history_wall >= HISTORY_RECONCILE_SECONDS
                ):
                    self._refresh_history()
            except ApiError as exc:
                self._set_error(exc.message, "refresh", exc.details)
                self._schedule_retry()
            except Exception as exc:  # pragma: no cover
                self._set_error(f"Binance refresh failed: {exc}", "refresh")
                self._schedule_retry()
            self._ensure_ws()
            self._refresh_state()
            # WS notifications own the hot path. This snapshot is only for
            # recovery, when the socket is down or no tick has arrived yet.
            if ws_lagging:
                self._notify()

    # ------------------------------------------------------------- REST data
    def _refresh_ticker(self) -> None:
        payload = self._request_json("/api/v3/ticker/24hr", {"symbol": self._symbol})
        if not isinstance(payload, dict) or not payload.get("symbol"):
            raise MarketDataUnavailableError(
                f"Binance returned no 24h ticker for {self._symbol}.",
                code="BINANCE_TICKER_UNAVAILABLE",
            )
        self._ticker = payload
        bid = _as_float(payload.get("bidPrice"))
        ask = _as_float(payload.get("askPrice"))
        last = _as_float(payload.get("lastPrice"))
        self._quote.update({"bid": bid, "ask": ask, "last": last})
        self._last_ticker_wall = time.time()
        self._symbol_available = last is not None
        if not self._symbol_available:
            self._symbol_error = f"Binance did not return a price for {self._symbol}."
        else:
            self._symbol_error = None

    def _refresh_history(self, force: bool = False) -> None:
        requested = max(MIN_HISTORY, self._candle_limit + 5)
        requested = min(requested, MAX_HISTORY)
        interval = INTERVALS[self._timeframe]
        payload = self._request_json(
            "/api/v3/klines",
            {"symbol": self._symbol, "interval": interval, "limit": requested},
        )
        if not isinstance(payload, list) or not payload:
            self._history_requested = requested
            self._history_returned = 0
            self._warnings = [
                f"Binance returned no {self._timeframe.value} candles for {self._symbol}. Nothing was fabricated."
            ]
            return

        rows: list[dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, (list, tuple)) or len(row) < 9:
                continue
            try:
                rows.append(
                    {
                        "time": int(row[0]) // 1000,
                        "server_time": int(row[6]) // 1000,
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "tick_volume": int(row[8]),
                        "real_volume": int(float(row[5])),
                        "spread": 0,
                        "source": "binance",
                        "symbol": self._symbol,
                    }
                )
            except (TypeError, ValueError):
                continue
        cleaned, warnings = clean_candles(rows)
        completed, forming = mark_forming(
            cleaned,
            TIMEFRAME_SECONDS[self._timeframe],
            int(time.time()),
        )
        if len(rows) < requested:
            warnings.append(f"Binance returned {len(rows)} of {requested} requested {self._timeframe.value} candles.")
        self._candles = completed[-self._candle_limit :]
        self._forming = forming
        self._history_requested = requested
        self._history_returned = len(rows)
        self._warnings = warnings
        self._last_history_at = _iso_now()
        self._last_history_wall = time.time()
        self._last_successful_update = _iso_now()
        self._last_successful_wall = time.time()
        if completed:
            try:
                self.candles_repo.upsert_many(
                    self._symbol,
                    self._timeframe.value,
                    completed[-50:],
                    source="binance",
                )
            except Exception:  # pragma: no cover - cache writes are best effort
                logger.debug("Binance candle cache write failed", exc_info=True)
        if not completed and not forming:
            self._warnings = [*warnings, "No valid Binance candles remained after integrity checks."]

    def _refresh_state(self) -> None:
        freshness, reason = self.freshness()
        if not self._connected:
            self._state = "CACHED" if self._candles else "DISCONNECTED"
            self._state_reason = self._last_error or "Binance is disconnected."
        elif freshness == "fresh" and (self._candles or self._forming):
            self._state = "MARKET_DATA_READY"
            self._state_reason = "Binance REST history and live WebSocket updates are available."
        elif self._candles or self._forming:
            self._state = "STALE"
            self._state_reason = reason or "Binance data is stale."
        else:
            self._state = "WAITING_FOR_MARKET_DATA"
            self._state_reason = reason or "Waiting for Binance candles."

    # ------------------------------------------------------------- websocket
    def _ws_url(self) -> str:
        interval = INTERVALS[self._timeframe]
        symbol = self._symbol.lower()
        base = self.settings.binance_ws_url.rstrip("/")
        return f"{base}/stream?streams={symbol}@kline_{interval}/{symbol}@bookTicker"

    def _ensure_ws(self) -> None:
        if not self._enabled:
            return
        if self._ws_thread is not None and self._ws_thread.is_alive():
            return
        self._ws_stop = threading.Event()
        self._ws_thread = threading.Thread(
            target=self._ws_loop,
            name="kbmti-binance-stream",
            daemon=True,
        )
        self._ws_thread.start()

    def _stop_ws(self) -> None:
        self._ws_stop.set()
        thread = self._ws_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._ws_thread = None
        self._ws_connected = False

    def _ws_loop(self) -> None:
        delay = 1.0
        while not self._ws_stop.is_set():
            try:
                connector = self._ws_connect or _default_ws_connect()
                with connector(
                    self._ws_url(),
                    open_timeout=10,
                    close_timeout=2,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2**20,
                ) as websocket:
                    with self._lock:
                        self._ws_connected = True
                        self._ws_retry_seconds = 1.0
                        self._clear_error()
                        self._refresh_state()
                        self._notify()
                    delay = 1.0
                    logger.info("Binance WebSocket connected for %s %s", self._symbol, self._timeframe.value)
                    # A reconnect can miss close frames. Reconcile once against
                    # REST before consuming the new live stream.
                    try:
                        with self._history_fetch_lock:
                            self._refresh_history(force=True)
                        self._notify()
                    except Exception:  # noqa: BLE001 - live stream remains authoritative
                        logger.debug("Binance reconnect reconciliation failed", exc_info=True)
                    for raw in websocket:
                        if self._ws_stop.is_set():
                            break
                        self._handle_ws_message(raw)
            except Exception as exc:  # noqa: BLE001 - reconnect loop must survive
                if not self._ws_stop.is_set():
                    logger.warning("Binance WebSocket disconnected: %s. Retrying in %.0fs.", exc, delay)
                    with self._lock:
                        self._ws_connected = False
                        self._set_error(f"Binance WebSocket disconnected: {exc}", "websocket")
                        self._refresh_state()
                        self._notify()
                    if self._ws_stop.wait(delay):
                        break
                    delay = min(30.0, delay * 2)
            finally:
                with self._lock:
                    self._ws_connected = False

    def _handle_ws_message(self, raw: Any) -> None:
        import json

        try:
            envelope = raw if isinstance(raw, dict) else json.loads(str(raw))
            data = envelope.get("data") if isinstance(envelope, dict) else None
            if not isinstance(data, dict):
                return
            event = data.get("e")
            if event == "kline":
                self._handle_kline(data.get("k") or {}, data.get("E"))
            elif event == "bookTicker" or ({"b", "a"} <= set(data)):
                self._handle_book(data)
        except Exception:  # pragma: no cover - malformed public payloads are ignored
            logger.debug("Invalid Binance WebSocket payload", exc_info=True)

    def _handle_kline(self, kline: dict[str, Any], event_time_ms: Any = None) -> None:
        try:
            open_time = int(kline["t"]) // 1000
            close_time = int(kline["T"]) // 1000
            candle = Candle(
                time=open_time,
                server_time=close_time,
                open=float(kline["o"]),
                high=float(kline["h"]),
                low=float(kline["l"]),
                close=float(kline["c"]),
                tick_volume=int(kline.get("n") or 0),
                real_volume=int(float(kline.get("v") or 0)),
                source="binance",
                symbol=self._symbol,
            )
            exchange_ms = int(event_time_ms or kline.get("E") or 0) or None
        except (KeyError, TypeError, ValueError):
            return
        closed = bool(kline.get("x"))
        with self._lock:
            if closed:
                self._candles = [item for item in self._candles if item.time != open_time]
                self._candles.append(candle)
                self._candles.sort(key=lambda item: item.time)
                self._candles = self._candles[-self._candle_limit :]
                if self._forming and self._forming.time == open_time:
                    self._forming = None
            else:
                # Binance's forming kline replaces the in-memory bar; it is
                # never inserted into the completed-candle list.
                self._forming = candle
                self._candles = [item for item in self._candles if item.time != open_time]
            # Use the exchange event time, not the bar's future close boundary,
            # so the UI's "last tick" timestamp and lag are truthful while a
            # candle is still forming.
            quote_time = int(exchange_ms // 1000) if exchange_ms else int(time.time())
            self._quote.update({"last": candle.close, "time": quote_time})
            self._last_ws_wall = time.time()
            self._last_tick_at = epoch_to_iso(quote_time)
            self._last_kline_at = _iso_now()
            self._kline_events += 1
            if exchange_ms:
                self._last_kline_latency_ms = round(
                    max(0.0, time.time() * 1000.0 - float(exchange_ms)), 2
                )
            self._last_successful_update = _iso_now()
            self._last_successful_wall = time.time()
            if self._last_error_stage == "websocket":
                self._clear_error()
            self._refresh_state()

        # Push the forming/confirmed candle before any persistence work. The
        # chart must never wait for a SQLite write.
        self._notify_candle(candle, closed, exchange_ms)
        self._notify_market(force=closed)
        if closed:
            try:
                self.candles_repo.upsert_many(
                    self._symbol, self._timeframe.value, [candle], source="binance"
                )
            except Exception:  # pragma: no cover
                logger.debug("Binance live candle cache write failed", exc_info=True)
        self._persist_tick()

    def _handle_book(self, data: dict[str, Any]) -> None:
        bid = _as_float(data.get("b"))
        ask = _as_float(data.get("a"))
        with self._lock:
            if bid:
                self._quote["bid"] = bid
            if ask:
                self._quote["ask"] = ask
            self._last_ws_wall = time.time()
            self._last_successful_update = _iso_now()
            self._last_successful_wall = time.time()
            if self._last_error_stage == "websocket":
                self._clear_error()
            self._refresh_state()

    def _persist_tick(self) -> None:
        now = time.time()
        if now - self._last_tick_persisted < 5.0:
            return
        quote = self._quote
        if not quote.get("last"):
            return
        try:
            self.ticks_repo.insert(
                self._symbol,
                int(quote.get("time") or now),
                quote.get("bid"),
                quote.get("ask"),
                quote.get("last"),
            )
            self._last_tick_persisted = now
        except Exception:  # pragma: no cover
            logger.debug("Binance tick persistence failed", exc_info=True)

    # ---------------------------------------------------------------- symbols
    def get_symbols(self, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            if not refresh and self._symbol_cache and now - self._symbol_cache_wall < self.settings.symbol_cache_seconds:
                return self._symbol_payload()
            try:
                payload = self._request_json("/api/v3/exchangeInfo")
                raw_symbols = payload.get("symbols", []) if isinstance(payload, dict) else []
                symbols: list[dict[str, Any]] = []
                for item in raw_symbols:
                    if not isinstance(item, dict):
                        continue
                    if item.get("status") != "TRADING" or item.get("baseAsset") != "BTC":
                        continue
                    quote = str(item.get("quoteAsset") or "")
                    if quote not in QUOTE_ASSETS:
                        continue
                    name = str(item.get("symbol") or "")
                    filters = {entry.get("filterType"): entry for entry in item.get("filters", []) if isinstance(entry, dict)}
                    tick_size = filters.get("PRICE_FILTER", {}).get("tickSize")
                    symbols.append(
                        {
                            "name": name,
                            "description": f"Bitcoin / {quote}",
                            "path": "Binance Spot",
                            "digits": _tick_size_digits(tick_size),
                            "point": float(tick_size) if tick_size else 0.01,
                            "spread": None,
                            "visible": True,
                            "currency_base": "BTC",
                            "currency_profit": quote,
                            "btc_like": True,
                            "recommended": name == DEFAULT_SYMBOL,
                            "match_score": 100 if name == DEFAULT_SYMBOL else 90,
                            "match_reason": "Binance spot BTC pair",
                            "bid": _as_float((self._ticker or {}).get("bidPrice")) if name == self._symbol else None,
                            "ask": _as_float((self._ticker or {}).get("askPrice")) if name == self._symbol else None,
                        }
                    )
                symbols.sort(key=lambda entry: (not entry["recommended"], entry["name"]))
                self._symbol_cache = symbols
                self._symbol_cache_wall = now
                self._symbol_cache_error = None
            except ApiError as exc:
                self._symbol_cache = []
                self._symbol_cache_error = exc.message
                logger.warning("Binance symbol discovery failed: %s", exc.message)
            return self._symbol_payload()

    def _symbol_payload(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "state": self._state,
            "symbols": self._symbol_cache,
            "count": len(self._symbol_cache),
            "total_broker_symbols": len(self._symbol_cache),
            "selected_symbol": self._symbol,
            "error": self._symbol_cache_error,
            "note": "Binance Spot BTC pairs. BTCUSDT is recommended and used by default.",
            "fetched_at": epoch_to_iso(int(self._symbol_cache_wall)) if self._symbol_cache_wall else None,
        }

    def select_symbol(self, symbol: str) -> dict[str, Any]:
        cleaned = (symbol or "").strip().upper()
        if not cleaned:
            raise ValidationError("A symbol name is required.")
        symbols = self.get_symbols(refresh=True).get("symbols", [])
        available = {str(item.get("name")) for item in symbols}
        if available and cleaned not in available:
            raise ValidationError(f"Binance spot symbol '{cleaned}' is not available.")
        with self._lock:
            self._symbol = cleaned
            self._symbol_info = self._base_symbol_info()
            self._symbol_info["name"] = cleaned
            self._symbol_info["description"] = self._symbol_info.get("description") or "Bitcoin"
            self._symbol_error = None
            self.settings_repo.set("binance.symbol", cleaned)
            self._candles = []
            self._forming = None
            self._quote = {}
            self._ticker = {}
            self._last_history_wall = 0.0
            self._stop_ws()
            self._connected = False
            return {"selected_symbol": cleaned, "btc_like": True, "status": self.connect(force=True)}

    def set_timeframe(self, value: str) -> dict[str, Any]:
        try:
            timeframe = parse_timeframe(value)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        with self._lock:
            self._timeframe = timeframe
            self.settings_repo.set("market.timeframe", timeframe.value)
            self._candles = []
            self._forming = None
            self._last_history_wall = 0.0
            self._stop_ws()
            if self._connected:
                try:
                    self._refresh_history(force=True)
                except ApiError as exc:
                    self._set_error(exc.message, "history", exc.details)
                self._ensure_ws()
            self._refresh_state()
            return {"timeframe": timeframe.value, "status": self.status()}

    def set_candle_limit(self, limit: int) -> int:
        with self._lock:
            self._candle_limit = max(60, min(MAX_HISTORY, int(limit)))
            self.settings_repo.set("market.candle_limit", self._candle_limit)
            return self._candle_limit

    # --------------------------------------------------------------- freshness
    def freshness(self) -> tuple[str, str | None]:
        if not self._connected:
            return "unavailable", self._last_error or "Binance is not connected."
        if not self._candles and not self._forming:
            return "unavailable", "No Binance candle history is loaded."
        if not self._last_ws_wall:
            return "stale", "Binance history is loaded; waiting for the live WebSocket."
        if not self._ws_connected:
            return "stale", "Binance WebSocket is reconnecting."
        lag = time.time() - self._last_ws_wall
        if lag > self.settings.stale_after_seconds:
            return "stale", f"No Binance update for {int(lag)} seconds."
        return "fresh", None

    # ---------------------------------------------------------------- payloads
    def _last_completed(self) -> Candle | None:
        return self._candles[-1] if self._candles else None

    def _price(self) -> float | None:
        for key in ("last", "bid", "ask"):
            value = _as_float(self._quote.get(key))
            if value:
                return value
        for key in ("lastPrice", "bidPrice", "askPrice"):
            value = _as_float(self._ticker.get(key))
            if value:
                return value
        return None

    def status(self) -> dict[str, Any]:
        with self._lock:
            freshness, reason = self.freshness()
            last_error = self._last_error or (None if self._connected else "Binance is not connected.")
            return {
                "stage": STAGE,
                "provider": self.provider_id,
                "provider_label": self.provider_name,
                "state": self._state,
                "state_label": _state_label(self._state),
                "state_reason": self._state_reason or reason,
                "operational": self._state == "MARKET_DATA_READY",
                "package_available": True,
                "package_version": "REST + WebSocket",
                "connected": self._connected,
                "rest_connected": self._connected,
                "ws_connected": self._ws_connected,
                "terminal_connected": False,
                "broker_connected": self._connected,
                "symbol_available": self._symbol_available,
                "tick_available": bool(self._quote.get("last")),
                "history_available": bool(self._candles or self._forming),
                "market_data_ready": self._state == "MARKET_DATA_READY",
                "selected_symbol": self._symbol,
                "symbol_info": self._symbol_info,
                "symbol_error": self._symbol_error,
                "timeframe": self._timeframe.value,
                "last_error": last_error,
                "last_error_stage": self._last_error_stage,
                "last_error_detail": self._last_error_detail,
                "reconnect_attempts": self._reconnect_attempts,
                "next_retry_seconds": max(0, round(self._next_retry_wall - time.time()))
                if not self._connected
                else 0,
                "poll_interval_seconds": self.settings.poll_interval_seconds,
                "connect_timeout_ms": int(self.settings.binance_timeout_seconds * 1000),
                "stale_after_seconds": self.settings.stale_after_seconds,
                "freshness": freshness,
                "freshness_reason": reason,
                "time_basis": "utc",
                "server_offset_seconds": 0,
                "candle_count": len(self._candles),
                "history_requested": self._history_requested,
                "history_returned": self._history_returned,
                "history_warnings": list(self._warnings),
                "last_successful_update": self._last_successful_update,
                "last_tick_at": self._last_tick_at,
                "last_history_at": self._last_history_at,
                "last_kline_at": self._last_kline_at,
                "last_kline_latency_ms": self._last_kline_latency_ms,
                "kline_events": self._kline_events,
                "warnings": list(self._warnings),
                "ai_available": False,
                "uptime_seconds": round(time.time() - self._started_at),
                "rest_base": self.settings.binance_rest_url,
                "ws_base": self.settings.binance_ws_url,
                "source": "binance",
            }

    def get_connection_status(self) -> dict[str, Any]:
        return self.status()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            freshness, reason = self.freshness()
            ticker = self._ticker or {}
            quote = self._quote or {}
            bid = _as_float(quote.get("bid")) or _as_float(ticker.get("bidPrice"))
            ask = _as_float(quote.get("ask")) or _as_float(ticker.get("askPrice"))
            price = self._price()
            point = 0.01
            digits = 2
            spread_price = round(ask - bid, 6) if bid and ask and ask >= bid else None
            spread_points = int(round(spread_price / point)) if spread_price is not None else None
            open_price = _as_float(ticker.get("openPrice"))
            daily_change = round(price - open_price, 8) if price and open_price else None
            daily_pct = round((price - open_price) / open_price * 100.0, 4) if price and open_price else None
            completed = self._last_completed()
            raw_time = int(quote.get("time") or self._last_ws_wall or 0)
            data_state = (
                "cached"
                if not self._connected and self._candles
                else "live"
                if freshness == "fresh"
                else "stale"
                if self._connected or self._candles
                else "unavailable"
            )
            return {
                "provider": self.provider_id,
                "provider_label": self.provider_name,
                "connected": self._connected,
                "state": self._state,
                "operational": self._state == "MARKET_DATA_READY",
                "state_reason": self._state_reason or reason,
                "symbol": self._symbol,
                "symbol_description": "Bitcoin / TetherUS (Binance Spot)",
                "timeframe": self._timeframe.value,
                "bid": bid,
                "ask": ask,
                "last": price,
                "spread_points": spread_points,
                "spread_price": spread_price,
                "digits": digits,
                "point": point,
                "tick_time": raw_time or None,
                "tick_time_server": raw_time or None,
                "tick_time_iso": epoch_to_iso(raw_time) if raw_time else None,
                "tick_lag_seconds": round(time.time() - self._last_ws_wall, 1) if self._last_ws_wall else None,
                "candle_time": completed.time if completed else None,
                "candle_time_iso": epoch_to_iso(completed.time) if completed else None,
                "forming_candle_time": self._forming.time if self._forming else None,
                "forming_candle": self._forming.to_dict() if self._forming else None,
                "last_candle": completed.to_dict() if completed else None,
                "last_kline_at": self._last_kline_at,
                "last_kline_latency_ms": self._last_kline_latency_ms,
                "tick_volume": completed.tick_volume if completed else None,
                "daily_change": daily_change,
                "daily_change_percent": daily_pct,
                "daily_reference_close": open_price,
                "daily_reference_time": None,
                "candle_count": len(self._candles),
                "data_state": data_state,
                "stale_reason": reason,
                "last_update": _iso_now(),
                "last_successful_update": self._last_successful_update,
                "server_offset_seconds": 0,
                "time_basis": "utc",
                "tick_volume_note": TICK_VOLUME_NOTE,
                "warnings": list(self._warnings),
                "candle_source": "binance",
                "source": "binance",
            }

    def candle_series(self, limit: int | None = None, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._connected and (force or not self._candles):
                self._refresh_history(force=force)
            requested = max(1, min(limit or self._candle_limit, MAX_HISTORY))
            candles = self._candles[-requested:]
            freshness, reason = self.freshness()
            data_state = (
                "cached"
                if not self._connected and candles
                else "live"
                if freshness == "fresh"
                else "stale"
                if self._connected or candles
                else "unavailable"
            )
            return {
                "symbol": self._symbol,
                "timeframe": self._timeframe.value,
                "count": len(candles),
                "candles": [candle.to_dict() for candle in candles],
                "forming_candle": self._forming.to_dict() if self._forming else None,
                "source": "binance",
                "connected": self._connected,
                "data_state": data_state,
                "stale_reason": reason,
                "time_basis": "utc",
                "server_offset_seconds": 0,
                "warnings": list(self._warnings),
                "tick_volume_note": TICK_VOLUME_NOTE,
                "history_requested": self._history_requested,
                "history_returned": self._history_returned,
                "fetched_at": _iso_now(),
            }

    def completed_candles(self, force: bool = False) -> list[Candle]:
        with self._lock:
            if self._connected and (force or not self._candles):
                self._refresh_history(force=force)
            return list(self._candles)

    def get_historical_candles(self, timeframe: str, limit: int) -> list[Candle]:
        parsed = parse_timeframe(timeframe)
        with self._lock:
            if parsed != self._timeframe:
                self.set_timeframe(parsed.value)
            if self._connected:
                self._refresh_history(force=True)
            return list(self._candles[-max(1, min(limit, MAX_HISTORY)) :])

    # -------------------------------------------------------------- diagnostics
    def diagnostics(self) -> dict[str, Any]:
        status = self.status()
        freshness, reason = self.freshness()
        checks = [
            {
                "id": "rest",
                "label": "Binance REST API",
                "ok": self._connected,
                "status": "pass" if self._connected else "fail",
                "detail": self.settings.binance_rest_url if self._connected else (self._last_error or "Not connected."),
            },
            {
                "id": "websocket",
                "label": "Binance WebSocket",
                "ok": self._ws_connected,
                "status": "pass" if self._ws_connected else "warn",
                "detail": self._ws_url() if self._ws_connected else "Reconnecting.",
            },
            {
                "id": "symbol",
                "label": "Selected symbol",
                "ok": self._symbol_available,
                "status": "pass" if self._symbol_available else "warn",
                "detail": self._symbol,
            },
            {
                "id": "history",
                "label": "Historical candles",
                "ok": bool(self._candles or self._forming),
                "status": "pass" if (self._candles or self._forming) else "fail",
                "detail": f"{len(self._candles)} completed bars",
            },
            {
                "id": "freshness",
                "label": "Live data freshness",
                "ok": freshness == "fresh",
                "status": "pass" if freshness == "fresh" else "warn",
                "detail": reason or freshness,
            },
        ]
        return {
            "provider": self.provider_id,
            "provider_name": self.provider_name,
            "state": self._state,
            "state_label": _state_label(self._state),
            "state_reason": self._state_reason,
            "operational": self._state == "MARKET_DATA_READY",
            "checks": checks,
            "symbol": self._symbol,
            "timeframe": self._timeframe.value,
            "freshness": freshness,
            "freshness_reason": reason,
            "last_error": self._last_error,
            "last_error_stage": self._last_error_stage,
            "last_successful_update": self._last_successful_update,
            "realtime": {
                "last_kline_at": self._last_kline_at,
                "last_exchange_to_receive_ms": self._last_kline_latency_ms,
                "kline_events": self._kline_events,
                "last_market_publish_at": self._last_market_publish_at,
                "snapshot_throttle_ms": int(MARKET_NOTIFY_MIN_SECONDS * 1000),
                "history_reconcile_seconds": HISTORY_RECONCILE_SECONDS,
                "ticker_reconcile_seconds": TICKER_RECONCILE_SECONDS,
            },
            "rest_base": self.settings.binance_rest_url,
            "ws_base": self.settings.binance_ws_url,
            "recovery": {
                "reconnect_attempts": self._reconnect_attempts,
                "next_retry_seconds": status["next_retry_seconds"],
            },
            "checked_at": _iso_now(),
        }


def _state_label(state: str) -> str:
    return {
        "DISCONNECTED": "Disconnected",
        "CONNECTING": "Connecting",
        "CONNECTED": "Connected",
        "WAITING_FOR_MARKET_DATA": "Waiting for market data",
        "STALE": "Stale data",
        "MARKET_DATA_READY": "Market data ready",
        "ERROR": "Error",
        "CACHED": "Cached history",
    }.get(state, state)


def _default_ws_connect() -> Any:
    from websockets.sync.client import connect

    return connect
