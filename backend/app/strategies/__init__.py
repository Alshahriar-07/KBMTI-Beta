"""Deterministic strategy engine (Phase 2).

The package is pure: strategies read an existing Phase 1 ``MarketSnapshot`` and
return a typed, explainable evaluation. Nothing here fetches data, reads a clock
implicitly, or produces an order, entry, stop, target, leverage or position size.
"""

from app.strategies.config import (
    CONFIG_VERSION,
    DEFAULT_CONFIG,
    STRATEGY_DESCRIPTION,
    STRATEGY_ID,
    STRATEGY_VERSION,
    SUPPORTED_SYMBOL,
    SUPPORTED_TIMEFRAME,
    TrendPullbackConfig,
)
from app.strategies.contracts import (
    ConfirmationStatus,
    EligibilityAssessment,
    QualityLabel,
    StrategyCatalogItem,
    StrategyCatalogResponse,
    StrategyDecision,
    StrategyDirection,
    StrategyEvidence,
    StrategyQuality,
    StrategyReason,
    TrendPullbackEvaluation,
)
from app.strategies.registry import STRATEGIES, StrategySpec, get_strategy, strategy_catalog
from app.strategies.trend_pullback import evaluate_trend_pullback

__all__ = [
    "CONFIG_VERSION",
    "DEFAULT_CONFIG",
    "STRATEGIES",
    "STRATEGY_DESCRIPTION",
    "STRATEGY_ID",
    "STRATEGY_VERSION",
    "SUPPORTED_SYMBOL",
    "SUPPORTED_TIMEFRAME",
    "ConfirmationStatus",
    "EligibilityAssessment",
    "QualityLabel",
    "StrategyCatalogItem",
    "StrategyCatalogResponse",
    "StrategyDecision",
    "StrategyDirection",
    "StrategyEvidence",
    "StrategyQuality",
    "StrategyReason",
    "StrategySpec",
    "TrendPullbackConfig",
    "TrendPullbackEvaluation",
    "evaluate_trend_pullback",
    "get_strategy",
    "strategy_catalog",
]
