"""Frozen BTCUSDT M15 fixtures for deterministic market-intelligence tests.

The JSON files contain synthetic, deterministic candles (documented in
``tests/fixtures/analysis/README.md``). They are test inputs only: no claim is made
that they represent live market performance.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.analysis.context import MarketContextBuilder
from app.analysis.sources import CandleBatch
from app.market_data.candles import Candle

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "analysis"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def fixture_candles(name: str) -> list[Candle]:
    document = load_fixture(name)
    return [
        Candle(
            time=int(row["time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(row.get("tick_volume") or 0),
            source="binance",
            symbol="BTCUSDT",
        )
        for row in document["candles"]
    ]


def fixture_now(name: str, *, exclude_last: int = 0, offset_seconds: int = 30) -> datetime:
    candles = fixture_candles(name)
    anchor = candles[-1 - exclude_last] if exclude_last else candles[-1]
    return datetime.fromtimestamp(int(anchor.time) + 900 + offset_seconds, UTC)


def build_snapshot(
    name: str,
    *,
    now: datetime | None = None,
    exclude_last: int = 0,
    stale_after_seconds: float = 120.0,
):
    resolved_now = now or fixture_now(name, exclude_last=exclude_last)
    builder = MarketContextBuilder(stale_after_seconds=stale_after_seconds, clock=lambda: resolved_now)
    return builder.build(
        symbol="BTCUSDT",
        timeframe="M15",
        candles=fixture_candles(name),
        provider="binance",
        source="fixture",
        fetched_at=resolved_now,
    )


class StaticCandleSource:
    def __init__(self, candles: list[Candle], *, provider: str = "binance", source: str = "fixture") -> None:
        self.candles = candles
        self.provider = provider
        self.source = source
        self.calls = 0

    def fetch(self, symbol: str, timeframe: str, limit: int) -> CandleBatch:
        self.calls += 1
        return CandleBatch(
            candles=list(self.candles[-limit:]),
            provider=self.provider,
            source=self.source,
            fetched_at=datetime.now(UTC),
        )
