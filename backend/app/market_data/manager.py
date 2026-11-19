"""Single-source market data orchestration for KBMTI.

Exactly one provider is active. The manager delegates the chart, quote, history,
indicator, statistics and signal paths to that provider and never merges candles
or silently switches sources after a failure.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from app.core.config import Settings
from app.core.errors import ProviderSelectionError
from app.market_data.broadcaster import Broadcaster
from app.market_data.candles import Candle
from app.market_data.mt5_gateway import MT5Gateway
from app.market_data.providers.base import MarketDataProvider
from app.market_data.providers.binance import BinanceMarketDataProvider
from app.market_data.service import MT5MarketDataProvider
from app.persistence.repositories import SettingsRepository

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {"binance": "Binance", "mt5": "MetaTrader 5"}
DEFAULT_PROVIDER = "binance"


class MarketDataService:
    """The selected provider is the only source used by the rest of the app."""

    def __init__(
        self,
        settings: Settings,
        settings_repo: SettingsRepository,
        binance: BinanceMarketDataProvider,
        mt5: MT5MarketDataProvider,
        broadcaster: Broadcaster | None = None,
    ) -> None:
        self.settings = settings
        self.settings_repo = settings_repo
        self.binance = binance
        self.mt5 = mt5
        self.broadcaster = broadcaster or Broadcaster()
        self._providers: dict[str, MarketDataProvider] = {"binance": binance, "mt5": mt5}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._started_at = time.time()
        self._last_status_signature: tuple[Any, ...] | None = None

        stored = settings_repo.get("market.provider")
        selected = str(stored or settings.default_provider or DEFAULT_PROVIDER).lower()
        if selected not in self._providers:
            selected = DEFAULT_PROVIDER
        self._provider_id = selected
        # First launch explicitly records Binance as the default.
        if not stored:
            settings_repo.set("market.provider", selected)
        logger.info("Market data provider selected: %s", selected)

    # ------------------------------------------------------------------ source
    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider(self) -> MarketDataProvider:
        return self._providers[self._provider_id]

    @property
    def active_provider(self) -> str:
        return self._provider_id

    @property
    def candle_limit(self) -> int:
        return self.provider.candle_limit

    @property
    def _candle_limit(self) -> int:  # compatibility for settings diagnostics
        return self.provider.candle_limit

    def provider_ids(self) -> list[str]:
        return list(self._providers)

    def _validate_provider(self, provider_id: str) -> str:
        normalized = str(provider_id or "").strip().lower()
        if normalized not in self._providers:
            raise ProviderSelectionError(
                f"Unsupported market data provider '{provider_id}'. Choose binance or mt5.",
                {"supported": list(self._providers)},
            )
        return normalized

    def _prepare_provider(self, provider_id: str) -> None:
        """Carry global timeframe/limit into a provider before it is selected."""
        provider = self._providers[provider_id]
        timeframe = self.settings_repo.get("market.timeframe") or self.settings.default_timeframe
        limit = self.settings_repo.get("market.candle_limit") or self.settings.default_candle_limit
        try:
            provider.set_timeframe(str(timeframe))
        except Exception:  # pragma: no cover - provider-specific cleanup is best effort
            logger.debug("Could not prepare timeframe for %s", provider_id, exc_info=True)
        try:
            provider.set_candle_limit(int(limit))
        except Exception:  # pragma: no cover
            logger.debug("Could not prepare candle limit for %s", provider_id, exc_info=True)

    def select_provider(self, provider_id: str, connect: bool = True) -> dict[str, Any]:
        normalized = self._validate_provider(provider_id)
        with self._lock:
            previous = self._provider_id
            if previous != normalized:
                try:
                    self._providers[previous].disconnect()
                except Exception:  # pragma: no cover - switching must remain possible
                    logger.warning("Could not disconnect %s cleanly", previous, exc_info=True)
                self._provider_id = normalized
                self.settings_repo.set("market.provider", normalized)
                self._prepare_provider(normalized)
                logger.info("Market data provider switched from %s to %s", previous, normalized)
            if connect:
                self.provider.connect(force=True)
            self._publish()
            return self.status()

    # --------------------------------------------------------------- lifecycle
    async def run(self) -> None:
        """Start the single active-provider poll loop."""
        self.broadcaster.bind_loop(asyncio.get_running_loop())
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.poll_once)
            except Exception:  # pragma: no cover
                logger.exception("Market data poll failed unexpectedly")
            await asyncio.sleep(max(0.5, self.settings.poll_interval_seconds))

    def poll_once(self) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            try:
                self.provider.poll_once()
            except Exception:
                logger.exception("Active provider poll failed")
            # Binance pushes snapshots and candle frames from its WebSocket
            # listener. The manager only publishes a market snapshot here for
            # MT5, whose session is still poll-based.
            self._publish(include_market=self._provider_id != "binance")

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            for provider in self._providers.values():
                try:
                    provider.stop()
                except Exception:  # pragma: no cover - best effort
                    logger.debug("Provider stop failed", exc_info=True)

    def connect(self, force: bool = True) -> dict[str, Any]:
        with self._lock:
            self.provider.connect(force=force)
            self._publish()
            return self.status()

    def reconnect(self) -> dict[str, Any]:
        with self._lock:
            self.provider.connect(force=True)
            self._publish()
            return self.status()

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self.provider.disconnect()
            self._publish()
            return self.status()

    # -------------------------------------------------------------- delegation
    def status(self) -> dict[str, Any]:
        with self._lock:
            active = dict(self.provider.get_connection_status())
            active["provider"] = self._provider_id
            active["provider_label"] = PROVIDER_LABELS[self._provider_id]
            active["selected_provider"] = self._provider_id
            active["uptime_seconds"] = round(time.time() - self._started_at)
            providers: dict[str, Any] = {}
            for provider_id, provider in self._providers.items():
                try:
                    item = provider.get_connection_status()
                except Exception as exc:  # pragma: no cover
                    item = {
                        "state": "ERROR",
                        "state_label": "Error",
                        "connected": False,
                        "last_error": str(exc),
                    }
                providers[provider_id] = {
                    "provider": provider_id,
                    "provider_label": PROVIDER_LABELS[provider_id],
                    "connected": bool(item.get("connected")),
                    "state": item.get("state"),
                    "state_label": item.get("state_label"),
                    "state_reason": item.get("state_reason"),
                    "freshness": item.get("freshness"),
                    "selected_symbol": item.get("selected_symbol"),
                    "last_error": item.get("last_error"),
                    "last_successful_update": item.get("last_successful_update"),
                    "ws_connected": item.get("ws_connected"),
                }
            active["providers"] = providers
            return active

    def snapshot(self) -> dict[str, Any]:
        snapshot = dict(self.provider.snapshot())
        snapshot["provider"] = self._provider_id
        snapshot["provider_label"] = PROVIDER_LABELS[self._provider_id]
        return snapshot

    def candle_series(self, limit: int | None = None, force: bool = False) -> dict[str, Any]:
        series = dict(self.provider.candle_series(limit=limit, force=force))
        series["provider"] = self._provider_id
        series["provider_label"] = PROVIDER_LABELS[self._provider_id]
        return series

    def completed_candles(self, force: bool = False) -> list[Candle]:
        return self.provider.completed_candles(force=force)

    def freshness(self) -> tuple[str, str | None]:
        return self.provider.freshness()

    def select_symbol(self, name: str) -> dict[str, Any]:
        result = self.provider.select_symbol(name)
        self._publish()
        return result

    def set_timeframe(self, value: str) -> dict[str, Any]:
        with self._lock:
            result = self.provider.set_timeframe(value)
            self._publish()
            return result

    def set_candle_limit(self, limit: int) -> int:
        with self._lock:
            value = self.provider.set_candle_limit(limit)
            for provider in self._providers.values():
                try:
                    provider.set_candle_limit(value)
                except Exception:  # pragma: no cover
                    pass
            return value

    def refresh(self) -> dict[str, Any]:
        self.provider.poll_once()
        self.provider.candle_series(force=True)
        self._publish()
        return self.snapshot()

    # -------------------------------------------------------------- MT5 routes
    def mt5_connect(self) -> dict[str, Any]:
        return self.select_provider("mt5", connect=True)

    def mt5_reconnect(self) -> dict[str, Any]:
        with self._lock:
            self._provider_id = "mt5"
            self.settings_repo.set("market.provider", "mt5")
            result = self.mt5.reconnect()
            self._publish()
            return result

    def mt5_disconnect(self) -> dict[str, Any]:
        with self._lock:
            result = self.mt5.disconnect()
            if self._provider_id == "mt5":
                self._publish()
            return result

    def mt5_status(self) -> dict[str, Any]:
        return self.mt5.status()

    def terminal_payload(self) -> dict[str, Any]:
        return self.mt5.terminal_payload()

    def select_terminal(self, path: str | None) -> dict[str, Any]:
        return self.mt5.select_terminal(path)

    def set_connect_timeout(self, timeout_ms: int) -> int:
        return self.mt5.set_connect_timeout(timeout_ms)

    def history_check(self, count: int = 500) -> dict[str, Any]:
        return self.mt5.history_check(count=count)

    def test_connection(
        self,
        terminal_path: str | None = None,
        symbol: str | None = None,
        include_history: bool = True,
    ) -> dict[str, Any]:
        return self.mt5.test_connection(
            terminal_path=terminal_path,
            symbol=symbol,
            include_history=include_history,
        )

    def discover_symbols(self, refresh: bool = False) -> dict[str, Any]:
        return self.mt5.discover_symbols(refresh=refresh)

    def symbol_details(self, name: str) -> dict[str, Any]:
        return self.mt5.symbol_details(name)

    def diagnostics(self) -> dict[str, Any]:
        active = self.provider.diagnostics()
        active["provider"] = self._provider_id
        active["provider_label"] = PROVIDER_LABELS[self._provider_id]
        active["providers"] = {
            "binance": self.binance.diagnostics(),
            "mt5": self.mt5.diagnostics(),
        }
        active["selected_provider"] = self._provider_id
        active["source_isolation"] = "one selected provider per chart and forecast dataset"
        return active

    # ------------------------------------------------------------------ events
    def _publish(self, include_market: bool = True) -> None:
        try:
            snapshot = self.snapshot() if include_market else None
            status = self.status()
        except Exception:  # pragma: no cover
            return
        if snapshot is not None:
            self.broadcaster.publish({"type": "market", "payload": snapshot})
        # Volatile quote timestamps must not turn every status poll into a
        # WebSocket status frame. Publish only when connection state changes.
        signature = (
            status.get("provider"),
            status.get("state"),
            status.get("connected"),
            status.get("ws_connected"),
            status.get("freshness"),
            status.get("selected_symbol"),
            status.get("timeframe"),
            status.get("last_error"),
            status.get("reconnect_attempts"),
        )
        if signature != self._last_status_signature:
            self._last_status_signature = signature
            self.broadcaster.publish({"type": "status", "payload": status})


def build_mt5_provider(
    settings: Settings,
    gateway: MT5Gateway,
    candles_repo,
    ticks_repo,
    settings_repo,
    broadcaster: Broadcaster,
) -> MT5MarketDataProvider:  # type: ignore[no-untyped-def]
    return MT5MarketDataProvider(
        settings=settings,
        gateway=gateway,
        candles_repo=candles_repo,
        ticks_repo=ticks_repo,
        settings_repo=settings_repo,
        broadcaster=broadcaster,
    )
