"""Common read-only contract for every KBMTI market data source.

The manager in :mod:`app.market_data.manager` owns exactly one selected provider.
Providers never fall back to another source: a connection failure is surfaced to
the caller and the manager keeps the selected provider selected.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from app.market_data.candles import Candle

MarketEventListener = Callable[[dict[str, Any]], None]


class MarketDataProvider(ABC):
    """Provider contract shared by Binance and MetaTrader 5."""

    provider_id: str
    provider_name: str

    @abstractmethod
    def connect(self, force: bool = False) -> dict[str, Any]:
        """Connect or verify the provider session and return its status."""

    @abstractmethod
    def disconnect(self) -> dict[str, Any]:
        """Disconnect without selecting another provider."""

    @abstractmethod
    def get_symbols(self, refresh: bool = False) -> dict[str, Any]:
        """Return normalized BTC symbol metadata."""

    @abstractmethod
    def get_historical_candles(self, timeframe: str, limit: int) -> list[Candle]:
        """Return normalized historical candles for one timeframe."""

    @abstractmethod
    def subscribe(self, listener: MarketEventListener) -> Callable[[], None]:
        """Subscribe to live normalized quote/candle events."""

    @abstractmethod
    def get_connection_status(self) -> dict[str, Any]:
        """Return provider connection, freshness and error details."""

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Return the normalized live market snapshot."""

    @abstractmethod
    def candle_series(self, limit: int | None = None, force: bool = False) -> dict[str, Any]:
        """Return the normalized candle-series response."""

    @abstractmethod
    def completed_candles(self, force: bool = False) -> list[Candle]:
        """Return completed candles only."""

    @abstractmethod
    def freshness(self) -> tuple[str, str | None]:
        """Return (fresh|stale|unavailable, reason)."""

    @abstractmethod
    def select_symbol(self, symbol: str) -> dict[str, Any]:
        """Select and persist a symbol for this provider."""

    @abstractmethod
    def set_timeframe(self, timeframe: str) -> dict[str, Any]:
        """Select and persist the chart timeframe."""

    @abstractmethod
    def set_candle_limit(self, limit: int) -> int:
        """Set and persist the requested history depth."""

    @abstractmethod
    def poll_once(self) -> None:
        """Perform one bounded health/refresh cycle."""

    @property
    @abstractmethod
    def candle_limit(self) -> int:
        """Configured history depth."""

    def diagnostics(self) -> dict[str, Any]:
        """Provider-specific diagnostics; safe for providers to override."""
        status = self.get_connection_status()
        return {
            "provider": self.provider_id,
            "provider_name": self.provider_name,
            "status": status,
            "checked_at": status.get("last_successful_update"),
        }

    def stop(self) -> None:
        """Stop background work. Manager calls this on application shutdown."""
        self.disconnect()
