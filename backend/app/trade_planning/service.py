"""Trade-planning service and deterministic plan lifecycle."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.analysis.contracts import (
    SCOPE_SYMBOL,
    SCOPE_TIMEFRAME,
    SCOPE_TIMEFRAME_SECONDS,
    MarketSnapshot,
    ValidationStatus,
    scope_for,
)
from app.analysis.service import AnalysisService
from app.core.errors import NotFoundError, UnsupportedScopeError
from app.persistence.repositories import TradePlanRepository
from app.risk.contracts import (
    MISSING_ACCOUNT_INPUTS,
    PlanValidationStatus,
    RiskCurrentResponse,
    RiskPolicy,
    RiskReason,
    RiskValidationStatus,
    StrategyValidationStatus,
)
from app.risk.engine import execution_eligibility
from app.risk.service import RiskService
from app.strategies.config import STRATEGY_ID
from app.strategies.contracts import StrategyDecision, TrendPullbackEvaluation
from app.strategies.service import StrategyService
from app.trade_planning.contracts import (
    PlanEvidence,
    PlanReason,
    PlanStatus,
    TradePlan,
    TradePlanningResult,
)
from app.trade_planning.planner import build_geometry
from app.trade_planning.provenance import strategy_validation_status
from app.trade_planning.validation import all_passed, validate_geometry

logger = logging.getLogger(__name__)
PLAN_VERSION = "1.0.0"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _reason(code: str, message: str, detail: str | None = None) -> PlanReason:
    return PlanReason(code=code, message=message, detail=detail)


class TradePlanningService:
    def __init__(
        self,
        *,
        analysis: AnalysisService,
        strategies: StrategyService,
        risk: RiskService,
        repository: TradePlanRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._analysis = analysis
        self._strategies = strategies
        self._risk = risk
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache: tuple[str, TradePlanningResult] | None = None
        self._plans = 0
        self._last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return True

    @property
    def policy(self) -> RiskPolicy:
        return self._risk.policy

    def current(
        self,
        *,
        symbol: str = SCOPE_SYMBOL,
        timeframe: str = SCOPE_TIMEFRAME,
        refresh: bool = False,
    ) -> TradePlanningResult:
        scope = scope_for(symbol, timeframe)
        if not scope.supported:
            raise UnsupportedScopeError(scope.reason or "Unsupported market scope.", scope.model_dump())

        snapshot = self._analysis.snapshot(symbol=scope.symbol, timeframe=scope.timeframe, refresh=refresh)
        evaluation = self._strategies.evaluate(
            strategy_id=STRATEGY_ID, symbol=scope.symbol, timeframe=scope.timeframe, refresh=False
        )
        if evaluation.market_snapshot_id != snapshot.snapshot_id:
            snapshot = self._analysis.snapshot(symbol=scope.symbol, timeframe=scope.timeframe, refresh=True)
            evaluation = self._strategies.evaluate(
                strategy_id=STRATEGY_ID, symbol=scope.symbol, timeframe=scope.timeframe, refresh=True
            )
        if evaluation.market_snapshot_id != snapshot.snapshot_id:
            raise RuntimeError("strategy evaluation and market snapshot could not be aligned")

        expires_at = min(
            evaluation.valid_until,
            snapshot.data_as_of + timedelta(seconds=SCOPE_TIMEFRAME_SECONDS * self.policy.max_plan_bars),
        )
        cache_key = f"{evaluation.evaluation_id}|{self.policy.policy_version}|{expires_at.isoformat()}"
        if not refresh and self._cache is not None and self._cache[0] == cache_key:
            return self._cache[1].model_copy(update={"cached": True})

        try:
            result = self._build(snapshot=snapshot, evaluation=evaluation, expires_at=expires_at)
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            raise
        if result.plan is not None:
            result = self._persist(result)
            self._plans += 1
        self._cache = (cache_key, result)
        return result

    def get_plan(self, plan_id: str) -> TradePlan:
        if self._repository is None:
            raise NotFoundError(f"Trade plan '{plan_id}' is not available.")
        payload = self._repository.get(plan_id)
        if payload is None:
            raise NotFoundError(f"Trade plan '{plan_id}' was not found.", {"plan_id": plan_id})
        payload.pop("updated_at", None)
        plan = TradePlan.model_validate(payload)
        refreshed = self._refresh_lifecycle(plan)
        if refreshed != plan and self._repository is not None:
            try:
                self._repository.update_status(
                    plan_id,
                    refreshed.plan_status.value,
                    refreshed.execution_eligibility.value,
                )
            except Exception:  # noqa: BLE001 - lifecycle response is still authoritative
                logger.exception("Trade-plan status update failed")
        return refreshed

    def risk_current(
        self,
        *,
        symbol: str = SCOPE_SYMBOL,
        timeframe: str = SCOPE_TIMEFRAME,
        refresh: bool = False,
    ) -> RiskCurrentResponse:
        result = self.current(symbol=symbol, timeframe=timeframe, refresh=refresh)
        assessment = result.plan.risk_assessment if result.plan is not None else None
        return RiskCurrentResponse(
            request_id=result.request_id,
            plan_id=result.plan.plan_id if result.plan is not None else None,
            strategy_id=result.strategy_id,
            strategy_version=result.strategy_version,
            strategy_validation_status=result.strategy_validation_status,
            plan_status=result.status.value,
            plan_validation_status=result.plan_validation_status,
            risk_validation_status=result.risk_validation_status,
            execution_eligibility=result.execution_eligibility,
            risk_policy_version=result.risk_policy_version,
            position_size_status="NOT_CALCULATED",
            position_size=None,
            missing_account_inputs=result.missing_account_inputs,
            assessment=assessment,
            rejection_reasons=[
                RiskReason(code=reason.code, message=reason.message, detail=reason.detail)
                for reason in result.rejection_reasons
            ],
            warnings=result.warnings,
            market_snapshot_id=result.market_snapshot_id,
            strategy_evaluation_id=result.strategy_evaluation_id,
            data_as_of=result.data_as_of,
            generated_at=result.generated_at,
        )

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "risk_policy_version": self.policy.policy_version,
            "plans_built": self._plans,
            "persisted_plans": self._repository.count() if self._repository else None,
            "strategy_validation_status": strategy_validation_status(STRATEGY_ID).value,
            "execution": "disabled",
            "last_error": self._last_error,
            "generated_at": self._clock().isoformat(),
        }

    # -- construction -------------------------------------------------------
    def _build(
        self, *, snapshot: MarketSnapshot, evaluation: TrendPullbackEvaluation, expires_at: datetime
    ) -> TradePlanningResult:
        now = self._clock()
        strategy_status = strategy_validation_status(evaluation.strategy_id)
        base_warnings = _dedupe([*snapshot.warnings, *evaluation.warnings])
        evidence = [
            PlanEvidence(code=item.code, message=item.message, refs=item.refs) for item in evaluation.evidence
        ]

        if snapshot.validation.status is ValidationStatus.INVALID:
            return self._no_plan(
                snapshot, evaluation, expires_at,
                status=PlanStatus.PLAN_INVALID,
                plan_validation=PlanValidationStatus.INVALID,
                reasons=[_reason("MARKET_DATA_INVALID", "The market snapshot failed OHLCV validation.",
                                  "; ".join(snapshot.validation.errors) or None)],
                warnings=base_warnings,
                evidence=evidence,
            )
        if snapshot.validation.status is ValidationStatus.INSUFFICIENT_DATA:
            return self._no_plan(
                snapshot, evaluation, expires_at,
                status=PlanStatus.PLAN_INVALID,
                plan_validation=PlanValidationStatus.INVALID,
                reasons=[_reason("MARKET_DATA_INSUFFICIENT", "The market snapshot lacks enough closed candles.")],
                warnings=base_warnings,
                evidence=evidence,
            )
        if snapshot.is_stale or snapshot.validation.status is ValidationStatus.STALE:
            return self._no_plan(
                snapshot, evaluation, expires_at,
                status=PlanStatus.PLAN_EXPIRED,
                plan_validation=PlanValidationStatus.NOT_EVALUATED,
                reasons=[_reason("MARKET_DATA_STALE", "Stale market data cannot produce a usable plan.")],
                warnings=base_warnings,
                evidence=evidence,
            )
        if now >= expires_at or now >= evaluation.valid_until:
            return self._no_plan(
                snapshot, evaluation, expires_at,
                status=PlanStatus.PLAN_EXPIRED,
                plan_validation=PlanValidationStatus.NOT_EVALUATED,
                reasons=[_reason("PLAN_EXPIRED", "The strategy candidate or plan lifetime has expired.")],
                warnings=base_warnings,
                evidence=evidence,
            )

        if evaluation.decision not in {StrategyDecision.LONG, StrategyDecision.SHORT}:
            reasons = [
                _reason(
                    "STRATEGY_WAIT" if evaluation.decision is StrategyDecision.WAIT else "STRATEGY_NO_TRADE",
                    f"Strategy decision is {evaluation.decision.value}; no trade plan is constructed.",
                )
            ]
            reasons.extend(
                _reason(reason.code, reason.message, reason.detail)
                for reason in [*evaluation.wait_reasons, *evaluation.rejection_reasons]
            )
            return self._no_plan(
                snapshot, evaluation, expires_at,
                status=PlanStatus.PLAN_BLOCKED,
                plan_validation=PlanValidationStatus.NOT_EVALUATED,
                reasons=reasons,
                warnings=base_warnings,
                evidence=evidence,
            )

        geometry_result = build_geometry(evaluation=evaluation, snapshot=snapshot, policy=self.policy)
        if geometry_result.geometry is None:
            return self._no_plan(
                snapshot, evaluation, expires_at,
                status=PlanStatus.PLAN_INVALID,
                plan_validation=PlanValidationStatus.INVALID,
                reasons=geometry_result.reasons,
                warnings=_dedupe([*base_warnings, *geometry_result.warnings]),
                evidence=evidence,
                checks=geometry_result.checks,
            )
        geometry = geometry_result.geometry
        validation_checks = validate_geometry(
            geometry=geometry, evaluation=evaluation, snapshot=snapshot, now=now, policy=self.policy
        )
        if not all_passed(validation_checks):
            failed = [check for check in validation_checks if not check.passed]
            return self._no_plan(
                snapshot, evaluation, expires_at,
                status=PlanStatus.PLAN_INVALID,
                plan_validation=PlanValidationStatus.INVALID,
                reasons=[
                    _reason(
                        "INVALID_PLAN_GEOMETRY",
                        "Plan geometry failed deterministic validation.",
                        "; ".join(f"{check.name}: {check.detail}" for check in failed),
                    )
                ],
                warnings=_dedupe([*base_warnings, *geometry_result.warnings]),
                evidence=[*evidence, *geometry.evidence],
                checks=[*geometry_result.checks, *validation_checks],
            )

        assessment = self._risk.assess(
            direction=geometry.direction,
            entry=geometry.suggested_entry,
            stop=geometry.stop_loss,
            targets=[target.price for target in geometry.targets],
            target_conflict=geometry.target_conflict,
            atr=geometry.atr,
            snapshot=snapshot,
            evaluation=evaluation,
            strategy_status=strategy_status,
        )
        if assessment.passed:
            plan_status = (
                PlanStatus.PLAN_REVIEW_REQUIRED
                if strategy_status is not StrategyValidationStatus.VALIDATED
                else PlanStatus.PLAN_READY
            )
        else:
            plan_status = PlanStatus.PLAN_BLOCKED
        eligibility = execution_eligibility(plan_status=plan_status.value, strategy_status=strategy_status)
        plan_id = self._plan_id(evaluation, expires_at)
        reasons = [
            _reason(reason.code, reason.message, reason.detail) for reason in assessment.reasons
        ]
        plan_warnings = _dedupe(
            [
                *base_warnings,
                *geometry_result.warnings,
                *assessment.warnings,
                (
                    f"UNVALIDATED_STRATEGY: {evaluation.strategy_id} {evaluation.strategy_version} "
                    "has a PENDING independent gate; execution eligibility is review-gated."
                    if strategy_status is not StrategyValidationStatus.VALIDATED
                    else ""
                ),
            ]
        )
        plan = TradePlan(
            plan_id=plan_id,
            strategy_id=evaluation.strategy_id,
            strategy_version=evaluation.strategy_version,
            strategy_config_version=evaluation.config_version,
            strategy_evaluation_id=evaluation.evaluation_id,
            strategy_validation_status=strategy_status,
            strategy_quality_score=evaluation.quality.score,
            market_snapshot_id=snapshot.snapshot_id,
            market_feature_version=snapshot.feature_version,
            symbol=evaluation.symbol,
            timeframe=evaluation.timeframe,
            direction=geometry.direction.value,
            reference_price=geometry.reference_price,
            entry_zone=geometry.entry_zone,
            suggested_entry=geometry.suggested_entry,
            stop_loss=geometry.stop_loss,
            stop_basis=geometry.stop_basis,
            take_profits=geometry.targets,
            risk_reward=assessment.risk_reward,
            invalidation_conditions=geometry.invalidation_conditions,
            confirmation_requirements=geometry.confirmation_requirements,
            plan_status=plan_status,
            plan_validation_status=PlanValidationStatus.VALID,
            risk_validation_status=assessment.validation_status,
            execution_eligibility=eligibility,
            risk_policy_version=self.policy.policy_version,
            risk_assessment=assessment,
            missing_account_inputs=assessment.missing_account_inputs,
            warnings=plan_warnings,
            evidence=[*evidence, *geometry.evidence],
            rejection_reasons=reasons,
            data_as_of=snapshot.data_as_of,
            created_at=now,
            expires_at=expires_at,
        )
        return TradePlanningResult(
            request_id=snapshot.request_id,
            status=plan_status,
            plan=plan,
            strategy_id=evaluation.strategy_id,
            strategy_version=evaluation.strategy_version,
            strategy_config_version=evaluation.config_version,
            strategy_evaluation_id=evaluation.evaluation_id,
            strategy_validation_status=strategy_status,
            strategy_decision=evaluation.decision.value,
            market_snapshot_id=snapshot.snapshot_id,
            market_feature_version=snapshot.feature_version,
            symbol=evaluation.symbol,
            timeframe=evaluation.timeframe,
            direction=evaluation.direction.value,
            reference_price=evaluation.reference_price,
            plan_validation_status=PlanValidationStatus.VALID,
            risk_validation_status=assessment.validation_status,
            execution_eligibility=eligibility,
            risk_policy_version=self.policy.policy_version,
            position_size_status="NOT_CALCULATED",
            position_size=None,
            missing_account_inputs=assessment.missing_account_inputs,
            rejection_reasons=reasons,
            warnings=plan_warnings,
            checks=validation_checks,
            evidence=[*evidence, *geometry.evidence],
            data_as_of=snapshot.data_as_of,
            expires_at=expires_at,
            generated_at=now,
        )

    def _no_plan(
        self,
        snapshot: MarketSnapshot,
        evaluation: TrendPullbackEvaluation,
        expires_at: datetime,
        *,
        status: PlanStatus,
        plan_validation: PlanValidationStatus,
        reasons: list[PlanReason],
        warnings: list[str],
        evidence: list[PlanEvidence],
        checks=None,
    ) -> TradePlanningResult:
        strategy_status = strategy_validation_status(evaluation.strategy_id)
        now = self._clock()
        eligibility = execution_eligibility(plan_status=status.value, strategy_status=strategy_status)
        return TradePlanningResult(
            request_id=snapshot.request_id,
            status=status,
            plan=None,
            strategy_id=evaluation.strategy_id,
            strategy_version=evaluation.strategy_version,
            strategy_config_version=evaluation.config_version,
            strategy_evaluation_id=evaluation.evaluation_id,
            strategy_validation_status=strategy_status,
            strategy_decision=evaluation.decision.value,
            market_snapshot_id=snapshot.snapshot_id,
            market_feature_version=snapshot.feature_version,
            symbol=evaluation.symbol,
            timeframe=evaluation.timeframe,
            direction=evaluation.direction.value,
            reference_price=evaluation.reference_price,
            plan_validation_status=plan_validation,
            risk_validation_status=RiskValidationStatus.NOT_EVALUATED,
            execution_eligibility=eligibility,
            risk_policy_version=self.policy.policy_version,
            missing_account_inputs=list(MISSING_ACCOUNT_INPUTS),
            rejection_reasons=reasons,
            warnings=warnings,
            checks=checks or [],
            evidence=evidence,
            data_as_of=snapshot.data_as_of,
            expires_at=expires_at,
            generated_at=now,
        )

    def _plan_id(self, evaluation: TrendPullbackEvaluation, expires_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{evaluation.evaluation_id}|{self.policy.policy_version}|{PLAN_VERSION}|"
            f"{evaluation.direction.value}|{expires_at.isoformat()}".encode()
        ).hexdigest()
        return f"plan_{digest[:24]}"

    def _persist(self, result: TradePlanningResult) -> TradePlanningResult:
        if self._repository is None or result.plan is None:
            return result
        try:
            self._repository.insert(plan=result.plan)
        except Exception:  # noqa: BLE001 - persistence is audit, not a reason to fail planning
            logger.exception("Trade-plan persistence failed")
            plan = result.plan.model_copy(
                update={
                    "warnings": [
                        *result.plan.warnings,
                        "Trade-plan persistence failed; the plan was still returned.",
                    ]
                }
            )
            return result.model_copy(
                update={
                    "plan": plan,
                    "warnings": [
                        *result.warnings,
                        "Trade-plan persistence failed; the plan was still returned.",
                    ],
                }
            )
        return result

    def _refresh_lifecycle(self, plan: TradePlan) -> TradePlan:
        now = self._clock()
        snapshot = self._analysis.snapshot(symbol=plan.symbol, timeframe=plan.timeframe, refresh=True)
        status = plan.plan_status
        reasons = list(plan.rejection_reasons)
        warnings = list(plan.warnings)

        def mark(new_status: PlanStatus, code: str, message: str) -> TradePlan:
            reasons.append(_reason(code, message))
            eligibility = execution_eligibility(
                plan_status=new_status.value, strategy_status=plan.strategy_validation_status
            )
            return plan.model_copy(
                update={
                    "plan_status": new_status,
                    "execution_eligibility": eligibility,
                    "rejection_reasons": reasons,
                    "warnings": warnings,
                }
            )

        if snapshot.validation.status is ValidationStatus.INVALID:
            return mark(PlanStatus.PLAN_INVALID, "MARKET_DATA_INVALID", "The latest snapshot is invalid.")
        if snapshot.is_stale or snapshot.validation.status is ValidationStatus.STALE:
            return mark(PlanStatus.PLAN_EXPIRED, "MARKET_DATA_STALE", "The plan expired because market data is stale.")
        if now >= plan.expires_at:
            return mark(PlanStatus.PLAN_EXPIRED, "PLAN_EXPIRED", "The plan lifetime has elapsed.")
        if snapshot.data_as_of > plan.data_as_of and status in {
            PlanStatus.PLAN_READY,
            PlanStatus.PLAN_REVIEW_REQUIRED,
        }:
            close = snapshot.last_price
            atr = float(snapshot.volatility.atr14 or 0.0)
            tolerance = atr * self.policy.entry_tolerance_atr
            if plan.direction == "LONG":
                if close < float(plan.stop_loss):
                    return mark(PlanStatus.PLAN_INVALID, "INVALIDATION_TRIGGERED", "Price closed below the plan stop.")
                if close > float(plan.entry_zone.upper) + tolerance:
                    return mark(PlanStatus.PLAN_EXPIRED, "ENTRY_MISSED", "Price moved above the long entry zone.")
            else:
                if close > float(plan.stop_loss):
                    return mark(PlanStatus.PLAN_INVALID, "INVALIDATION_TRIGGERED", "Price closed above the plan stop.")
                if close < float(plan.entry_zone.lower) - tolerance:
                    return mark(PlanStatus.PLAN_EXPIRED, "ENTRY_MISSED", "Price moved below the short entry zone.")
        return plan
