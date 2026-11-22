"""Strategy validation provenance for downstream plans.

Phase 2's independent 60-case gate is still PENDING. Until it is genuinely completed,
every plan originating from ``trend_pullback`` must carry that status. This module is
the single read-only source of that fact; no API can upgrade it.
"""

from __future__ import annotations

from app.risk.contracts import StrategyValidationStatus
from app.strategies.config import STRATEGY_ID

STRATEGY_VALIDATION: dict[str, StrategyValidationStatus] = {
    STRATEGY_ID: StrategyValidationStatus.PENDING,
}


def strategy_validation_status(strategy_id: str) -> StrategyValidationStatus:
    return STRATEGY_VALIDATION.get(strategy_id, StrategyValidationStatus.PENDING)
