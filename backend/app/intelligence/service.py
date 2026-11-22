"""Trading-intelligence orchestration.

The deterministic path is always available. Qwen is optional, is given only authoritative
data, and its JSON is rejected unless it matches the deterministic action, known evidence
references and known numbers. Any failure leaves the deterministic answer intact with an
explicit warning.
"""

from __future__ import annotations

import json
import logging
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
from app.intelligence.validator import parse_output, validate_output
from app.kie.contracts import Mode, RunRequest
from app.risk.contracts import StrategyValidationStatus

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


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


class IntelligenceService:
    def __init__(
        self,
        *,
        analysis: Any,
        strategies: Any,
        planning: Any,
        knowledge: KnowledgeBase | None = None,
        kie: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._analysis = analysis
        self._strategies = strategies
        self._planning = planning
        self._knowledge = knowledge or KnowledgeBase()
        self._kie = kie
        self._clock = clock or _now
        self._cache: dict[str, tuple[float, TradingIntelligence]] = {}
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
        self._cache[cache_key] = (now_monotonic, deterministic)
        return deterministic

    def status(self) -> IntelligenceStatus:
        model = None
        enabled = False
        ready = False
        if self._kie is not None:
            enabled = bool(getattr(self._kie, "config", None) and self._kie.config.enabled)
            ready = bool(getattr(self._kie, "ready", False))
            try:
                status = self._kie.status()
                model = (status.get("identity") or {}).get("description") or status.get("model")
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
            return base.model_copy(
                update={
                    "qwen": QwenMetadata(
                        used=False,
                        status=QwenStatus.UNAVAILABLE,
                        error="The Qwen model is not loaded. Deterministic explanation returned.",
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
