"""Out-of-sample forecast evaluation and market-regime diagnostics.

This package is intentionally separate from the live forecast path. It consumes
matured observations only and never feeds evaluation data back into inference.
"""

from app.evaluation.metrics import (
    ForecastObservations,
    direction_probability_from_quantiles,
    summarize_observations,
)
from app.evaluation.regimes import add_market_regimes

__all__ = [
    "ForecastObservations",
    "add_market_regimes",
    "direction_probability_from_quantiles",
    "summarize_observations",
]
