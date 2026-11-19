"""Candle normalization, UTC conversion and integrity validation.

MetaTrader 5 returns bar timestamps in the broker server's clock, not necessarily
UTC. The service estimates the server offset from the live tick and shifts bars
into UTC before they enter the chart/cache. The original server timestamp is kept
alongside converted bars so the distinction is never hidden.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

TIME_BASIS_UTC = "utc"
TIME_BASIS_SERVER = "broker_server"


@dataclass(frozen=True, slots=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    spread: int = 0
    real_volume: int = 0
    server_time: int | None = None
    source: str = "mt5"
    symbol: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "server_time": self.server_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "tick_volume": self.tick_volume,
            "spread": self.spread,
            "real_volume": self.real_volume,
            "source": self.source,
            "symbol": self.symbol,
        }


def candle_to_epoch(value: Any) -> int:
    """Convert MT5 time values (int, float, datetime, numpy datetime64) to epoch seconds."""

    if value is None:
        return 0
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp())
    if hasattr(value, "astype"):  # numpy scalar types
        try:
            return int(value.astype("datetime64[s]").astype("int64")) if "datetime64" in str(value.dtype) else int(value)
        except (TypeError, ValueError):
            return int(value)
    return int(float(value))


def _float(value: Any, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def raw_to_candle(row: Mapping[str, Any] | Sequence[Any]) -> Candle:
    if isinstance(row, Mapping):
        get = row.get
    else:  # pragma: no cover - defensive path for tuple-like rows
        keys = ("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume")
        mapping = dict(zip(keys, row, strict=False))
        get = mapping.get

    server_time = candle_to_epoch(get("server_time")) if get("server_time") is not None else None
    return Candle(
        time=candle_to_epoch(get("time")),
        open=_float(get("open")),
        high=_float(get("high")),
        low=_float(get("low")),
        close=_float(get("close")),
        tick_volume=int(_float(get("tick_volume"), 0.0) or 0),
        spread=int(_float(get("spread"), 0.0) or 0),
        real_volume=int(_float(get("real_volume"), 0.0) or 0),
        server_time=server_time,
        source=str(get("source") or "mt5"),
        symbol=str(get("symbol")) if get("symbol") is not None else None,
    )


def clean_candles(rows: Iterable[Mapping[str, Any] | Sequence[Any]]) -> tuple[list[Candle], list[str]]:
    """Sort ascending, de-duplicate by timestamp and drop structurally invalid bars.

    Returns (candles, warnings). Invalid bars are reported, never repaired or invented.
    """

    warnings: list[str] = []
    by_time: dict[int, Candle] = {}
    raw_count = 0
    invalid = 0
    duplicates = 0

    for row in rows:
        raw_count += 1
        candle = raw_to_candle(row)
        prices = (candle.open, candle.high, candle.low, candle.close)
        if candle.time <= 0 or any(math.isnan(p) or math.isinf(p) or p <= 0 for p in prices):
            invalid += 1
            continue
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            invalid += 1
            continue
        if candle.high < candle.low:
            invalid += 1
            continue
        if candle.time in by_time:
            duplicates += 1
        by_time[candle.time] = candle

    candles = [by_time[key] for key in sorted(by_time)]
    if invalid:
        warnings.append(f"{invalid} candle(s) failed OHLC integrity checks and were excluded.")
    if duplicates:
        warnings.append(f"{duplicates} duplicate candle timestamp(s) were collapsed to the latest values.")
    if raw_count and not candles:
        warnings.append("No valid candles were available in the broker response.")
    return candles, warnings


def shift_rows_to_utc(rows: Iterable[Mapping[str, Any]], offset_seconds: int) -> list[dict[str, Any]]:
    """Return copies with ``time`` shifted from broker-server time to UTC.

    ``offset_seconds`` is server clock minus UTC. The original value is preserved as
    ``server_time`` so the conversion can be audited.
    """

    shifted: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        server_time = candle_to_epoch(item.get("time"))
        item["server_time"] = server_time
        item["time"] = server_time - int(offset_seconds)
        shifted.append(item)
    return shifted


def shift_candles(candles: Iterable[Candle], delta_seconds: int) -> list[Candle]:
    """Shift already-normalized candles by ``delta_seconds`` (UTC = server - offset)."""

    if not delta_seconds:
        return list(candles)
    return [
        replace(candle, time=candle.time + int(delta_seconds), server_time=candle.server_time or candle.time)
        for candle in candles
    ]


def mark_forming(candles: Sequence[Candle], timeframe_seconds: int, reference_epoch: int | None) -> tuple[list[Candle], Candle | None]:
    """Split the newest (still forming) bar from completed candles."""

    if not candles:
        return [], None
    last = candles[-1]
    reference = reference_epoch if reference_epoch and reference_epoch > 0 else None
    is_forming = reference is None or last.time + timeframe_seconds > reference
    if is_forming:
        return list(candles[:-1]), last
    return list(candles), None


def epoch_to_iso(epoch: int | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(int(epoch), tz=UTC).isoformat(timespec="seconds")
