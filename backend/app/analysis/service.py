"""Service facade for deterministic BTCUSDT M15 market intelligence.

Responsibilities: enforce the approved scope, fetch closed candles, build one
snapshot per closed bar, persist it, and serve a short-lived cache so two consumers
reading the same bar do not recompute (or refetch) independently.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.analysis.context import MarketContextBuilder
from app.analysis.contracts import (
    FEATURE_VERSION,
    MAX_ANALYSIS_BARS,
    SCOPE_SYMBOL,
    SCOPE_TIMEFRAME,
    SCOPE_TIMEFRAME_SECONDS,
    MarketContextResponse,
    MarketSnapshot,
    RegimeState,
    ValidationState,
    ValidationStatus,
    scope_for,
)
from app.analysis.sources import CandleSource
from app.core.config import Settings
from app.core.errors import UnsupportedScopeError
from app.persistence.repositories import MarketSnapshotRepository

logger = logging.getLogger(__name__)

CACHE_SECONDS = 5.0


@dataclass(slots=True)
class _CacheEntry:
    snapshot: MarketSnapshot
    built_monotonic: float


class AnalysisService:
    def __init__(
        self,
        *,
        source: CandleSource,
        repository: MarketSnapshotRepository | None,
        settings: Settings,
        clock: Callable[[], datetime] | None = None,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._source = source
        self._repository = repository
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache_seconds = max(0.0, float(cache_seconds))
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._builder = MarketContextBuilder(
            stale_after_seconds=settings.stale_after_seconds,
            clock=self._clock,
        )
        self._last_error: str | None = None
        self._builds = 0

    @property
    def enabled(self) -> bool:
        return True

    def snapshot(
        self,
        *,
        symbol: str = SCOPE_SYMBOL,
        timeframe: str = SCOPE_TIMEFRAME,
        refresh: bool = False,
    ) -> MarketSnapshot:
        scope = scope_for(symbol, timeframe)
        if not scope.supported:
            raise UnsupportedScopeError(scope.reason or "Unsupported market scope.", scope.model_dump())

        key = (scope.symbol, scope.timeframe)
        now_monotonic = time.monotonic()
        if not refresh and self._cache_seconds > 0:
            cached = self._cache.get(key)
            if cached and now_monotonic - cached.built_monotonic < self._cache_seconds:
                return self._apply_current_staleness(cached.snapshot)

        fetched_at = self._clock()
        try:
            batch = self._source.fetch(scope.symbol, scope.timeframe, MAX_ANALYSIS_BARS)
            snapshot = self._builder.build(
                symbol=scope.symbol,
                timeframe=scope.timeframe,
                candles=batch.candles,
                provider=batch.provider,
                source=batch.source,
                fetched_at=fetched_at,
                request_id=uuid.uuid4().hex,
                fetch_notes=batch.notes,
            )
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            raise

        snapshot = self._persist(snapshot)
        self._cache[key] = _CacheEntry(snapshot=snapshot, built_monotonic=now_monotonic)
        self._builds += 1
        return snapshot

    def context(
        self,
        *,
        symbol: str = SCOPE_SYMBOL,
        timeframe: str = SCOPE_TIMEFRAME,
        refresh: bool = False,
    ) -> MarketContextResponse:
        return context_from_snapshot(self.snapshot(symbol=symbol, timeframe=timeframe, refresh=refresh))

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "scope": {"symbol": SCOPE_SYMBOL, "timeframe": SCOPE_TIMEFRAME},
            "feature_version": FEATURE_VERSION,
            "cache_seconds": self._cache_seconds,
            "cached_scopes": len(self._cache),
            "builds": self._builds,
            "persisted_snapshots": self._repository.count() if self._repository else None,
            "last_error": self._last_error,
            "generated_at": self._clock().isoformat(),
        }

    def clear_cache(self) -> None:
        self._cache.clear()

    def _persist(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        if self._repository is None:
            return snapshot
        try:
            self._repository.insert(
                snapshot_id=snapshot.snapshot_id,
                symbol=snapshot.symbol,
                timeframe=snapshot.timeframe,
                provider=snapshot.provider,
                generated_at=snapshot.generated_at.isoformat(),
                data_as_of=snapshot.data_as_of.isoformat(),
                is_stale=snapshot.is_stale,
                feature_version=snapshot.feature_version,
                validation_status=snapshot.validation.status.value,
                payload=snapshot.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - persistence is audit, not a reason to fail analysis
            logger.exception("Market snapshot persistence failed")
            return snapshot.model_copy(
                update={
                    "warnings": [
                        *snapshot.warnings,
                        "Snapshot persistence failed; the analysis was still returned.",
                    ]
                }
            )
        return snapshot

    def _apply_current_staleness(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        now = self._clock()
        limit = SCOPE_TIMEFRAME_SECONDS + self._settings.stale_after_seconds
        stale_now = (now - snapshot.data_as_of).total_seconds() > limit
        request_id = uuid.uuid4().hex
        if stale_now == snapshot.is_stale:
            return snapshot.model_copy(update={"request_id": request_id})

        warnings = list(snapshot.warnings)
        validation = snapshot.validation
        regime = snapshot.regime
        if stale_now:
            message = f"Market data became stale while cached; the newest closed candle is older than {limit:.0f}s."
            if message not in warnings:
                warnings.append(message)
            if validation.status is ValidationStatus.OK:
                validation = ValidationState(
                    status=ValidationStatus.STALE,
                    checks=validation.checks,
                    errors=validation.errors,
                )
            if regime.state is not RegimeState.UNCERTAIN:
                regime = regime.model_copy(
                    update={
                        "state": RegimeState.UNCERTAIN,
                        "reasons": [*regime.reasons, "Market data became stale after the snapshot was built."],
                        "meta": regime.meta.model_copy(
                            update={"valid": False, "reason": "market data is stale"}
                        ),
                    }
                )
        else:
            message = (
                f"Market data is now within the freshness window; the newest closed candle closed "
                f"{(now - snapshot.data_as_of).total_seconds():.0f}s ago."
            )
            if message not in warnings:
                warnings.append(message)
            if validation.status is ValidationStatus.STALE:
                validation = ValidationState(
                    status=ValidationStatus.OK,
                    checks=validation.checks,
                    errors=validation.errors,
                )
        return snapshot.model_copy(
            update={
                "request_id": request_id,
                "is_stale": stale_now,
                "validation": validation,
                "regime": regime,
                "warnings": warnings,
            }
        )


def context_from_snapshot(snapshot: MarketSnapshot) -> MarketContextResponse:
    pools = sorted(snapshot.liquidity.pools, key=lambda pool: abs(pool.distance_percent))[:4]
    return MarketContextResponse(
        request_id=snapshot.request_id,
        snapshot_id=snapshot.snapshot_id,
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        provider=snapshot.provider,
        generated_at=snapshot.generated_at,
        data_as_of=snapshot.data_as_of,
        is_stale=snapshot.is_stale,
        feature_version=snapshot.feature_version,
        scope=snapshot.scope,
        provenance=snapshot.provenance,
        validation=snapshot.validation,
        last_price=snapshot.last_price,
        trend_state=snapshot.trend.state,
        trend_strength=snapshot.trend.strength,
        structure_state=snapshot.structure.state,
        momentum_state=snapshot.momentum.state,
        momentum_phase=snapshot.momentum.phase,
        volatility_state=snapshot.volatility.state,
        volatility_phase=snapshot.volatility.phase,
        regime_state=snapshot.regime.state,
        regime_reasons=snapshot.regime.reasons,
        key_levels=snapshot.structure.levels[:6],
        liquidity_pools=pools,
        warnings=snapshot.warnings,
    )
