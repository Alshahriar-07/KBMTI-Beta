"""Validate model narration against deterministic authority.

A syntactically valid JSON answer is not enough. The action must equal the deterministic
decision, every evidence reference must exist, and every decimal or price-like number in
the prose must match a value supplied by the planner/snapshot. Any violation rejects the
whole model answer and the caller falls back to the deterministic explanation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from app.intelligence.contracts import QwenOutput

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


def validate_output(
    output: QwenOutput,
    *,
    authoritative_action: str,
    allowed_refs: Iterable[str],
    allowed_numbers: Iterable[Decimal | int | float | str],
) -> list[str]:
    """Return validation notes or raise ``ValueError`` with every violation."""

    errors: list[str] = []
    notes: list[str] = []
    if output.action.value != authoritative_action:
        errors.append(
            f"action {output.action.value} does not match deterministic action {authoritative_action}"
        )
    refs = set(allowed_refs)
    unknown = sorted(set(output.evidence_refs) - refs)
    if unknown:
        errors.append(f"unknown evidence_refs: {unknown}")

    numbers: set[Decimal] = set()
    for value in allowed_numbers:
        try:
            numbers.add(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            continue
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
    if errors:
        raise ValueError("; ".join(errors))
    notes.append("schema valid")
    notes.append(f"{len(output.evidence_refs)} known evidence references")
    notes.append("all numeric claims verified")
    return notes


__all__ = ["extract_json", "parse_output", "validate_output"]
