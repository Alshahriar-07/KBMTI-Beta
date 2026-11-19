"""Signal composition and snapshot persistence."""

from __future__ import annotations

import threading
import time
from typing import Any

from app.core.config import Settings
from app.indicators.engine import compute_indicators
from app.market_data.candles import epoch_to_iso
from app.market_data.service import MarketService
from app.persistence.repositories import SignalRepository
from app.signals.engine import DISCLAIMER, ENGINE_ID, NO_CLEAR_SETUP, WAIT, evaluate_signal


class SignalService:
    def __init__(self, market: MarketService, repository: SignalRepository, settings: Settings) -> None:
        self.market = market
        self.repository = repository
        self.settings = settings
        self._lock = threading.RLock()
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._cached_bar: int | None = None
        self._last_persisted_label: str | None = None
        self._last_persisted_at = 0.0

    def current(self, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            candles = self.market.completed_candles()
            current_bar = int(candles[-1].time) if candles else None
            # A wall-clock cache keyed only by time can return the previous
            # signal after a confirmed close. Invalidate on the actual source
            # bar so the displayed bias always reflects the newest candle.
            if (
                not refresh
                and self._cached is not None
                and self._cached_bar == current_bar
                and now - self._cached_at < self.settings.signal_cache_seconds
            ):
                return self._cached

            result = self._evaluate(candles)
            payload = result.to_dict()
            self._cached = payload
            self._cached_at = now
            self._cached_bar = current_bar
            self._maybe_persist(payload, now)
            return payload

    def _evaluate(self, candles=None):  # type: ignore[no-untyped-def]
        symbol = self.market.status().get("selected_symbol") or ""
        if candles is None:
            candles = self.market.completed_candles()
        snapshot = self.market.snapshot()
        timeframe = snapshot["timeframe"]
        freshness, reason = self.market.freshness()

        if not candles:
            return evaluate_signal(
                symbol=symbol,
                timeframe=timeframe,
                bundle=compute_indicators([]),
                close=None,
                completed_candle_count=0,
                data_as_of=None,
                freshness="unavailable",
                stale_reason=reason or "No completed candles are available.",
            )

        bundle = compute_indicators(candles)
        close = candles[-1].close
        return evaluate_signal(
            symbol=symbol,
            timeframe=timeframe,
            bundle=bundle,
            close=close,
            completed_candle_count=len(candles),
            data_as_of=epoch_to_iso(candles[-1].time),
            freshness=freshness,
            stale_reason=reason,
            spread_points=snapshot.get("spread_points"),
            atr_value=bundle.latest().get("atr14"),
        )

    def _maybe_persist(self, payload: dict[str, Any], now: float) -> None:
        if not payload.get("symbol"):
            return
        label = payload.get("label")
        should_persist = label != self._last_persisted_label or now - self._last_persisted_at > 300
        if not should_persist or payload.get("source_candle_count", 0) < 1:
            return
        try:
            self.repository.insert(
                {
                    "symbol": payload["symbol"],
                    "timeframe": payload["timeframe"],
                    "timestamp_utc": int(time.time()),
                    "label": label or WAIT,
                    "direction": payload.get("direction") or "neutral",
                    "score": float(payload.get("score") or 0.0),
                    "engine": ENGINE_ID,
                    "freshness": payload.get("freshness") or "unknown",
                    "evidence": payload.get("supporting", []) + payload.get("conflicting", []),
                    "invalidation": payload.get("invalidation", []),
                }
            )
            self._last_persisted_label = label
            self._last_persisted_at = now
        except Exception:  # pragma: no cover - persistence must not break signals
            pass

    def history(self, limit: int = 50, symbol: str | None = None) -> list[dict[str, Any]]:
        rows = self.repository.recent(limit=max(1, min(limit, 200)), symbol=symbol)
        for row in rows:
            row["created_at"] = epoch_to_iso(row.pop("timestamp_utc", None))
        return rows


EMPTY_SIGNAL_LABEL = NO_CLEAR_SETUP
SIGNAL_DISCLAIMER = DISCLAIMER
