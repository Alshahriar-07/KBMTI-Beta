"""Read-only candle sources for market intelligence.

The Phase 1 scope is BTCUSDT M15. The canonical source is the same Binance public
history client that feeds PATRON, so the analysis and the forecast describe the
same instrument and interval. If that fetch fails, a repository fallback may serve
already-stored Binance candles; the fallback is recorded in the snapshot source and
a warning, never hidden.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.core.errors import MarketDataUnavailableError
from app.market_data.binance_history import BinanceHistoryClient
from app.market_data.candles import Candle
from app.persistence.repositories import CandleRepository

logger = logging.getLogger(__name__)

BINANCE_INTERVAL = {"M15": "15m"}


@dataclass(frozen=True, slots=True)
class CandleBatch:
    candles: list[Candle]
    provider: str
    source: str
    fetched_at: datetime
    notes: list[str] = field(default_factory=list)


class CandleSource(Protocol):
    def fetch(self, symbol: str, timeframe: str, limit: int) -> CandleBatch: ...


class BinanceCandleSource:
    """Fetch closed BTCUSDT M15 klines from the public Binance history client."""

    provider = "binance"

    def __init__(self, history: BinanceHistoryClient) -> None:
        self._history = history

    def fetch(self, symbol: str, timeframe: str, limit: int) -> CandleBatch:
        interval = BINANCE_INTERVAL.get(timeframe.upper())
        if interval is None:
            raise MarketDataUnavailableError(
                f"No Binance interval mapping exists for timeframe '{timeframe}'.",
                {"supported": list(BINANCE_INTERVAL)},
            )
        try:
            rows = self._history.recent(symbol.upper(), interval, limit=limit)
        except Exception as exc:  # noqa: BLE001 - normalized for the service layer
            raise MarketDataUnavailableError(
                "Binance history required for market intelligence is unavailable.",
                {"error": str(exc), "symbol": symbol, "timeframe": timeframe},
            ) from exc
        candles = [
            Candle(
                time=int(row.open_time),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                tick_volume=int(row.trades),
                real_volume=0,
                source=self.provider,
                symbol=symbol.upper(),
            )
            for row in rows
        ]
        if not candles:
            raise MarketDataUnavailableError(
                "Binance returned no closed candles for market intelligence.",
                {"symbol": symbol, "timeframe": timeframe},
            )
        return CandleBatch(
            candles=candles,
            provider=self.provider,
            source="binance_rest",
            fetched_at=datetime.now(UTC),
        )


class RepositoryCandleSource:
    """Serve stored Binance candles when the REST fetch is unavailable."""

    provider = "binance"

    def __init__(self, repository: CandleRepository, *, source: str = "binance") -> None:
        self._repository = repository
        self._source = source

    def fetch(self, symbol: str, timeframe: str, limit: int) -> CandleBatch:
        rows = self._repository.recent(symbol.upper(), timeframe.upper(), limit=limit, source=self._source)
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
                source=self._source,
                symbol=symbol.upper(),
            )
            for row in rows
        ]
        if not candles:
            raise MarketDataUnavailableError(
                "No stored Binance candles are available for market intelligence.",
                {"symbol": symbol, "timeframe": timeframe, "source": self._source},
            )
        return CandleBatch(
            candles=candles,
            provider=self.provider,
            source="database_cache",
            fetched_at=datetime.now(UTC),
        )


class FallbackCandleSource:
    """Try the live source first; fall back to stored candles with an explicit note."""

    def __init__(self, primary: CandleSource, fallback: CandleSource) -> None:
        self._primary = primary
        self._fallback = fallback

    def fetch(self, symbol: str, timeframe: str, limit: int) -> CandleBatch:
        try:
            return self._primary.fetch(symbol, timeframe, limit)
        except Exception as exc:  # noqa: BLE001 - the fallback is the failure policy
            logger.warning("Primary market-intelligence source failed: %s", exc)
            batch = self._fallback.fetch(symbol, timeframe, limit)
            return CandleBatch(
                candles=batch.candles,
                provider=batch.provider,
                source=batch.source,
                fetched_at=batch.fetched_at,
                notes=[
                    *batch.notes,
                    f"Live Binance fetch failed ({exc}); serving stored Binance candles instead.",
                ],
            )
