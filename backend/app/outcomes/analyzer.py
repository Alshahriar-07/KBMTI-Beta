"""Outcome classification from journal evidence.

The analyzer separates *what happened* from *why it happened*. A losing trade is not
automatically a strategy or model failure; an unexplained loss is reported as
unexplained. Every finding carries a confidence label and evidence references.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.outcomes.metrics import excursion_r, net_r_multiple
from app.trade_journal.contracts import (
    FailureFinding,
    OutcomeCategory,
    TradeMode,
    TradeOutcome,
    TradeStatus,
)


def _decimal_or_none(value: Any) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def _event_types(events: Iterable[Mapping[str, Any]]) -> set[str]:
    return {str(event.get("event_type")) for event in events}


def analyze_outcome(
    *,
    trade: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]] = (),
    candles: Iterable[Mapping[str, Any]] = (),
    patron_alignment: Mapping[str, Any] | None = None,
) -> TradeOutcome:
    """Classify one journal record and compute its metrics from recorded data."""

    event_rows = list(events)
    candle_rows = list(candles)
    types = _event_types(event_rows)
    refs = [str(event.get("event_id")) for event in event_rows if event.get("event_id")]
    direction = str(trade["direction"]).upper()
    entry = _decimal_or_none(trade.get("actual_entry")) or _decimal_or_none(trade.get("planned_entry"))
    stop = _decimal_or_none(trade.get("stop_loss"))
    exit_price = _decimal_or_none(trade.get("exit_price"))
    status = str(trade.get("status"))
    findings: list[FailureFinding] = []

    if "INVALIDATED" in types:
        findings.append(
            FailureFinding(
                code="SETUP_INVALIDATED",
                message="The recorded setup was invalidated before a successful close.",
                confidence="confirmed",
                evidence_refs=refs,
            )
        )
    if "STOP_HIT" in types:
        findings.append(
            FailureFinding(
                code="STOP_LOSS_HIT",
                message="Price reached the recorded stop level.",
                confidence="confirmed",
                evidence_refs=refs,
            )
        )
    if "TP_HIT" in types:
        findings.append(
            FailureFinding(
                code="TARGET_REACHED",
                message="A recorded take-profit event was reached.",
                confidence="confirmed",
                evidence_refs=refs,
            )
        )
    if patron_alignment is None:
        findings.append(
            FailureFinding(
                code="PATRON_EVIDENCE_UNAVAILABLE",
                message="No stored PATRON forecast preceded this record; alignment is marked insufficient data.",
                confidence="unknown",
                evidence_refs=[],
            )
        )
    elif int(patron_alignment.get("evaluated_steps") or 0) == 0:
        findings.append(
            FailureFinding(
                code="PATRON_EVIDENCE_INSUFFICIENT",
                message="The stored PATRON forecast has not matured into evaluated steps.",
                confidence="unknown",
                evidence_refs=[str(patron_alignment.get("forecast_id") or "")],
            )
        )
    else:
        predicted = str(patron_alignment.get("predicted_direction") or "").upper()
        if predicted and predicted != direction:
            findings.append(
                FailureFinding(
                    code="PATRON_FORECAST_CONFLICT",
                    message=(
                        "The preceding PATRON forecast direction opposed the record. This is a "
                        "probable context signal, not proof of causation."
                    ),
                    confidence="probable",
                    evidence_refs=[str(patron_alignment.get("forecast_id") or "")],
                )
            )

    if status == str(TradeStatus.EXPIRED) or "INVALIDATED" in types:
        return TradeOutcome(
            trade_id=str(trade["trade_id"]),
            category=OutcomeCategory.INVALID_SETUP,
            findings=findings,
            evidence_refs=refs,
        )
    if str(trade.get("mode")) == str(TradeMode.MANUAL) and entry is None:
        return TradeOutcome(
            trade_id=str(trade["trade_id"]),
            category=OutcomeCategory.EXECUTION_ERROR,
            findings=[
                *findings,
                FailureFinding(
                    code="MISSING_ACTUAL_ENTRY",
                    message="A manual record has no actual entry; result cannot be computed.",
                    confidence="confirmed",
                    evidence_refs=refs,
                ),
            ],
            evidence_refs=refs,
        )
    if entry is None or stop is None or exit_price is None or status != str(TradeStatus.CLOSED):
        return TradeOutcome(
            trade_id=str(trade["trade_id"]),
            category=OutcomeCategory.INSUFFICIENT_DATA,
            findings=findings,
            evidence_refs=refs,
        )

    net_r, gross_r, costs_r = net_r_multiple(
        direction=direction,
        entry=entry,
        stop=stop,
        exit_price=exit_price,
        fees=_decimal_or_none(trade.get("fees")) or Decimal("0"),
        slippage=_decimal_or_none(trade.get("slippage")) or Decimal("0"),
    )
    mfe, mae = excursion_r(direction=direction, entry=entry, stop=stop, candles=candle_rows)
    if net_r is None:
        category = OutcomeCategory.INSUFFICIENT_DATA
    elif net_r > Decimal("0.05"):
        category = OutcomeCategory.SUCCESS
    elif net_r < Decimal("-0.05"):
        category = OutcomeCategory.LOSS
    else:
        category = OutcomeCategory.BREAKEVEN

    if costs_r > 0:
        findings.append(
            FailureFinding(
                code="COSTS_REDUCED_RESULT",
                message=f"Recorded fees and slippage cost {costs_r:.4f}R.",
                confidence="confirmed",
                evidence_refs=refs,
            )
        )
    if category is OutcomeCategory.LOSS and "STOP_HIT" not in types:
        findings.append(
            FailureFinding(
                code="UNEXPLAINED_LOSS",
                message=(
                    "The trade lost without a recorded stop hit or invalidation. "
                    "The cause is not established by the available evidence."
                ),
                confidence="unknown",
                evidence_refs=refs,
            )
        )
    if str(trade.get("strategy_validation_status")) != "VALIDATED":
        findings.append(
            FailureFinding(
                code="STRATEGY_UNVALIDATED",
                message=(
                    "The strategy gate was not VALIDATED for this record. This is provenance "
                    "context, not evidence that the strategy caused the result."
                ),
                confidence="confirmed",
                evidence_refs=[str(trade.get("strategy_version") or "")],
            )
        )

    holding_seconds = None
    opened = trade.get("opened_at")
    closed = trade.get("closed_at")
    if opened and closed:
        try:
            holding_seconds = int(
                (datetime.fromisoformat(str(closed)) - datetime.fromisoformat(str(opened))).total_seconds()
            )
        except ValueError:
            holding_seconds = None

    return TradeOutcome(
        trade_id=str(trade["trade_id"]),
        category=category,
        r_multiple=net_r,
        gross_r=gross_r,
        costs_r=costs_r,
        mfe_r=mfe,
        mae_r=mae,
        holding_seconds=holding_seconds,
        findings=findings,
        evidence_refs=refs,
        sample_warning=(
            "One trade is an observation, not evidence of edge. Aggregate only reviewed, "
            "cost-aware samples and report the sample size."
        ),
    )


__all__ = ["analyze_outcome"]
