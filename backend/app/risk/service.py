"""Risk service facade around the pure risk engine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.analysis.contracts import MarketSnapshot
from app.risk.contracts import (
    DEFAULT_RISK_POLICY,
    RiskAssessment,
    RiskPolicy,
    StrategyValidationStatus,
)
from app.risk.engine import assess_risk
from app.strategies.contracts import StrategyDirection, TrendPullbackEvaluation


class RiskService:
    def __init__(
        self,
        *,
        policy: RiskPolicy = DEFAULT_RISK_POLICY,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def policy(self) -> RiskPolicy:
        return self._policy

    @property
    def enabled(self) -> bool:
        return True

    def assess(
        self,
        *,
        direction: StrategyDirection,
        entry,
        stop,
        targets,
        target_conflict: bool,
        atr,
        snapshot: MarketSnapshot,
        evaluation: TrendPullbackEvaluation,
        strategy_status: StrategyValidationStatus,
    ) -> RiskAssessment:
        return assess_risk(
            direction=direction,
            entry=entry,
            stop=stop,
            targets=targets,
            target_conflict=target_conflict,
            atr=atr,
            snapshot=snapshot,
            evaluation=evaluation,
            strategy_status=strategy_status,
            policy=self._policy,
        )

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "policy_version": self._policy.policy_version,
            "policy": self._policy.model_dump(mode="json"),
            "position_size_status": "NOT_CALCULATED",
            "execution": "disabled",
            "generated_at": self._clock().isoformat(),
        }
