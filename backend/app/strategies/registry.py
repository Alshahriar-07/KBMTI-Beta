"""Catalog of deterministic strategies available to the API.

Only the approved, implemented Trend Pullback strategy is registered. A strategy
that is planned but not implemented must be listed with ``implemented=False`` and
must never be evaluable; absent is also acceptable. Phase 2 adds exactly one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.analysis.contracts import SCOPE_SYMBOL, SCOPE_TIMEFRAME
from app.strategies.config import (
    STRATEGY_DESCRIPTION,
    STRATEGY_ID,
    STRATEGY_VERSION,
    SUPPORTED_SYMBOL,
    SUPPORTED_TIMEFRAME,
)
from app.strategies.contracts import StrategyCatalogItem, StrategyCatalogResponse, TrendPullbackEvaluation
from app.strategies.trend_pullback import evaluate_trend_pullback

Evaluator = Callable[..., TrendPullbackEvaluation]


@dataclass(frozen=True, slots=True)
class StrategySpec:
    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    status: str
    description: str
    implemented: bool
    evaluate: Evaluator

    def catalog_item(self) -> StrategyCatalogItem:
        return StrategyCatalogItem(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            symbol=self.symbol,
            timeframe=self.timeframe,
            status=self.status,
            description=self.description,
            implemented=self.implemented,
        )


STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec(
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        symbol=SUPPORTED_SYMBOL,
        timeframe=SUPPORTED_TIMEFRAME,
        status="active",
        description=STRATEGY_DESCRIPTION,
        implemented=True,
        evaluate=evaluate_trend_pullback,
    ),
)


def get_strategy(strategy_id: str) -> StrategySpec | None:
    for spec in STRATEGIES:
        if spec.strategy_id == strategy_id:
            return spec
    return None


def strategy_catalog(now: datetime | None = None) -> StrategyCatalogResponse:
    return StrategyCatalogResponse(
        strategies=[spec.catalog_item() for spec in STRATEGIES],
        evaluated_at=now or datetime.now(UTC),
    )


def scope_matches(spec: StrategySpec, symbol: str = SCOPE_SYMBOL, timeframe: str = SCOPE_TIMEFRAME) -> bool:
    return spec.symbol == symbol.upper() and spec.timeframe == timeframe.upper()
