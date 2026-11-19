"""Closed-candle liquidity context.

A "pool" here is a price cluster touched by at least two confirmed swings. This is
a deliberately narrow definition: the data providers in KBMTI expose candles only,
so no order-book, depth or institutional-flow claim is made. A sweep is a wick
through a pool that closes back on the original side; it is marked unconfirmed when
no later closed candle exists to confirm the rejection.
"""

from __future__ import annotations

from datetime import datetime
from statistics import mean

from app.analysis.contracts import (
    LIQUIDITY_VERSION,
    FeatureMeta,
    LiquidityFeature,
    LiquidityPool,
    LiquiditySweep,
)
from app.analysis.structure import find_swings
from app.analysis.util import utc_from_epoch
from app.market_data.candles import Candle

MIN_LIQUIDITY_SWINGS = 6
POOL_CLUSTER_ATR = 0.15
POOL_CLUSTER_MIN_PRICE = 0.0002
NEARBY_ATR_MULTIPLE = 3.0
SWEEP_LOOKBACK_BARS = 60
SWEEP_EXCEED_ATR = 0.05
MAX_POOLS = 8


def _meta(calculated_at: datetime, source: str, *, valid: bool, reason: str | None = None) -> FeatureMeta:
    return FeatureMeta(
        version=LIQUIDITY_VERSION,
        source=source,
        calculated_at=calculated_at,
        valid=valid,
        reason=reason,
    )


def unavailable_liquidity(calculated_at: datetime, source: str, reason: str) -> LiquidityFeature:
    return LiquidityFeature(
        meta=_meta(calculated_at, source, valid=False, reason=reason),
        available=False,
    )


def evaluate_liquidity(
    candles: list[Candle],
    *,
    atr14: float | None,
    calculated_at: datetime,
    source: str,
) -> LiquidityFeature:
    swings = find_swings(candles)
    if len(swings) < MIN_LIQUIDITY_SWINGS:
        return unavailable_liquidity(
            calculated_at,
            source,
            f"At least {MIN_LIQUIDITY_SWINGS} confirmed swings are required for liquidity pools.",
        )
    if atr14 is None or atr14 <= 0:
        return unavailable_liquidity(calculated_at, source, "ATR is required to size liquidity tolerance.")

    last_close = float(candles[-1].close)
    tolerance = max(atr14 * POOL_CLUSTER_ATR, last_close * POOL_CLUSTER_MIN_PRICE)
    pools: list[LiquidityPool] = []

    for kind in ("high", "low"):
        items = sorted((swing for swing in swings if swing.kind == kind), key=lambda swing: swing.price)
        clusters: list[list] = []
        for item in items:
            if clusters and abs(item.price - mean(swing.price for swing in clusters[-1])) <= tolerance:
                clusters[-1].append(item)
            else:
                clusters.append([item])
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            price = mean(swing.price for swing in cluster)
            if abs(price - last_close) > atr14 * NEARBY_ATR_MULTIPLE:
                continue
            pools.append(
                LiquidityPool(
                    id=f"pool:{kind}:{min(swing.time for swing in cluster)}",
                    kind=kind,
                    price=round(price, 8),
                    touches=len(cluster),
                    side="above" if price > last_close else "below",
                    distance_percent=round((price - last_close) / last_close * 100.0, 4),
                    first_time=utc_from_epoch(min(swing.time for swing in cluster)),
                    last_time=utc_from_epoch(max(swing.time for swing in cluster)),
                    evidence=[f"swing:{kind}:{swing.time}" for swing in cluster],
                )
            )

    pools.sort(key=lambda pool: abs(pool.distance_percent))
    pools = pools[:MAX_POOLS]

    sweeps: list[LiquiditySweep] = []
    start = max(0, len(candles) - SWEEP_LOOKBACK_BARS)
    for pool in pools:
        latest: LiquiditySweep | None = None
        for index in range(start, len(candles)):
            candle = candles[index]
            if candle.time <= int(pool.last_time.timestamp()):
                continue
            if pool.kind == "high":
                swept = candle.high >= pool.price + atr14 * SWEEP_EXCEED_ATR and candle.close < pool.price
                confirmed = index + 1 < len(candles) and candles[index + 1].close < pool.price
            else:
                swept = candle.low <= pool.price - atr14 * SWEEP_EXCEED_ATR and candle.close > pool.price
                confirmed = index + 1 < len(candles) and candles[index + 1].close > pool.price
            if not swept:
                continue
            latest = LiquiditySweep(
                id=f"sweep:{pool.kind}:{candle.time}",
                kind=pool.kind,
                level=pool.price,
                candle_time=utc_from_epoch(candle.time),
                confirmation="CONFIRMED" if confirmed else "UNCONFIRMED",
                evidence=[f"candle:{candle.time}", pool.id],
            )
        if latest is not None:
            sweeps.append(latest)

    return LiquidityFeature(
        meta=_meta(calculated_at, source, valid=True),
        available=True,
        pools=pools,
        sweeps=sorted(sweeps, key=lambda sweep: sweep.candle_time)[-6:],
    )
