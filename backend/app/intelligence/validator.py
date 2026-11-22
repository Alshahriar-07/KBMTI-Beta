"""Validate model narration against deterministic authority.

A syntactically valid JSON answer is not enough. The action must equal the deterministic
decision, every evidence reference must exist, and every decimal or price-like number in
the prose must match a value supplied by the deterministic services. Any violation rejects
the whole model answer and the caller falls back to deterministic text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from app.intelligence.contracts import QwenOutput
from app.intelligence.market_contracts import MarketQwenOutput

_NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_PROHIBITED = (
    "ignore risk",
    "override risk",
    "bypass risk",
    "place order",
    "order placed",
    "position size is",
    "guaranteed profit",
    "risk-free",
    "buy now",
    "sell now",
    "increase the stop",
    "widen the stop",
)


def extract_json(text: str) -> str:
    cleaned = _FENCE.sub("", (text or "").strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("model output did not contain a JSON object")
    return cleaned[start : end + 1]


def parse_output(text: str) -> QwenOutput:
    payload = json.loads(extract_json(text))
    if not isinstance(payload, dict):
        raise ValueError("model output must be a JSON object")
    return QwenOutput.model_validate(payload)


def parse_market_output(text: str) -> MarketQwenOutput:
    payload = json.loads(extract_json(text))
    if not isinstance(payload, dict):
        raise ValueError("model output must be a JSON object")
    return MarketQwenOutput.model_validate(payload)


def _claim_errors(
    *,
    action: str,
    prose: str,
    evidence_refs: Iterable[str],
    allowed_refs: Iterable[str],
    allowed_numbers: Iterable[Decimal | int | float | str],
) -> list[str]:
    errors: list[str] = []
    refs = set(allowed_refs)
    unknown = sorted(set(evidence_refs) - refs)
    if unknown:
        errors.append(f"unknown evidence_refs: {unknown}")

    numbers: set[Decimal] = set()
    for value in allowed_numbers:
        try:
            numbers.add(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            continue
    lowered = prose.lower()
    for phrase in _PROHIBITED:
        if phrase in lowered:
            errors.append(f"prohibited instruction or claim: '{phrase}'")
    for token in _NUMBER.findall(prose):
        # Only inspect price-like decimals and large integers; prose counts such as
        # "3 targets" are not numerical market claims.
        if "." not in token and len(token.lstrip("+-")) < 4:
            continue
        try:
            value = Decimal(token.replace(",", ""))
        except InvalidOperation:
            errors.append(f"unparseable numeric claim: {token}")
            continue
        if value not in numbers:
            errors.append(f"numeric claim {token} is not present in authoritative data")
    return errors


def validate_output(
    output: QwenOutput,
    *,
    authoritative_action: str,
    allowed_refs: Iterable[str],
    allowed_numbers: Iterable[Decimal | int | float | str],
) -> list[str]:
    """Return validation notes or raise ``ValueError`` with every violation."""

    errors: list[str] = []
    if output.action.value != authoritative_action:
        errors.append(
            f"action {output.action.value} does not match deterministic action {authoritative_action}"
        )
    prose = " ".join(
        [
            output.market_context,
            output.strategy_rationale,
            output.plan_rationale,
            output.uncertainty,
            output.next_action,
        ]
        + list(output.warnings)
    )
    errors.extend(
        _claim_errors(
            action=output.action.value,
            prose=prose,
            evidence_refs=output.evidence_refs,
            allowed_refs=allowed_refs,
            allowed_numbers=allowed_numbers,
        )
    )
    if errors:
        raise ValueError("; ".join(errors))
    return [
        "schema valid",
        f"{len(output.evidence_refs)} known evidence references",
        "all numeric claims verified",
    ]


def validate_market_output(
    output: MarketQwenOutput,
    *,
    authoritative_action: str,
    allowed_refs: Iterable[str],
    allowed_numbers: Iterable[Decimal | int | float | str],
) -> list[str]:
    """Validate the unified-response narration without relaxing any rule."""

    errors: list[str] = []
    if output.action.value != authoritative_action:
        errors.append(
            f"action {output.action.value} does not match deterministic action {authoritative_action}"
        )
    prose = " ".join(
        [
            output.market_summary,
            output.forecast_interpretation,
            output.uncertainty,
            output.next_action,
        ]
        + list(output.bullish_evidence)
        + list(output.bearish_evidence)
        + list(output.missing_information)
        + list(output.warnings)
    )
    errors.extend(
        _claim_errors(
            action=output.action.value,
            prose=prose,
            evidence_refs=output.evidence_refs,
            allowed_refs=allowed_refs,
            allowed_numbers=allowed_numbers,
        )
    )
    if errors:
        raise ValueError("; ".join(errors))
    return [
        "schema valid",
        f"{len(output.evidence_refs)} known evidence references",
        "all numeric claims verified",
    ]


__all__ = [
    "extract_json",
    "parse_output",
    "parse_market_output",
    "validate_output",
    "validate_market_output",
]
