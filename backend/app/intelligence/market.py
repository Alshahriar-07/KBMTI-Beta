"""Deterministic assembly and assessment for the unified market response.

Nothing in this module calls a model. It turns the persisted PATRON run and the
deterministic market snapshot into typed, traceable evidence and a rule-based
forecast assessment. Qwen only narrates this output afterwards.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.intelligence.contracts import QwenMetadata, QwenStatus
from app.intelligence.market_contracts import (
    ExecutionReadiness,
    ForecastAssessment,
    ForecastAssessmentStatus,
    ForecastSourceInfo,
    MarketCondition,
    MarketReadiness,
    PatronReadiness,
    PipelineReadiness,
    PositionSizeReadiness,
    QwenReadiness,
    RiskReadiness,
    RiskValidationView,
    StrategyReadiness,
    TradePlanReadiness,
    UnifiedTradePlan,
)
from app.risk.contracts import MISSING_ACCOUNT_INPUTS

BAR_SECONDS = 900
STALE_AFTER_SECONDS = 2 * BAR_SECONDS
WIDE_INTERVAL_ATR = 8.0
NARROW_INTERVAL_ATR = 0.05
MIN_BARRIER_MARGIN = 0.40
MIN_MOMENTUM_MARGIN = 0.30
# A sign flip in the final median is not a directional disagreement worth a conflict
# when the median has barely moved relative to a 15-minute bar's average range. This
# threshold is a measurement, not a rewrite of PATRON: the raw direction and the
# measured displacement are both still reported.
MATERIAL_DIRECTION_ATR = 0.25


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _sha256_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _final_close_band(payload: dict[str, Any]) -> tuple[float, float, float] | None:
    """Final-step close quantiles (q10, q50, q90) in return units."""

    try:
        band = payload["range_quantiles"][-1]["close"]
        return float(band["q10"]), float(band["q50"]), float(band["q90"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def forecast_direction(payload: dict[str, Any]) -> str | None:
    band = _final_close_band(payload)
    if band is None:
        return None
    median = band[1]
    if median > 0:
        return "BULLISH"
    if median < 0:
        return "BEARISH"
    return "NEUTRAL"


def deterministic_direction(snapshot: Any) -> str:
    trend = str(getattr(getattr(snapshot, "trend", None), "state", ""))
    momentum = str(getattr(getattr(snapshot, "momentum", None), "state", ""))
    regime = str(getattr(getattr(snapshot, "regime", None), "state", ""))
    if "BULLISH" in trend or regime == "TRENDING_UP":
        return "BULLISH"
    if "BEARISH" in trend or regime == "TRENDING_DOWN":
        return "BEARISH"
    if momentum == "BULLISH":
        return "BULLISH"
    if momentum == "BEARISH":
        return "BEARISH"
    return "NEUTRAL"


def market_condition(snapshot: Any) -> MarketCondition:
    trend = str(getattr(snapshot.trend.state, "value", snapshot.trend.state))
    strength = str(getattr(snapshot.trend.strength, "value", snapshot.trend.strength))
    alignment = str(getattr(snapshot.trend.alignment, "value", snapshot.trend.alignment))
    structure = str(getattr(snapshot.structure.state, "value", snapshot.structure.state))
    momentum = str(getattr(snapshot.momentum.state, "value", snapshot.momentum.state))
    momentum_phase = str(
        getattr(snapshot.momentum.phase, "value", snapshot.momentum.phase)
    )
    volatility = str(getattr(snapshot.volatility.state, "value", snapshot.volatility.state))
    volatility_phase = str(
        getattr(snapshot.volatility.phase, "value", snapshot.volatility.phase)
    )
    regime = str(getattr(snapshot.regime.state, "value", snapshot.regime.state))
    direction = deterministic_direction(snapshot)
    summary = (
        f"Regime {regime}; trend {trend} ({strength}, {alignment}); "
        f"structure {structure}; momentum {momentum} ({momentum_phase}); "
        f"volatility {volatility} ({volatility_phase})."
    )
    return MarketCondition(
        trend=trend,
        trend_strength=strength,
        trend_alignment=alignment,
        structure=structure,
        momentum=momentum,
        momentum_phase=momentum_phase,
        volatility=volatility,
        volatility_phase=volatility_phase,
        regime=regime,
        direction=direction,
        summary=summary,
    )


def assess_forecast(
    run: dict[str, Any] | None,
    snapshot: Any,
    now: datetime | None = None,
) -> tuple[ForecastSourceInfo | None, ForecastAssessment]:
    """Return immutable source evidence and a deterministic assessment.

    Priority: UNAVAILABLE -> INVALID -> STALE -> CONFLICTING_EVIDENCE ->
    LOW_CONFIDENCE -> VALID. No numeric confidence is produced.
    """

    now = now or datetime.now(UTC)
    if not run:
        return None, ForecastAssessment(
            status=ForecastAssessmentStatus.UNAVAILABLE,
            reasons=["No persisted PATRON forecast exists. Deterministic analysis continues."],
            usable_in_decision=False,
        )
    output = run.get("output") or {}
    payload = output.get("patron") if isinstance(output, dict) else None
    meta = output.get("meta") if isinstance(output, dict) else None
    if not isinstance(payload, dict):
        return None, ForecastAssessment(
            status=ForecastAssessmentStatus.UNAVAILABLE,
            reasons=[
                "The latest forecast run has no PATRON payload (possibly a failed run). "
                "Deterministic analysis continues."
            ],
            usable_in_decision=False,
        )

    predicted_candles = [
        dict(candle)
        for candle in (run.get("candles") or [])
        if isinstance(candle, dict)
    ]
    source = ForecastSourceInfo(
        model_id=str(run.get("model_id") or payload.get("model_version") or "patron"),
        model_version=str(payload.get("model_version") or run.get("model_id") or "unknown"),
        checkpoint=str(meta.get("checkpoint")) if isinstance(meta, dict) else None,
        checkpoint_sha256=str(meta.get("checkpoint_sha256"))
        if isinstance(meta, dict) and meta.get("checkpoint_sha256")
        else None,
        feature_version=str(payload.get("feature_version"))
        if payload.get("feature_version")
        else None,
        generated_at=_parse_time(run.get("created_at")),
        forecast_as_of=_parse_time(payload.get("as_of")),
        input_last_bar_at=_parse_time(
            datetime.fromtimestamp(int(run["input_last_bar_at"]), UTC).isoformat()
        )
        if run.get("input_last_bar_at") is not None
        else None,
        horizon_candles=len(payload.get("range_quantiles") or []),
        horizon_minutes=int(payload.get("horizon_minutes") or 90),
        reference_close=_num(meta.get("reference_close")) if isinstance(meta, dict) else None,
        range_quantiles=list(payload.get("range_quantiles") or []),
        predicted_candles=predicted_candles,
        barrier_probabilities={
            str(key): float(value)
            for key, value in (payload.get("barrier_probabilities") or {}).items()
            if _num(value) is not None
        },
        momentum=dict(payload.get("momentum") or {}),
        data_quality=dict(payload.get("data_quality") or {}),
        source_hash=_sha256_payload(
            {"patron": payload, "predicted_candles": predicted_candles}
        ),
        freshness_seconds=None,
    )

    reasons: list[str] = []
    conflicts: list[str] = []
    invalid = False

    if str(payload.get("status")) != "OK":
        invalid = True
        reasons.append(f"PATRON returned status {payload.get('status') or 'UNKNOWN'}, not OK.")
    quantiles = payload.get("range_quantiles")
    if not isinstance(quantiles, list) or not quantiles:
        invalid = True
        reasons.append("PATRON range_quantiles is missing or empty.")
        quantiles = []
    for index, step in enumerate(quantiles, start=1):
        if not isinstance(step, dict):
            invalid = True
            reasons.append(f"Forecast step {index} is not an object.")
            continue
        for field in ("high", "low", "close"):
            band = step.get(field)
            if not isinstance(band, dict):
                invalid = True
                reasons.append(f"Forecast step {index} has no {field} quantiles.")
                continue
            q10, q50, q90 = (_num(band.get("q10")), _num(band.get("q50")), _num(band.get("q90")))
            if q10 is None or q50 is None or q90 is None:
                invalid = True
                reasons.append(f"Forecast step {index} {field} has non-numeric quantiles.")
            elif not (q10 <= q50 <= q90):
                invalid = True
                reasons.append(
                    f"Forecast step {index} {field} quantiles are not ordered "
                    f"(q10={q10}, q50={q50}, q90={q90})."
                )

    latest_market = getattr(getattr(snapshot, "provenance", None), "last_closed_candle_time", None)
    latest_market = _parse_time(latest_market)
    freshness = None
    if source.forecast_as_of and latest_market:
        freshness = (latest_market - source.forecast_as_of).total_seconds()
    elif source.generated_at:
        freshness = (now - source.generated_at).total_seconds()
    if source.forecast_as_of and now:
        age = (now - source.forecast_as_of).total_seconds()
        if freshness is None or age > freshness:
            freshness = age
    source = source.model_copy(update={"freshness_seconds": round(freshness, 1) if freshness is not None else None})

    # Interval width is expressed in ATR units of the last closed bar.
    atr = _num(getattr(getattr(snapshot, "volatility", None), "atr14", None))
    price = _num(getattr(snapshot, "last_price", None))
    atr_pct = (atr / price) if atr and price else None
    widths: list[float] = []
    if atr_pct and atr_pct > 0:
        for step in quantiles:
            try:
                width = float(step["close"]["q90"]) - float(step["close"]["q10"])
            except (KeyError, TypeError, ValueError):
                continue
            widths.append(width / atr_pct)
    interval_width_atr = round(sum(widths) / len(widths), 3) if widths else None

    barrier = source.barrier_probabilities
    barrier_name = max(barrier, key=barrier.get) if barrier else None
    barrier_margin = max(barrier.values()) if barrier else None
    momentum_probs = source.momentum.get("class_probabilities") or {}
    momentum_probs = {
        str(key): float(value)
        for key, value in momentum_probs.items()
        if _num(value) is not None
    }
    momentum_name = max(momentum_probs, key=momentum_probs.get) if momentum_probs else None
    momentum_margin = max(momentum_probs.values()) if momentum_probs else None
    band = _final_close_band(payload)
    median_path_atr = None
    if band is not None and atr_pct and atr_pct > 0:
        median_path_atr = round(abs(band[1]) / atr_pct, 3)
    patron_direction = forecast_direction(payload)
    det_direction = deterministic_direction(snapshot)
    direction_conflict_material: bool | None = None
    materiality_notes: list[str] = []

    if patron_direction in {"BULLISH", "BEARISH"} and det_direction in {"BULLISH", "BEARISH"}:
        if patron_direction != det_direction:
            material = median_path_atr is None or median_path_atr >= MATERIAL_DIRECTION_ATR
            if not material and band is not None and atr_pct and atr_pct > 0:
                # Even a small median is material when the whole 80% interval sits on
                # the opposite side of zero: the model then rules out the other sign.
                lower_atr = band[0] / atr_pct
                upper_atr = band[2] / atr_pct
                material = (patron_direction == "BEARISH" and upper_atr < 0) or (
                    patron_direction == "BULLISH" and lower_atr > 0
                )
            direction_conflict_material = material
            if material:
                magnitude = (
                    f" ({median_path_atr:.2f} ATR over {source.horizon_minutes} minutes)"
                    if median_path_atr is not None
                    else ""
                )
                conflicts.append(
                    f"PATRON's median path is {patron_direction}{magnitude} while deterministic "
                    f"market direction is {det_direction}."
                )
            else:
                materiality_notes.append(
                    f"PATRON's median path is {patron_direction} but only {median_path_atr:.2f} "
                    f"ATR from zero (materiality threshold {MATERIAL_DIRECTION_ATR:.2f} ATR); "
                    "the sign flip is not treated as a material directional conflict."
                )
    if momentum_name and det_direction in {"BULLISH", "BEARISH"}:
        momentum_direction = (
            "BULLISH" if "bullish" in momentum_name else "BEARISH" if "bearish" in momentum_name else "NEUTRAL"
        )
        if momentum_direction in {"BULLISH", "BEARISH"} and momentum_direction != det_direction:
            conflicts.append(
                f"PATRON momentum is {momentum_name} while deterministic direction is {det_direction}."
            )
    if barrier_name and det_direction in {"BULLISH", "BEARISH"}:
        expected = "tp_first" if det_direction == "BULLISH" else "sl_first"
        opposite = "sl_first" if expected == "tp_first" else "tp_first"
        if barrier_name == opposite and barrier_margin is not None and barrier_margin >= 0.50:
            conflicts.append(
                f"PATRON's dominant barrier is {barrier_name} ({barrier_margin:.0%}), "
                f"opposite to deterministic {det_direction} direction."
            )

    low: list[str] = []
    if interval_width_atr is not None:
        if interval_width_atr > WIDE_INTERVAL_ATR:
            low.append(
                f"80% close interval is {interval_width_atr:.1f} ATR wide "
                f"(threshold {WIDE_INTERVAL_ATR:.0f}), indicating an uninformative forecast."
            )
        elif interval_width_atr < NARROW_INTERVAL_ATR:
            low.append(
                f"80% close interval is only {interval_width_atr:.2f} ATR wide, "
                "which is implausibly narrow for a 90-minute horizon."
            )
    if barrier_margin is not None and barrier_margin < MIN_BARRIER_MARGIN:
        low.append(
            f"Barrier class margin is {barrier_margin:.0%} (threshold "
            f"{MIN_BARRIER_MARGIN:.0%}); the model has no clear outcome preference."
        )
    if momentum_margin is not None and momentum_margin < MIN_MOMENTUM_MARGIN:
        low.append(
            f"Momentum class margin is {momentum_margin:.0%} (threshold "
            f"{MIN_MOMENTUM_MARGIN:.0%}); the momentum head is close to uniform."
        )
    quality_warnings = source.data_quality.get("warnings") or []
    if quality_warnings:
        low.extend(str(item) for item in quality_warnings[:3])

    if invalid:
        status = ForecastAssessmentStatus.INVALID
    elif freshness is not None and freshness > STALE_AFTER_SECONDS:
        status = ForecastAssessmentStatus.STALE
        reasons.append(
            f"Forecast is {freshness / 60:.1f} minutes behind the latest closed market bar "
            f"(stale after {STALE_AFTER_SECONDS / 60:.0f} minutes)."
        )
    elif conflicts:
        status = ForecastAssessmentStatus.CONFLICTING_EVIDENCE
        reasons.extend(conflicts)
    elif low:
        status = ForecastAssessmentStatus.LOW_CONFIDENCE
        reasons.extend(low)
    else:
        status = ForecastAssessmentStatus.VALID
        reasons.append("Schema, freshness and cross-checks passed; forecast remains probabilistic.")
    # Keep materiality explanations after the primary status reason so the first reason
    # always describes the actual assessment, and Qwen still sees why a sign flip was
    # not promoted to a conflict.
    reasons.extend(materiality_notes)

    assessment = ForecastAssessment(
        status=status,
        reasons=list(dict.fromkeys(reasons)),
        conflicts=list(dict.fromkeys(conflicts)),
        usable_in_decision=status == ForecastAssessmentStatus.VALID,
        freshness_seconds=round(freshness, 1) if freshness is not None else None,
        interval_width_atr=interval_width_atr,
        barrier_margin=round(barrier_margin, 4) if barrier_margin is not None else None,
        momentum_margin=round(momentum_margin, 4) if momentum_margin is not None else None,
        forecast_direction=patron_direction,
        deterministic_direction=det_direction,
        median_path_atr=median_path_atr,
        direction_conflict_material=direction_conflict_material,
        horizon_minutes=source.horizon_minutes,
    )
    return source, assessment


def _enum_value(value: Any, default: str = "UNKNOWN") -> str:
    return str(getattr(value, "value", value if value is not None else default))


def qwen_readiness(
    ai_status: QwenMetadata,
    *,
    health_state: str | None = None,
    waited_seconds: float | None = None,
) -> QwenReadiness:
    """Map Qwen's runtime/inference state onto one explicit component state."""

    status = {
        QwenStatus.USED: "READY",
        QwenStatus.INITIALIZING: "INITIALIZING",
        QwenStatus.DISABLED: "DISABLED",
    }.get(ai_status.status, "FAILED")
    if ai_status.used:
        detail = (
            "Qwen returned a validated structured interpretation"
            f"{f' with {ai_status.model}' if ai_status.model else ''}."
        )
    elif ai_status.error:
        detail = ai_status.error
    elif status == "READY":
        detail = "Qwen is ready but no interpretation was recorded for this response."
    else:
        detail = "Qwen interpretation is not available; deterministic analysis stands."
    return QwenReadiness(
        status=status,  # type: ignore[arg-type]
        detail=detail,
        reason_code=ai_status.status.value,
        health_state=health_state or None,
        waited_seconds=round(waited_seconds, 2) if waited_seconds else None,
    )


def build_readiness(
    *,
    snapshot: Any,
    planning_result: Any,
    plan: Any,
    assessment: ForecastAssessment,
    source: ForecastSourceInfo | None,
    ai_status: QwenMetadata,
    qwen_health_state: str | None,
    qwen_wait_seconds: float | None,
    now: datetime | None = None,
) -> PipelineReadiness:
    """Describe each pipeline component independently and honestly.

    Nothing here upgrades an existing gate: a PENDING strategy stays PENDING, missing
    account inputs stay missing, and execution is always disabled.
    """

    now = now or datetime.now(UTC)
    data_as_of = getattr(snapshot, "data_as_of", None)
    data_as_of = data_as_of if isinstance(data_as_of, datetime) else None
    market_freshness = (
        round((now - data_as_of).total_seconds(), 1) if data_as_of is not None else None
    )
    is_stale = bool(getattr(snapshot, "is_stale", False))
    market = MarketReadiness(
        status="STALE" if is_stale else "READY",
        detail=(
            f"Verified {getattr(snapshot, 'symbol', 'market')} "
            f"{getattr(snapshot, 'timeframe', '')} snapshot from closed candles."
            if not is_stale
            else "The latest closed candle is older than the freshness limit; analysis is stale."
        ),
        reason_code="MARKET_STALE" if is_stale else "MARKET_READY",
        data_as_of=data_as_of,
        freshness_seconds=market_freshness,
    )

    patron_status = {
        ForecastAssessmentStatus.VALID: "AVAILABLE",
        ForecastAssessmentStatus.CONFLICTING_EVIDENCE: "CONFLICTING",
        ForecastAssessmentStatus.LOW_CONFIDENCE: "LOW_CONFIDENCE",
        ForecastAssessmentStatus.STALE: "STALE",
        ForecastAssessmentStatus.INVALID: "INVALID",
        ForecastAssessmentStatus.UNAVAILABLE: "UNAVAILABLE",
    }[assessment.status]
    patron_model = source.model_version if source is not None else "PATRON"
    patron_detail = (
        f"{patron_model} median path is {assessment.forecast_direction or 'unknown'}; "
        f"assessment {assessment.status.value} and"
        f" {'usable' if assessment.usable_in_decision else 'not usable'} for the decision."
    )
    if assessment.reasons:
        patron_detail += f" {assessment.reasons[0]}"
    patron = PatronReadiness(
        status=patron_status,  # type: ignore[arg-type]
        detail=patron_detail,
        reason_code=assessment.status.value,
        missing_inputs=[],
        assessment=assessment.status,
        usable_in_decision=assessment.usable_in_decision,
        conflicts=list(assessment.conflicts),
        freshness_seconds=assessment.freshness_seconds,
        median_path_atr=assessment.median_path_atr,
    )

    qwen = qwen_readiness(
        ai_status,
        health_state=qwen_health_state,
        waited_seconds=qwen_wait_seconds,
    )

    strategy_status = _enum_value(
        getattr(planning_result, "strategy_validation_status", "PENDING"), "PENDING"
    )
    gate_status = {"PENDING": "PENDING", "VALIDATED": "PASSED", "REJECTED": "FAILED"}.get(
        strategy_status, "PENDING"
    )
    strategy = StrategyReadiness(
        status=gate_status,  # type: ignore[arg-type]
        detail=(
            "The independent human-reviewed acceptance gate is "
            f"{gate_status}; deterministic candidates are evaluated but not validated."
            if gate_status == "PENDING"
            else f"The independent acceptance gate is {gate_status}."
        ),
        reason_code=f"STRATEGY_GATE_{gate_status}",
        reviewed_cases=None,
        required_cases=None,
    )

    if plan is not None:
        trade_plan = TradePlanReadiness(
            status="AVAILABLE",
            detail=(
                f"A review-gated {_enum_value(getattr(plan, 'direction', ''))} plan exists "
                f"with status {_enum_value(getattr(plan, 'plan_status', ''))}; it is not executable."
            ),
            plan_status=_enum_value(getattr(plan, "plan_status", "")),
        )
    else:
        reasons = list(getattr(planning_result, "rejection_reasons", None) or [])
        messages = [str(getattr(reason, "message", reason)) for reason in reasons[:3]]
        trade_plan = TradePlanReadiness(
            status="UNAVAILABLE",
            detail=(
                "No trade plan was constructed: "
                + ("; ".join(messages) if messages else "no eligible deterministic candidate.")
            ),
            reason_code=(
                _enum_value(getattr(reasons[0], "code", ""))
                if reasons
                else _enum_value(getattr(planning_result, "status", "NO_PLAN"))
            ),
            plan_status=_enum_value(getattr(planning_result, "status", "")),
        )

    risk_status = {
        "VALID": "APPROVED",
        "INVALID": "REJECTED",
        "NOT_EVALUATED": "NOT_EVALUATED",
    }.get(_enum_value(getattr(planning_result, "risk_validation_status", "UNKNOWN")), "NOT_EVALUATED")
    risk = RiskReadiness(
        status=risk_status,  # type: ignore[arg-type]
        detail=(
            "Deterministic risk checks approved the plan geometry; execution stays disabled."
            if risk_status == "APPROVED"
            else "Deterministic risk checks rejected the candidate."
            if risk_status == "REJECTED"
            else "Risk checks were not evaluated because no plan was constructed."
        ),
        reason_code=(
            None
            if risk_status == "APPROVED"
            else "RISK_REJECTED"
            if risk_status == "REJECTED"
            else "NO_PLAN_TO_ASSESS"
        ),
    )

    missing_inputs = list(
        getattr(planning_result, "missing_account_inputs", None) or MISSING_ACCOUNT_INPUTS
    )
    position_size = PositionSizeReadiness(
        status="NOT_CALCULATED",
        detail=(
            "Position size is not calculated: verified account/risk inputs are missing. "
            "No size is fabricated."
        ),
        reason_code="MISSING_ACCOUNT_INPUTS",
        missing_inputs=missing_inputs,
    )
    execution = ExecutionReadiness(
        status="DISABLED",
        detail="Order execution is disabled in this phase; no order can be placed.",
        reason_code="EXECUTION_DISABLED",
    )
    return PipelineReadiness(
        market=market,
        patron=patron,
        qwen=qwen,
        strategy=strategy,
        trade_plan=trade_plan,
        risk=risk,
        position_size=position_size,
        execution=execution,
    )


def risk_view(planning_result: Any, plan: Any) -> RiskValidationView:
    checks = [
        {"name": check.name, "passed": bool(check.passed), "detail": check.detail}
        for check in (getattr(planning_result, "checks", None) or [])
    ]
    if plan is not None:
        risk = getattr(plan, "risk_assessment", None)
        if risk is not None:
            for check in getattr(risk, "checks", None) or []:
                checks.append(
                    {
                        "name": str(getattr(check, "name", "risk_check")),
                        "passed": bool(getattr(check, "passed", False)),
                        "detail": str(getattr(check, "detail", "")),
                    }
                )
    return RiskValidationView(
        status=str(
            getattr(
                getattr(planning_result, "risk_validation_status", None),
                "value",
                getattr(planning_result, "risk_validation_status", "UNKNOWN"),
            )
        ),
        execution_eligibility=str(
            getattr(
                getattr(planning_result, "execution_eligibility", None),
                "value",
                getattr(planning_result, "execution_eligibility", "UNKNOWN"),
            )
        ),
        checks=checks,
    )


def unified_plan(plan: Any) -> UnifiedTradePlan | None:
    if plan is None:
        return None
    direction = str(getattr(plan.direction, "value", plan.direction))
    entry_zone = plan.entry_zone
    return UnifiedTradePlan(
        plan_id=str(plan.plan_id),
        strategy_id=str(getattr(plan, "strategy_id", "unknown")),
        strategy_version=str(getattr(plan, "strategy_version", "unknown")),
        direction=direction,
        plan_status=str(getattr(plan.plan_status, "value", plan.plan_status)),
        entry_zone={
            "lower": str(entry_zone.lower),
            "upper": str(entry_zone.upper),
            "anchor": str(entry_zone.anchor),
            "anchor_type": str(entry_zone.anchor_type),
        },
        suggested_entry=str(plan.suggested_entry),
        confirmation_level=str(
            entry_zone.upper if direction == "LONG" else entry_zone.lower
        ),
        stop_loss=str(plan.stop_loss),
        stop_basis=str(getattr(plan, "stop_basis", "")),
        take_profits=[
            {
                "label": str(target.label),
                "price": str(target.price),
                "risk_multiple": str(target.risk_multiple),
                "method": str(target.method),
            }
            for target in plan.take_profits
        ],
        risk_reward={
            "rr_tp1": str(plan.risk_reward.rr_tp1),
            "rr_tp2": str(plan.risk_reward.rr_tp2),
            "rr_tp3": str(plan.risk_reward.rr_tp3),
        },
        invalidation_conditions=list(plan.invalidation_conditions),
        confirmation_requirements=list(plan.confirmation_requirements),
        expires_at=plan.expires_at.isoformat(),
        risk_validation_status=str(
            getattr(plan.risk_validation_status, "value", plan.risk_validation_status)
        ),
        execution_eligibility=str(
            getattr(plan.execution_eligibility, "value", plan.execution_eligibility)
        ),
    )


def evidence_bullets(snapshot: Any, assessment: ForecastAssessment, source: ForecastSourceInfo | None) -> tuple[list[str], list[str]]:
    """Build deterministic bullish/bearish evidence, never Qwen claims."""

    bullish: list[str] = []
    bearish: list[str] = []
    trend = str(getattr(snapshot.trend.state, "value", snapshot.trend.state))
    structure = str(getattr(snapshot.structure.state, "value", snapshot.structure.state))
    momentum = str(getattr(snapshot.momentum.state, "value", snapshot.momentum.state))
    regime = str(getattr(snapshot.regime.state, "value", snapshot.regime.state))
    if "BULLISH" in trend or regime == "TRENDING_UP":
        bullish.append(f"Deterministic trend/regime is {trend}/{regime}.")
    if "BEARISH" in trend or regime == "TRENDING_DOWN":
        bearish.append(f"Deterministic trend/regime is {trend}/{regime}.")
    if structure == "UPTREND":
        bullish.append("Market structure is making higher highs and higher lows.")
    elif structure == "DOWNTREND":
        bearish.append("Market structure is making lower highs and lower lows.")
    elif structure in {"RANGING", "TRANSITION"}:
        bullish.append(f"Structure is {structure}; no directional breakout is confirmed.")
        bearish.append(f"Structure is {structure}; range edges remain the main risk.")
    if momentum == "BULLISH":
        bullish.append("Momentum state is bullish.")
    elif momentum == "BEARISH":
        bearish.append("Momentum state is bearish.")
    elif momentum == "MIXED":
        bullish.append("Momentum is mixed, so trend continuation is not confirmed.")
        bearish.append("Momentum is mixed, so downside continuation is not confirmed.")
    for event in (getattr(snapshot.structure, "events", None) or [])[-3:]:
        event_type = str(getattr(event, "type", ""))
        if "UP" in event_type:
            bullish.append(f"Structure event {event_type} at {getattr(event, 'price', 'n/a')}.")
        elif "DOWN" in event_type:
            bearish.append(f"Structure event {event_type} at {getattr(event, 'price', 'n/a')}.")
    if source is not None:
        direction = assessment.forecast_direction
        if direction == "BULLISH":
            bullish.append(
                f"PATRON median close path leans bullish; assessment {assessment.status.value}."
            )
        elif direction == "BEARISH":
            bearish.append(
                f"PATRON median close path leans bearish; assessment {assessment.status.value}."
            )
    return list(dict.fromkeys(bullish))[:6], list(dict.fromkeys(bearish))[:6]
