"""Trading-intelligence orchestration.

The deterministic path is always available. Qwen is optional, is given only authoritative
data, and its JSON is rejected unless it matches the deterministic action, known evidence
references and known numbers. Any failure leaves the deterministic answer intact with an
explicit warning.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.intelligence.contracts import (
    IntelligenceAction,
    IntelligenceStatus,
    KnowledgeSearchResponse,
    QwenMetadata,
    QwenStatus,
    StrategyComparison,
    TradingIntelligence,
)
from app.intelligence.knowledge import CORPUS_VERSION, KnowledgeBase
from app.intelligence.market import (
    assess_forecast,
    build_readiness,
    evidence_bullets,
    market_condition,
    qwen_readiness,
    risk_view,
    unified_plan,
)
from app.intelligence.market_contracts import (
    ForecastAssessmentStatus,
    MarketIntelligence,
)
from app.intelligence.validator import (
    parse_market_output,
    parse_output,
    validate_market_output,
    validate_output,
)
from app.intelligence.visualization import build_chart_overlay
from app.kie.contracts import Mode, RunRequest
from app.risk.contracts import StrategyValidationStatus

logger = logging.getLogger(__name__)

# Trading Intelligence waits this long for an in-flight Qwen load (measured load plus
# inference gate is ~3.3 s) instead of returning INITIALIZING on the first request.
QWEN_READY_WAIT_SECONDS = 25.0


def _now() -> datetime:
    return datetime.now(UTC)


_PROSE_NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])")


def _prose_numbers(text: str, out: set[Decimal]) -> None:
    """Allow numbers written in deterministic reason text sent to Qwen.

    Qwen may quote an explanation verbatim. Those values were computed by the
    deterministic services, so quoting them is not an invented claim. Numbers absent
    from both the structured payload and this authoritative prose are still rejected.
    """

    for token in _PROSE_NUMBER.findall(text or ""):
        try:
            out.add(Decimal(token))
        except Exception:  # noqa: BLE001 - a non-numeric token is not a claim
            continue


def _numbers(value: Any, out: set[Decimal]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float, Decimal)):
        try:
            out.add(Decimal(str(value)))
        except Exception:  # noqa: BLE001 - provenance values are best effort
            return
    elif isinstance(value, str):
        try:
            out.add(Decimal(value))
        except Exception:  # noqa: BLE001
            return
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _numbers(item, out)


def _with_ai_status(
    result: MarketIntelligence,
    status: QwenStatus,
    error: str,
    latency_ms: float | None = None,
) -> MarketIntelligence:
    warnings = list(result.warnings)
    if status is not QwenStatus.USED:
        warnings.append(error)
    return result.model_copy(
        update={
            "warnings": list(dict.fromkeys(warnings)),
            "ai_status": QwenMetadata(
                used=False,
                status=status,
                latency_ms=latency_ms,
                error=error,
            ),
        }
    )


def _decision_reason(planning_result: Any, evaluation: Any, plan: Any) -> str:
    if plan is not None:
        return (
            f"Deterministic plan {plan.plan_status.value} with execution eligibility "
            f"{plan.execution_eligibility.value}; strategy gate "
            f"{planning_result.strategy_validation_status.value}."
        )
    reasons = [reason.message for reason in planning_result.rejection_reasons]
    if not reasons:
        reasons = [reason.message for reason in evaluation.wait_reasons]
    suffix = "; ".join(reasons[:3]) if reasons else "no eligible deterministic candidate"
    return (
        f"No trade plan was constructed ({planning_result.status.value}): {suffix}. "
        "WAIT and NO_TRADE remain valid outcomes."
    )


def _fallback_interpretation(condition: Any, assessment: Any, action: str) -> str:
    return (
        f"{condition.summary} PATRON assessment is {assessment.status.value}: "
        f"{assessment.reasons[0] if assessment.reasons else 'no reason recorded.'} "
        f"Deterministic decision is {action}. Qwen interpretation is not available."
    )


def _fallback_forecast_text(source: Any, assessment: Any) -> str:
    if source is None:
        return "No PATRON source evidence is available; the deterministic market view is unchanged."
    direction = assessment.forecast_direction or "neutral"
    usable = "usable" if assessment.usable_in_decision else "not usable for the decision"
    return (
        f"PATRON {source.model_version} median path is {direction}; assessment "
        f"{assessment.status.value} and {usable}. This is source evidence, not an instruction."
    )


class IntelligenceService:
    def __init__(
        self,
        *,
        analysis: Any,
        strategies: Any,
        planning: Any,
        knowledge: KnowledgeBase | None = None,
        kie: Any | None = None,
        forecast: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        qwen_ready_wait_seconds: float = QWEN_READY_WAIT_SECONDS,
    ) -> None:
        self._analysis = analysis
        self._strategies = strategies
        self._planning = planning
        self._knowledge = knowledge or KnowledgeBase()
        self._kie = kie
        self._forecast = forecast
        self._clock = clock or _now
        self._qwen_ready_wait_seconds = max(0.0, float(qwen_ready_wait_seconds))
        self._cache: dict[str, tuple[float, TradingIntelligence]] = {}
        self._market_cache: dict[str, tuple[float, MarketIntelligence]] = {}
        self._market_lock = threading.Lock()
        self._last_error: str | None = None

    def current(self, *, use_qwen: bool = True, refresh: bool = False) -> TradingIntelligence:
        planning_result = self._planning.current(refresh=refresh)
        snapshot = self._analysis.snapshot()
        evaluation = self._strategies.evaluate(strategy_id="trend_pullback", refresh=False)
        if snapshot.snapshot_id != planning_result.market_snapshot_id:
            snapshot = self._analysis.snapshot(refresh=True)
        deterministic = self._deterministic(
            planning_result=planning_result,
            snapshot=snapshot,
            evaluation=evaluation,
        )
        cache_key = f"{deterministic.plan_id}|{use_qwen}"
        now_monotonic = time.monotonic()
        cached = self._cache.get(cache_key)
        if not refresh and cached and now_monotonic - cached[0] < 30.0:
            return cached[1]

        if use_qwen:
            self._ensure_qwen_loading()
            deterministic = self._with_qwen(deterministic, planning_result, snapshot, evaluation)
        else:
            deterministic = deterministic.model_copy(
                update={
                    "qwen": QwenMetadata(
                        used=False,
                        status=QwenStatus.DISABLED,
                        error="Qwen narration was not requested.",
                    )
                }
            )
        if deterministic.qwen.status is not QwenStatus.INITIALIZING:
            # Timestamp at write time: narration can take tens of seconds, and a
            # pre-inference timestamp would make the entry immediately stale.
            self._cache[cache_key] = (time.monotonic(), deterministic)
        return deterministic

    def _ensure_qwen_loading(self) -> None:
        """Ask KIE to warm in the background without blocking this request."""

        ensure = getattr(self._kie, "ensure_loading", None)
        if ensure is None:
            return
        try:
            ensure()
        except Exception:  # noqa: BLE001 - status remains authoritative
            logger.debug("KIE background initialization could not be started", exc_info=True)

    def _wait_for_qwen_ready(self) -> tuple[bool, float]:
        """Bounded wait for the background load; returns (ready, waited seconds)."""

        wait = getattr(self._kie, "wait_until_ready", None)
        if wait is None or self._qwen_ready_wait_seconds <= 0:
            return bool(getattr(self._kie, "ready", False)), 0.0
        started = time.perf_counter()
        try:
            ready = bool(wait(self._qwen_ready_wait_seconds))
        except Exception:  # noqa: BLE001 - deterministic output must survive
            logger.debug("Qwen readiness wait failed", exc_info=True)
            ready = bool(getattr(self._kie, "ready", False))
        return ready, time.perf_counter() - started

    def _with_qwen_readiness(
        self, result: MarketIntelligence, *, waited_seconds: float
    ) -> MarketIntelligence:
        health_state: str | None = None
        if self._kie is not None:
            try:
                health_state = str(getattr(self._kie, "health_state", "") or "") or None
            except Exception:  # noqa: BLE001 - diagnostics only
                health_state = None
        return result.model_copy(
            update={
                "readiness": result.readiness.model_copy(
                    update={
                        "qwen": qwen_readiness(
                            result.ai_status,
                            health_state=health_state,
                            waited_seconds=waited_seconds,
                        )
                    }
                )
            }
        )

    def _qwen_not_ready(self) -> tuple[QwenStatus, str]:
        state = str(getattr(self._kie, "health_state", "") or "")
        detail: str | None = None
        try:
            detail = self._kie.status().get("last_error")
        except Exception:  # noqa: BLE001 - diagnostics must never block the fallback
            detail = None
        if state == "INITIALIZING":
            return (
                QwenStatus.INITIALIZING,
                "Qwen is initializing on the AMD Vulkan backend. Deterministic interpretation returned.",
            )
        if state == "GPU_BACKEND_UNAVAILABLE":
            return (
                QwenStatus.UNAVAILABLE,
                f"Qwen GPU backend unavailable: {detail or 'Vulkan did not initialize.'}",
            )
        if state == "GPU_MEMORY_INSUFFICIENT":
            return (
                QwenStatus.UNAVAILABLE,
                f"Qwen GPU memory is insufficient: {detail or 'the model does not fit the VRAM budget.'}",
            )
        if state == "INFERENCE_FAILED":
            return (
                QwenStatus.UNAVAILABLE,
                f"Qwen inference failed: {detail or 'the readiness generation failed.'}",
            )
        if state == "MODEL_NOT_FOUND":
            return (QwenStatus.UNAVAILABLE, f"Qwen model not found: {detail or 'artifact missing.'}")
        if state == "MODEL_LOAD_FAILED":
            return (QwenStatus.UNAVAILABLE, f"Qwen model failed to load: {detail or 'runtime error.'}")
        return (
            QwenStatus.UNAVAILABLE,
            "Qwen is not initialized. Start it with POST /api/v1/kie/load.",
        )

    # -- unified, forecast-aware market intelligence -------------------------
    def market_intelligence(
        self, *, use_qwen: bool = True, refresh: bool = False
    ) -> MarketIntelligence:
        """Assemble market, PATRON evidence, deterministic risk and optional Qwen.

        The cache is keyed by the market snapshot and forecast run, so a newer bar
        can never reuse an older Qwen answer. Repeated frontend components share
        one inference result.
        """

        if use_qwen:
            self._ensure_qwen_loading()
        planning_result = self._planning.current(refresh=refresh)
        snapshot = self._analysis.snapshot(refresh=refresh)
        evaluation = self._strategies.evaluate(strategy_id="trend_pullback", refresh=False)
        if snapshot.snapshot_id != planning_result.market_snapshot_id:
            snapshot = self._analysis.snapshot(refresh=True)
        base = self._deterministic(
            planning_result=planning_result,
            snapshot=snapshot,
            evaluation=evaluation,
        )
        run = self._forecast.latest() if self._forecast is not None else None
        source, assessment = assess_forecast(run, snapshot, self._clock())
        condition = market_condition(snapshot)
        plan = planning_result.plan
        overlay = build_chart_overlay(snapshot, condition, plan)
        bullish, bearish = evidence_bullets(snapshot, assessment, source)
        decision_reason = _decision_reason(planning_result, evaluation, plan)
        warnings = list(
            dict.fromkeys(
                [
                    *base.warnings,
                    "PATRON is probabilistic source evidence; deterministic analysis and risk remain authoritative.",
                ]
            )
        )
        if assessment.status is not ForecastAssessmentStatus.VALID:
            warnings.extend(
                f"PATRON assessment {assessment.status.value}: {reason}"
                for reason in assessment.reasons[:3]
            )
        warnings = list(dict.fromkeys(warnings))
        refs = list(dict.fromkeys([*base.evidence_refs, "forecast.assessment", "forecast.source"]))
        if run and run.get("id"):
            refs.append(f"forecast:{run['id']}")
        unavailable: list[str] = ["position_size"]
        if source is None:
            unavailable.append("patron_forecast")
        if not assessment.usable_in_decision:
            unavailable.append("patron_forecast_usable_for_decision")
        if plan is None:
            unavailable.append("trade_plan")

        latest_market = snapshot.provenance.last_closed_candle_time
        data_freshness = {
            "market_as_of": latest_market.isoformat() if latest_market else None,
            "forecast_as_of": source.forecast_as_of.isoformat()
            if source and source.forecast_as_of
            else None,
            "forecast_age_seconds": assessment.freshness_seconds,
            "market_age_seconds": round((self._clock() - latest_market).total_seconds(), 1)
            if latest_market
            else None,
            "market_is_stale": snapshot.is_stale,
            "forecast_is_stale": assessment.status is ForecastAssessmentStatus.STALE,
            "bar_seconds": 900,
        }
        model_versions = {
            "market_feature": snapshot.feature_version,
            "strategy": evaluation.strategy_version,
            "strategy_config": evaluation.config_version,
            "plan": plan.plan_version if plan is not None else None,
            "risk_policy": plan.risk_policy_version if plan is not None else None,
            "patron": source.model_version if source is not None else None,
            "patron_feature": source.feature_version if source is not None else None,
            "qwen": None,
        }
        if not use_qwen:
            initial_ai_status = QwenMetadata(
                used=False,
                status=QwenStatus.DISABLED,
                error="Qwen narration was not requested.",
            )
        elif self._kie is None:
            initial_ai_status = QwenMetadata(
                used=False,
                status=QwenStatus.UNAVAILABLE,
                error="The embedded Qwen runtime is not configured.",
            )
        elif not getattr(self._kie, "enabled", False):
            initial_ai_status = QwenMetadata(
                used=False,
                status=QwenStatus.DISABLED,
                error="Qwen is disabled by configuration.",
            )
        elif getattr(self._kie, "ready", False):
            initial_ai_status = QwenMetadata(used=False, status=QwenStatus.UNAVAILABLE)
        else:
            qwen_status, message = self._qwen_not_ready()
            initial_ai_status = QwenMetadata(
                used=False, status=qwen_status, error=message
            )
        readiness = build_readiness(
            snapshot=snapshot,
            planning_result=planning_result,
            plan=plan,
            assessment=assessment,
            source=source,
            ai_status=initial_ai_status,
            qwen_health_state=str(getattr(self._kie, "health_state", "") or "") or None
            if self._kie is not None
            else None,
            qwen_wait_seconds=None,
            now=self._clock(),
        )
        result = MarketIntelligence(
            request_id=planning_result.request_id,
            generated_at=self._clock(),
            data_as_of=snapshot.data_as_of,
            is_stale=snapshot.is_stale,
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            chart_overlay=overlay,
            market_snapshot={
                "provider": snapshot.provider,
                "last_price": snapshot.last_price,
                "atr14": snapshot.volatility.atr14,
                "atr_percent": snapshot.volatility.atr_percent,
                "ema9": snapshot.trend.ema9,
                "ema21": snapshot.trend.ema21,
                "ema50": snapshot.trend.ema50,
                "rsi14": snapshot.momentum.rsi14,
                "macd": snapshot.momentum.macd,
                "macd_histogram": snapshot.momentum.macd_histogram,
                "validation": snapshot.validation.model_dump(mode="json"),
                "provenance": snapshot.provenance.model_dump(mode="json"),
            },
            market_condition=condition,
            forecast_source=source,
            forecast_assessment=assessment,
            ai_market_interpretation=_fallback_interpretation(condition, assessment, base.action.value),
            ai_forecast_interpretation=_fallback_forecast_text(source, assessment),
            bullish_evidence=bullish,
            bearish_evidence=bearish,
            strategy_candidates=base.strategy_comparison,
            readiness=readiness,
            decision=base.action,
            decision_reason=decision_reason,
            trade_plan=unified_plan(plan),
            risk_validation=risk_view(planning_result, plan),
            invalidation_conditions=list(plan.invalidation_conditions) if plan is not None else [],
            data_freshness=data_freshness,
            model_versions=model_versions,
            evidence_refs=refs,
            warnings=warnings,
            unavailable_fields=list(dict.fromkeys(unavailable)),
            ai_status=initial_ai_status,
        )

        key = "|".join(
            [
                snapshot.snapshot_id,
                evaluation.evaluation_id,
                base.plan_id or "no-plan",
                str(run.get("id")) if run else "no-forecast",
                str(use_qwen),
            ]
        )
        now_monotonic = time.monotonic()
        cached = self._market_cache.get(key)
        if not refresh and cached and now_monotonic - cached[0] < 45.0:
            return cached[1]
        if not use_qwen:
            self._market_cache[key] = (time.monotonic(), result)
            return result
        waited_seconds = 0.0
        if (
            self._kie is not None
            and getattr(self._kie, "enabled", False)
            and not getattr(self._kie, "ready", False)
        ):
            # The first request after startup waits for the real inference gate instead
            # of reporting INITIALIZING while the worker is already warming the model.
            _, waited_seconds = self._wait_for_qwen_ready()
        with self._market_lock:
            # Another request may have completed the same inference while waiting.
            cached = self._market_cache.get(key)
            if not refresh and cached and time.monotonic() - cached[0] < 45.0:
                return cached[1]
            if self._kie is None:
                updated = _with_ai_status(
                    result,
                    QwenStatus.UNAVAILABLE,
                    "The embedded Qwen runtime is not configured.",
                )
            elif not getattr(self._kie, "enabled", False):
                updated = _with_ai_status(
                    result, QwenStatus.DISABLED, "Qwen is disabled by configuration."
                )
            elif not getattr(self._kie, "ready", False):
                qwen_status, message = self._qwen_not_ready()
                updated = _with_ai_status(result, qwen_status, message)
            else:
                updated = self._market_with_qwen(
                    result,
                    base=base,
                    snapshot=snapshot,
                    evaluation=evaluation,
                    planning_result=planning_result,
                    source=source,
                    assessment=assessment,
                    condition=condition,
                    run=run,
                )
            updated = self._with_qwen_readiness(updated, waited_seconds=waited_seconds)
            if updated.ai_status.status is not QwenStatus.INITIALIZING:
                # Timestamp at write time: a 44 s inference plus a pre-inference
                # timestamp would evict the entry before the next poll reads it.
                self._market_cache[key] = (time.monotonic(), updated)
            return updated

    def _market_with_qwen(
        self,
        result: MarketIntelligence,
        *,
        base: TradingIntelligence,
        snapshot: Any,
        evaluation: Any,
        planning_result: Any,
        source: Any,
        assessment: Any,
        condition: Any,
        run: dict[str, Any] | None,
    ) -> MarketIntelligence:
        # Keep the prompt under the embedded 3072-token budget. Full service dumps
        # contain scores/checks that Qwen does not need; the validator still sees
        # every authoritative number from the complete base object below.
        assessment_payload = assessment.model_dump(mode="json")
        assessment_payload["reasons"] = assessment_payload.get("reasons", [])[:4]
        assessment_payload["conflicts"] = assessment_payload.get("conflicts", [])[:4]
        payload = {
            "authoritative_action": result.decision.value,
            "decision_reason": result.decision_reason,
            "strategy_validation_status": result.strategy_candidates[0].validation_status
            if result.strategy_candidates
            else "PENDING",
            "market_snapshot": result.market_snapshot,
            "market_condition": condition.model_dump(mode="json"),
            "recent_ohlcv": [
                {
                    "time": int(getattr(candle, "time", 0)),
                    "open": getattr(candle, "open", None),
                    "high": getattr(candle, "high", None),
                    "low": getattr(candle, "low", None),
                    "close": getattr(candle, "close", None),
                    "volume": getattr(candle, "real_volume", None),
                }
                for candle in (
                    self._analysis.recent_candles(6)
                    if hasattr(self._analysis, "recent_candles")
                    else []
                )
            ],
            "patron_source": {
                "model_id": source.model_id,
                "model_version": source.model_version,
                "feature_version": source.feature_version,
                "checkpoint_sha256": source.checkpoint_sha256,
                "source_hash": source.source_hash,
                "forecast_as_of": source.forecast_as_of.isoformat()
                if source.forecast_as_of
                else None,
                "input_last_bar_at": source.input_last_bar_at.isoformat()
                if source.input_last_bar_at
                else None,
                "horizon_minutes": source.horizon_minutes,
                "reference_close": source.reference_close,
                "range_quantiles": source.range_quantiles,
                "barrier_probabilities": source.barrier_probabilities,
                "momentum": source.momentum,
                "data_quality": source.data_quality,
                "freshness_seconds": source.freshness_seconds,
            }
            if source is not None
            else None,
            "forecast_assessment": assessment_payload,
            "strategy": {
                "strategy_id": evaluation.strategy_id,
                "strategy_version": evaluation.strategy_version,
                "decision": evaluation.decision.value,
                "direction": evaluation.direction.value,
                "quality_score": evaluation.quality.score,
                "quality_label": evaluation.quality.label.value,
                "confirmation": evaluation.confirmation_status.value,
                "wait_reasons": [item.message for item in evaluation.wait_reasons[:2]],
                "rejection_reasons": [item.message for item in evaluation.rejection_reasons[:2]],
            },
            "strategy_candidates": [
                {
                    "strategy_id": item.strategy_id,
                    "decision": item.decision,
                    "quality_score": item.quality_score,
                    "validation_status": item.validation_status,
                    "eligible": item.eligible,
                }
                for item in result.strategy_candidates
            ],
            "trade_plan": result.trade_plan.model_dump(mode="json")
            if result.trade_plan
            else None,
            "risk_validation": {
                **result.risk_validation.model_dump(mode="json"),
                "checks": result.risk_validation.checks[:6],
            },
            "bullish_evidence": result.bullish_evidence,
            "bearish_evidence": result.bearish_evidence,
            "allowed_evidence_refs": result.evidence_refs,
        }
        prompt = (
            "Return ONE JSON object only with exactly these keys: action, market_summary, "
            "forecast_interpretation, bullish_evidence, bearish_evidence, uncertainty, "
            "missing_information, next_action, evidence_refs, warnings.\n"
            "Types are strict: action is a string; market_summary, forecast_interpretation, "
            "uncertainty and next_action are strings; the remaining four are ARRAYS of strings. "
            "Write [] for an empty array, never the string \"none\".\n"
            f"action MUST equal \"{result.decision.value}\". "
            "The forecast_assessment status and usable_in_decision are authoritative: explain "
            "them, never change them and never claim the forecast is better than its status. "
            "Do not invent numbers, confidence scores, prices, entries, stops, targets or sizes. "
            "Use only numbers and evidence refs present in AUTHORITATIVE. Evidence refs must be "
            "copied from allowed_evidence_refs. Do not recommend buying, selling or executing; "
            "the strategy gate is PENDING. Explain bullish and bearish evidence, any "
            "inconsistency between PATRON and the deterministic market, and missing information. "
            "next_action must be a complete instruction sentence, not a single word. "
            "Keep every string under 45 words and the whole JSON under 320 words.\n"
            'Example shape: {"action":"WAIT","market_summary":"...",'
            '"forecast_interpretation":"...","bullish_evidence":[],"bearish_evidence":[],'
            '"uncertainty":"...","missing_information":[],"next_action":"...",'
            '"evidence_refs":["forecast.assessment"],"warnings":[]}\nAUTHORITATIVE:\n'
        )
        # Never cut JSON mid-object: drop optional sections until the payload fits.
        for optional in ("recent_ohlcv", "strategy_candidates", "trade_plan", "risk_validation"):
            if len(
                json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
            ) <= 8500:
                break
            payload.pop(optional, None)
        prompt += json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        )
        started = time.perf_counter()
        responded = False
        try:
            response = self._kie.chat(
                RunRequest(
                    messages=_messages(prompt),
                    mode=Mode.FAST,
                    max_tokens=800,
                    temperature=0.0,
                    top_p=0.9,
                )
            )
            responded = True
            parsed = parse_market_output(str(response.get("text") or ""))
            allowed_numbers: set[Decimal] = set()
            _numbers(payload, allowed_numbers)
            _numbers(base.model_dump(mode="json"), allowed_numbers)
            for text in (
                *assessment_payload.get("reasons", []),
                *assessment_payload.get("conflicts", []),
            ):
                _prose_numbers(str(text), allowed_numbers)
            notes = validate_market_output(
                parsed,
                authoritative_action=result.decision.value,
                allowed_refs=set(result.evidence_refs),
                allowed_numbers=allowed_numbers,
            )
            model = self._model_label()
            return result.model_copy(
                update={
                    "ai_market_interpretation": parsed.market_summary,
                    "ai_forecast_interpretation": parsed.forecast_interpretation,
                    "bullish_evidence": list(
                        dict.fromkeys([*result.bullish_evidence, *parsed.bullish_evidence])
                    )[:10],
                    "bearish_evidence": list(
                        dict.fromkeys([*result.bearish_evidence, *parsed.bearish_evidence])
                    )[:10],
                    "unavailable_fields": list(
                        dict.fromkeys(
                            [*result.unavailable_fields, *parsed.missing_information]
                        )
                    ),
                    "warnings": list(dict.fromkeys([*result.warnings, *parsed.warnings])),
                    "ai_status": QwenMetadata(
                        used=True,
                        status=QwenStatus.USED,
                        model=model,
                        run_id=response.get("run_id"),
                        latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
                        validation_notes=notes,
                    ),
                    "model_versions": {
                        **result.model_versions,
                        "qwen": model or "Qwen3-4B",
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001 - never break the deterministic response
            self._last_error = str(exc)
            logger.warning("Unified Qwen narration rejected or failed: %s", exc)
            status = QwenStatus.INVALID if responded else QwenStatus.UNAVAILABLE
            if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                status = QwenStatus.TIMEOUT
            return _with_ai_status(
                result,
                status,
                f"Qwen narration was rejected or unavailable ({exc}); deterministic interpretation returned.",
                latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            )

    def _model_label(self) -> str | None:
        if self._kie is None:
            return None
        try:
            status = self._kie.status()
            identity = status.get("identity") or {}
            artifacts = status.get("artifacts") or {}
            model_info = artifacts.get("model") or {}
            file_name = model_info.get("file") or "Qwen3-4B"
            quant = model_info.get("quant")
            runtime = identity.get("runtime_tag")
            model = identity.get("description") or f"{file_name}{f' ({quant})' if quant else ''}"
            if runtime and not identity.get("description"):
                model = f"{model} · llama.cpp {runtime}"
            return str(model)
        except Exception:  # noqa: BLE001
            return None

    def status(self) -> IntelligenceStatus:
        model = None
        enabled = False
        ready = False
        if self._kie is not None:
            enabled = bool(getattr(self._kie, "config", None) and self._kie.config.enabled)
            ready = bool(getattr(self._kie, "ready", False))
            try:
                status = self._kie.status()
                model = status.get("model_name") or (status.get("identity") or {}).get("description")
                if not model and isinstance(status.get("model"), dict):
                    model = status["model"].get("description")
            except Exception:  # noqa: BLE001 - status must never block
                model = None
        return IntelligenceStatus(
            enabled=True,
            deterministic_available=True,
            qwen_enabled=enabled,
            qwen_ready=ready,
            qwen_model=str(model) if model else None,
            knowledge_documents=self._knowledge.document_count,
            knowledge_version=CORPUS_VERSION,
            strategy_validation_status=StrategyValidationStatus.PENDING.value,
            generated_at=self._clock(),
            notes=[
                "Qwen can only narrate validated deterministic data; it cannot change action or risk.",
                "Strategy gate is PENDING; all plans remain review-gated and non-executable.",
            ],
        )

    def search_knowledge(self, query: str, limit: int = 4) -> KnowledgeSearchResponse:
        return self._knowledge.search(query, limit=limit)

    # -- deterministic authority -------------------------------------------
    def _deterministic(self, *, planning_result: Any, snapshot: Any, evaluation: Any) -> TradingIntelligence:
        plan = planning_result.plan
        if plan is not None:
            action = IntelligenceAction(plan.direction)
            plan_status = plan.plan_status.value
            eligibility = plan.execution_eligibility.value
            plan_explanation = (
                f"Hypothetical {plan.direction} geometry: entry zone "
                f"{plan.entry_zone.lower} to {plan.entry_zone.upper}, suggested entry "
                f"{plan.suggested_entry}, structural stop {plan.stop_loss} ({plan.stop_basis}). "
                f"TP1/TP2/TP3 are {plan.take_profits[0].price}, {plan.take_profits[1].price} and "
                f"{plan.take_profits[2].price}; R:R is {plan.risk_reward.rr_tp1}, "
                f"{plan.risk_reward.rr_tp2} and {plan.risk_reward.rr_tp3}. "
                f"Invalidation: {' '.join(plan.invalidation_conditions)} "
                "No order exists and no fill price is recorded."
            )
            next_action = (
                "Human review is required because the strategy gate is PENDING. "
                "No execution is permitted."
                if plan_status == "PLAN_REVIEW_REQUIRED"
                else "Do not execute; the plan is not ready."
            )
        else:
            action = IntelligenceAction(evaluation.decision.value)
            plan_status = planning_result.status.value
            eligibility = planning_result.execution_eligibility.value
            reasons = "; ".join(reason.message for reason in planning_result.rejection_reasons)
            plan_explanation = (
                f"No trade plan was constructed. Deterministic status {plan_status}"
                f"{': ' + reasons if reasons else '.'} WAIT and NO_TRADE are valid outcomes."
            )
            next_action = (
                "Wait for a new closed M15 bar and a confirmed candidate."
                if action is IntelligenceAction.WAIT
                else "No action. Re-evaluate only after new closed-candle evidence."
            )

        market = (
            f"Regime {snapshot.regime.state.value}; trend {snapshot.trend.state.value} "
            f"({snapshot.trend.strength.value}), structure {snapshot.structure.state.value}, "
            f"momentum {snapshot.momentum.state.value}, volatility {snapshot.volatility.state.value}. "
            f"Last price {snapshot.last_price}; ATR14 {snapshot.volatility.atr14}; "
            f"EMA21 {snapshot.trend.ema21}. "
            f"Structure evidence: {', '.join(snapshot.structure.evidence[:4]) or 'unavailable'}. "
            f"Warnings: {', '.join(snapshot.warnings[:3]) or 'none'}."
        )
        strategy = StrategyComparison(
            strategy_id=evaluation.strategy_id,
            strategy_version=evaluation.strategy_version,
            decision=evaluation.decision.value,
            quality_score=evaluation.quality.score,
            quality_label=evaluation.quality.label.value,
            validation_status=planning_result.strategy_validation_status.value,
            eligible=planning_result.execution_eligibility.value == "REVIEW_REQUIRED",
            reason=(
                "Deterministic checklist quality, not a probability. The independent 60-case "
                "gate is PENDING, so the candidate cannot be treated as validated."
            ),
        )
        uncertainty = (
            "The strategy gate is PENDING with no independent review. The plan is deterministic "
            "geometry, not a validated edge; targets are projections. "
            f"Market data is {planning_result.data_as_of.isoformat()} and stale={snapshot.is_stale}. "
            "Position size is NOT_CALCULATED because verified account inputs are unavailable."
        )
        query = (
            f"{snapshot.regime.state.value} {snapshot.trend.state.value} "
            f"{snapshot.structure.state.value} {snapshot.momentum.state.value} "
            "risk invalidation pullback"
        )
        hits = self._knowledge.search(query, limit=3).hits
        evidence_refs = [
            f"snapshot:{snapshot.snapshot_id}",
            f"evaluation:{evaluation.evaluation_id}",
            "trend.state",
            "structure.events",
            "volatility.atr14",
        ]
        if plan is not None:
            evidence_refs.extend([f"plan:{plan.plan_id}", "risk.checks", "plan.geometry"])
        for hit in hits:
            evidence_refs.extend(hit.refs)
        warnings = list(dict.fromkeys([*snapshot.warnings, *evaluation.warnings, *planning_result.warnings]))
        if plan is not None:
            warnings.extend(plan.warnings)
        warnings = list(dict.fromkeys(warnings))
        warnings.append(
            "Qwen does not override deterministic risk. The strategy gate is PENDING and execution is disabled."
        )
        return TradingIntelligence(
            request_id=planning_result.request_id,
            generated_at=self._clock(),
            data_as_of=snapshot.data_as_of,
            is_stale=snapshot.is_stale,
            snapshot_id=snapshot.snapshot_id,
            strategy_evaluation_id=evaluation.evaluation_id,
            plan_id=plan.plan_id if plan is not None else None,
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            action=action,
            plan_status=plan_status,
            execution_eligibility=eligibility,
            strategy_validation_status=planning_result.strategy_validation_status.value,
            market_explanation=market,
            strategy_comparison=[strategy],
            plan_explanation=plan_explanation,
            uncertainty=uncertainty,
            next_action=next_action,
            evidence_refs=evidence_refs,
            knowledge_refs=[ref for hit in hits for ref in hit.refs],
            knowledge=hits,
            warnings=warnings,
            qwen=QwenMetadata(used=False, status=QwenStatus.UNAVAILABLE, error="Qwen was not attempted."),
        )

    # -- optional Qwen narration -------------------------------------------
    def _with_qwen(self, base: TradingIntelligence, planning_result: Any, snapshot: Any, evaluation: Any) -> TradingIntelligence:
        if self._kie is None:
            return base.model_copy(
                update={
                    "qwen": QwenMetadata(
                        used=False,
                        status=QwenStatus.UNAVAILABLE,
                        error="The embedded Qwen runtime is not configured.",
                    )
                }
            )
        if not getattr(self._kie, "enabled", False):
            return base.model_copy(
                update={
                    "qwen": QwenMetadata(
                        used=False, status=QwenStatus.DISABLED, error="Qwen is disabled by configuration."
                    )
                }
            )
        if not getattr(self._kie, "ready", False):
            qwen_status, message = self._qwen_not_ready()
            return base.model_copy(
                update={
                    "qwen": QwenMetadata(
                        used=False,
                        status=qwen_status,
                        error=message,
                    )
                }
            )
        prompt = self._prompt(base, planning_result, snapshot, evaluation)
        started = time.perf_counter()
        responded = False
        try:
            result = self._kie.chat(
                RunRequest(messages=_messages(prompt), mode=Mode.FAST, max_tokens=700, temperature=0.0, top_p=0.9)
            )
            responded = True
            text = str(result.get("text") or "")
            parsed = parse_output(text)
            allowed_refs = set(base.evidence_refs) | {f"snapshot:{snapshot.snapshot_id}"}
            allowed_numbers: set[Decimal] = set()
            _numbers(planning_result.model_dump(mode="json"), allowed_numbers)
            _numbers(snapshot.model_dump(mode="json"), allowed_numbers)
            _numbers(evaluation.model_dump(mode="json"), allowed_numbers)
            notes = validate_output(
                parsed,
                authoritative_action=base.action.value,
                allowed_refs=allowed_refs,
                allowed_numbers=allowed_numbers,
            )
            model = None
            try:
                status = self._kie.status()
                identity = status.get("identity") or {}
                artifacts = status.get("artifacts") or {}
                model_info = artifacts.get("model") or {}
                file_name = model_info.get("file") or "Qwen3-4B"
                quant = model_info.get("quant")
                runtime = identity.get("runtime_tag")
                model = identity.get("description") or f"{file_name}{f' ({quant})' if quant else ''}"
                if runtime and not identity.get("description"):
                    model = f"{model} · llama.cpp {runtime}"
            except Exception:  # noqa: BLE001
                model = None
            return base.model_copy(
                update={
                    "market_explanation": parsed.market_context,
                    "plan_explanation": parsed.plan_rationale,
                    "uncertainty": parsed.uncertainty,
                    "next_action": parsed.next_action,
                    "warnings": list(dict.fromkeys([*base.warnings, *parsed.warnings])),
                    "qwen": QwenMetadata(
                        used=True,
                        status=QwenStatus.USED,
                        model=str(model) if model else None,
                        run_id=result.get("run_id"),
                        latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
                        validation_notes=notes,
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - model failure must degrade, never break
            self._last_error = str(exc)
            logger.warning("Qwen narration rejected or failed: %s", exc)
            status = QwenStatus.INVALID if responded else QwenStatus.UNAVAILABLE
            return base.model_copy(
                update={
                    "warnings": [
                        *base.warnings,
                        f"Qwen narration was rejected or unavailable ({exc}); deterministic explanation returned.",
                    ],
                    "qwen": QwenMetadata(
                        used=False,
                        status=status,
                        latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
                        error=str(exc),
                    ),
                }
            )

    def _prompt(self, base: TradingIntelligence, planning_result: Any, snapshot: Any, evaluation: Any) -> str:
        plan = planning_result.plan
        payload = {
            "authoritative_action": base.action.value,
            "plan_status": base.plan_status,
            "execution_eligibility": base.execution_eligibility,
            "strategy_validation_status": base.strategy_validation_status,
            "market": {
                "symbol": snapshot.symbol,
                "timeframe": snapshot.timeframe,
                "last_price": snapshot.last_price,
                "regime": snapshot.regime.state.value,
                "trend": snapshot.trend.state.value,
                "structure": snapshot.structure.state.value,
                "momentum": snapshot.momentum.state.value,
                "volatility": snapshot.volatility.state.value,
                "atr14": snapshot.volatility.atr14,
                "ema21": snapshot.trend.ema21,
                "stale": snapshot.is_stale,
                "data_as_of": snapshot.data_as_of.isoformat(),
            },
            "strategy": {
                "strategy_id": evaluation.strategy_id,
                "strategy_version": evaluation.strategy_version,
                "decision": evaluation.decision.value,
                "direction": evaluation.direction.value,
                "quality_score": evaluation.quality.score,
                "quality_label": evaluation.quality.label.value,
                "confirmation": evaluation.confirmation_status.value,
                "wait_reasons": [item.message for item in evaluation.wait_reasons[:3]],
                "rejection_reasons": [item.message for item in evaluation.rejection_reasons[:3]],
            },
            "plan": None
            if plan is None
            else {
                "plan_id": plan.plan_id,
                "status": plan.plan_status.value,
                "eligibility": plan.execution_eligibility.value,
                "entry_zone": [str(plan.entry_zone.lower), str(plan.entry_zone.upper)],
                "suggested_entry": str(plan.suggested_entry),
                "stop": str(plan.stop_loss),
                "targets": [str(target.price) for target in plan.take_profits],
                "rr": [str(plan.risk_reward.rr_tp1), str(plan.risk_reward.rr_tp2), str(plan.risk_reward.rr_tp3)],
                "invalidation": plan.invalidation_conditions,
                "position_size": None,
                "position_size_status": "NOT_CALCULATED",
            },
            "allowed_evidence_refs": base.evidence_refs,
            "knowledge_titles": [hit.title for hit in base.knowledge],
        }
        return (
            "Return ONE JSON object only, with exactly these keys: action, market_context, "
            "strategy_rationale, plan_rationale, uncertainty, next_action, evidence_refs, warnings.\n"
            "Types are strict: action is a string; the next five fields are strings; "
            "evidence_refs is an ARRAY of strings; warnings is an ARRAY of strings. "
            "If there are no warnings write []; never write the string \"none\". "
            f"action MUST be \"{base.action.value}\". Use only numbers and evidence refs present in "
            "AUTHORITATIVE. Do not recommend buying, selling, position sizing or changing a stop. "
            "Explain uncertainty and the PENDING strategy gate. Evidence refs must be copied from "
            "allowed_evidence_refs. No markdown, no prose outside the object. "
            "market_context must explicitly state the snapshot momentum and volatility values; "
            "never describe momentum as bullish when the snapshot says BEARISH. "
            "Do not repeat the raw price levels; explain their meaning. "
            "Keep every string field under 45 words and the whole JSON under 300 words.\n"
            'Example shape: {"action":"WAIT","market_context":"...","strategy_rationale":"...",'
            '"plan_rationale":"...","uncertainty":"...","next_action":"...",'
            '"evidence_refs":["snapshot:..."],"warnings":[]}\nAUTHORITATIVE:\n'
            + json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)[:12000]
        )


def _messages(prompt: str) -> tuple[Any, ...]:
    from app.kie.contracts import Message

    return (Message(role="user", content=prompt),)


__all__ = ["IntelligenceService"]
