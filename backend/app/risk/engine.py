"""Pure deterministic risk and reward validation.

The engine consumes already-computed plan geometry. It never chooses entries, stops
or targets, never fetches data, and never invents account information. All financial
arithmetic uses :class:`decimal.Decimal`; no position size is produced.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.analysis.contracts import MarketSnapshot, ValidationStatus
from app.risk.contracts import (
    DEFAULT_RISK_POLICY,
    MISSING_ACCOUNT_INPUTS,
    ExecutionEligibility,
    PositionSizeStatus,
    RiskAssessment,
    RiskCheck,
    RiskPolicy,
    RiskReason,
    RiskReward,
    RiskValidationStatus,
    StrategyValidationStatus,
)
from app.strategies.contracts import ConfirmationStatus, StrategyDirection, TrendPullbackEvaluation


def _quantize(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _atr_factor(distance: Decimal, atr: Decimal) -> float:
    if atr <= 0:
        return 0.0
    return float(distance / atr)


def assess_risk(
    *,
    direction: StrategyDirection,
    entry: Decimal,
    stop: Decimal,
    targets: list[Decimal],
    target_conflict: bool,
    atr: Decimal,
    snapshot: MarketSnapshot,
    evaluation: TrendPullbackEvaluation,
    strategy_status: StrategyValidationStatus = StrategyValidationStatus.PENDING,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
) -> RiskAssessment:
    checks: list[RiskCheck] = []
    reasons: list[RiskReason] = []
    warnings: list[str] = [
        f"Strategy '{evaluation.strategy_id}' {evaluation.strategy_version} is "
        f"{strategy_status.value}; risk validation does not validate the strategy.",
        "Targets are deterministic projections from structure/ATR/risk multiples; they are not promises.",
        "Position size is NOT_CALCULATED because verified account inputs are unavailable.",
    ]

    def blocking(name: str, passed: bool, detail: str, code: str, message: str) -> None:
        checks.append(RiskCheck(name=name, passed=passed, blocking=True, detail=detail))
        if not passed:
            reasons.append(RiskReason(code=code, message=message, detail=detail))

    valid_data = snapshot.validation.status is ValidationStatus.OK
    blocking(
        "market_data_valid",
        valid_data,
        f"validation={snapshot.validation.status.value}",
        "MARKET_DATA_INVALID",
        "The market snapshot is not valid for risk assessment.",
    )
    blocking(
        "market_data_fresh",
        not snapshot.is_stale,
        f"is_stale={snapshot.is_stale}",
        "MARKET_DATA_STALE",
        "The market snapshot is stale; no plan can be risk-valid.",
    )
    blocking(
        "strategy_confirmation",
        evaluation.confirmation_status is ConfirmationStatus.CONFIRMED,
        f"confirmation={evaluation.confirmation_status.value}",
        "REQUIRED_EVIDENCE_MISSING",
        "A confirmed closed-bar strategy candidate is required.",
    )

    has_evidence = bool(
        snapshot.snapshot_id
        and evaluation.evaluation_id
        and evaluation.market_snapshot_id == snapshot.snapshot_id
        and snapshot.trend.ema21 is not None
        and snapshot.volatility.atr14 is not None
        and atr > 0
        and len(targets) == 3
    )
    blocking(
        "required_evidence",
        has_evidence,
        "snapshot/evaluation ids, EMA21, positive ATR and three targets are required",
        "REQUIRED_EVIDENCE_MISSING",
        "Required plan evidence is missing or inconsistent.",
    )

    if direction is StrategyDirection.LONG:
        entry_ok = stop < entry and all(target > entry for target in targets)
    else:
        entry_ok = stop > entry and all(target < entry for target in targets)
    blocking(
        "entry_geometry",
        entry > 0 and entry_ok,
        f"entry={entry}, stop={stop}, targets={[str(t) for t in targets]}",
        "INVALID_ENTRY_GEOMETRY",
        "Entry or target geometry is on the wrong side of the reference price.",
    )

    stop_distance = abs(entry - stop)
    stop_ok = stop_distance > 0 and (
        (direction is StrategyDirection.LONG and stop < entry)
        or (direction is StrategyDirection.SHORT and stop > entry)
    )
    blocking(
        "stop_geometry",
        stop_ok,
        f"stop_distance={stop_distance}, direction={direction.value}",
        "INVALID_STOP_GEOMETRY",
        "Stop-loss geometry is invalid for the plan direction.",
    )
    stop_distance_atr = _atr_factor(stop_distance, atr)
    blocking(
        "minimum_stop_distance",
        stop_distance_atr >= policy.min_stop_distance_atr,
        f"stop_distance={stop_distance_atr:.4f} ATR, min={policy.min_stop_distance_atr}",
        "INVALID_STOP_GEOMETRY",
        "Stop distance is inside the configured minimum.",
    )
    blocking(
        "maximum_stop_distance",
        stop_distance_atr <= policy.max_stop_distance_atr,
        f"stop_distance={stop_distance_atr:.4f} ATR, max={policy.max_stop_distance_atr}",
        "STOP_DISTANCE_EXCEEDED",
        "Stop distance exceeds the configured maximum; the stop is not widened or narrowed to fit R:R.",
    )
    blocking(
        "target_structure_conflict",
        not target_conflict,
        f"target_conflict={target_conflict}",
        "TARGET_STRUCTURE_CONFLICT",
        "A confirmed structural level conflicts with the required first target.",
    )

    ordered = len(targets) == 3 and (
        (targets[1] > targets[0] > entry and targets[2] > targets[1])
        if direction is StrategyDirection.LONG
        else (targets[1] < targets[0] < entry and targets[2] < targets[1])
    )
    spacing = Decimal(str(policy.min_target_spacing_atr)) * atr
    spaced = len(targets) == 3 and (
        abs(targets[1] - targets[0]) >= spacing and abs(targets[2] - targets[1]) >= spacing
    )
    blocking(
        "target_ordering",
        ordered and spaced,
        f"targets={[str(t) for t in targets]}, spacing={spacing}",
        "INVALID_TARGET_GEOMETRY",
        "Targets are not ordered correctly or are closer than the required spacing.",
    )

    risk_reward: RiskReward | None = None
    if stop_distance > 0 and len(targets) == 3:
        rewards = [abs(target - entry) for target in targets]
        ratios = [_quantize(reward / stop_distance, policy.ratio_decimals) for reward in rewards]
        risk_reward = RiskReward(
            entry_to_stop=_quantize(stop_distance, policy.price_decimals),
            risk_per_unit=_quantize(stop_distance, policy.price_decimals),
            tp1_reward=_quantize(rewards[0], policy.price_decimals),
            tp2_reward=_quantize(rewards[1], policy.price_decimals),
            tp3_reward=_quantize(rewards[2], policy.price_decimals),
            rr_tp1=ratios[0],
            rr_tp2=ratios[1],
            rr_tp3=ratios[2],
            stop_distance_atr=round(stop_distance_atr, 4),
            tp1_distance_atr=round(_atr_factor(rewards[0], atr), 4),
            tp2_distance_atr=round(_atr_factor(rewards[1], atr), 4),
            tp3_distance_atr=round(_atr_factor(rewards[2], atr), 4),
        )
        blocking(
            "minimum_risk_reward",
            ratios[0] >= Decimal(str(policy.min_rr_tp1)),
            f"rr_tp1={ratios[0]}, min={policy.min_rr_tp1}",
            "INSUFFICIENT_RISK_REWARD",
            "TP1 risk/reward is below the configured minimum.",
        )

    checks.append(
        RiskCheck(
            name="strategy_validation",
            passed=strategy_status is StrategyValidationStatus.VALIDATED,
            blocking=False,
            detail=f"strategy_validation={strategy_status.value}; execution review is still required",
        )
    )
    checks.append(
        RiskCheck(
            name="position_size",
            passed=False,
            blocking=False,
            detail=f"position_size_status={PositionSizeStatus.NOT_CALCULATED.value}; missing {', '.join(MISSING_ACCOUNT_INPUTS)}",
        )
    )

    passed = not reasons
    return RiskAssessment(
        policy_version=policy.policy_version,
        validation_status=RiskValidationStatus.VALID if passed else RiskValidationStatus.INVALID,
        passed=passed,
        checks=checks,
        reasons=reasons,
        warnings=warnings,
        risk_reward=risk_reward,
        position_size_status=PositionSizeStatus.NOT_CALCULATED.value,
        position_size=None,
        missing_account_inputs=list(MISSING_ACCOUNT_INPUTS),
    )


def execution_eligibility(
    *, plan_status: str, strategy_status: StrategyValidationStatus
) -> ExecutionEligibility:
    """No plan is executable in this phase, regardless of technical validity."""

    if plan_status in {"PLAN_BLOCKED", "PLAN_INVALID", "PLAN_EXPIRED"}:
        return ExecutionEligibility.NOT_ELIGIBLE
    if strategy_status is not StrategyValidationStatus.VALIDATED:
        return ExecutionEligibility.REVIEW_REQUIRED
    return ExecutionEligibility.EXECUTION_DISABLED
