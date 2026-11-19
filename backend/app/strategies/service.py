"""Service facade for deterministic strategy evaluation.

The service never fetches market data itself. It asks Phase 1 ``AnalysisService``
for the latest closed-bar snapshot, which reuses the approved scope, validation,
freshness and snapshot cache. A strategy evaluation is therefore one closed bar at
most; it can never see forming or future candles.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.analysis.contracts import SCOPE_SYMBOL, SCOPE_TIMEFRAME, scope_for
from app.analysis.service import AnalysisService
from app.core.errors import NotFoundError, UnsupportedScopeError
from app.persistence.repositories import StrategyEvaluationRepository
from app.strategies.config import STRATEGY_ID
from app.strategies.contracts import StrategyCatalogResponse, TrendPullbackEvaluation
from app.strategies.registry import get_strategy, scope_matches, strategy_catalog

logger = logging.getLogger(__name__)


class StrategyService:
    def __init__(
        self,
        *,
        analysis: AnalysisService,
        repository: StrategyEvaluationRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._analysis = analysis
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._evaluations = 0
        self._last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return True

    def catalog(self) -> StrategyCatalogResponse:
        return strategy_catalog(self._clock())

    def evaluate(
        self,
        *,
        strategy_id: str = STRATEGY_ID,
        symbol: str = SCOPE_SYMBOL,
        timeframe: str = SCOPE_TIMEFRAME,
        refresh: bool = False,
    ) -> TrendPullbackEvaluation:
        spec = get_strategy(strategy_id)
        if spec is None or not spec.implemented:
            raise NotFoundError(
                f"Strategy '{strategy_id}' is not implemented.",
                {"strategy_id": strategy_id, "available": [item.strategy_id for item in self.catalog().strategies]},
            )

        scope = scope_for(symbol, timeframe)
        if not scope.supported:
            raise UnsupportedScopeError(scope.reason or "Unsupported market scope.", scope.model_dump())
        if not scope_matches(spec, scope.symbol, scope.timeframe):
            raise UnsupportedScopeError(
                f"Strategy '{spec.strategy_id}' supports {spec.symbol} {spec.timeframe} only.",
                {
                    **scope.model_dump(),
                    "supported": False,
                    "strategy_id": spec.strategy_id,
                    "strategy_symbol": spec.symbol,
                    "strategy_timeframe": spec.timeframe,
                },
            )

        try:
            snapshot = self._analysis.snapshot(symbol=scope.symbol, timeframe=scope.timeframe, refresh=refresh)
            evaluation = spec.evaluate(snapshot, evaluated_at=self._clock())
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            raise

        evaluation = self._persist(evaluation)
        self._evaluations += 1
        return evaluation

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "strategies": [item.model_dump() for item in self.catalog().strategies],
            "evaluations": self._evaluations,
            "persisted_evaluations": self._repository.count() if self._repository else None,
            "last_error": self._last_error,
            "generated_at": self._clock().isoformat(),
        }

    def _persist(self, evaluation: TrendPullbackEvaluation) -> TrendPullbackEvaluation:
        if self._repository is None:
            return evaluation
        try:
            self._repository.insert(
                evaluation_id=evaluation.evaluation_id,
                strategy_id=evaluation.strategy_id,
                strategy_version=evaluation.strategy_version,
                config_version=evaluation.config_version,
                symbol=evaluation.symbol,
                timeframe=evaluation.timeframe,
                decision=evaluation.decision.value,
                direction=evaluation.direction.value,
                quality_score=evaluation.quality.score,
                confirmation_status=evaluation.confirmation_status.value,
                market_snapshot_id=evaluation.market_snapshot_id,
                data_as_of=evaluation.data_as_of.isoformat(),
                evaluated_at=evaluation.evaluated_at.isoformat(),
                payload=evaluation.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - persistence is audit, not a reason to fail evaluation
            logger.exception("Strategy evaluation persistence failed")
            return evaluation.model_copy(
                update={
                    "warnings": [
                        *evaluation.warnings,
                        "Strategy evaluation persistence failed; the evaluation was still returned.",
                    ]
                }
            )
        return evaluation
