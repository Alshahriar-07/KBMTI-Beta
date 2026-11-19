"""Provisional historical evaluation harness for the Trend Pullback strategy.

This module is deliberately separate from the strategy and its API. It replays
closed candles chronologically, evaluates the same pure function the API uses, and
computes *labels afterwards* from later candles. Labels never enter a snapshot.

What this harness can and cannot claim:

* It measures deterministic behavior and rule outcomes on local historical data.
* Its labels are algorithmic (forward close-to-close move over a fixed horizon and
  path excursions in ATR units), not independently reviewed trade outcomes.
* It does not produce entry, stop, target, leverage or size, and it does not
  simulate order fills, fees, funding or slippage.

The reviewed 60-case acceptance gate therefore remains PENDING unless a human has
independently reviewed the exported cases. The report says so explicitly.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.analysis.context import MarketContextBuilder
from app.market_data.candles import Candle
from app.strategies.config import STRATEGY_ID, STRATEGY_VERSION
from app.strategies.trend_pullback import evaluate_trend_pullback

MIN_WARMUP_BARS = 120
LABEL_DEFINITION = (
    "Labels are computed only after the evaluation: for a LONG candidate the bar is a hit when "
    "close at t+horizon is above close at t, and a miss when it is below; SHORT is the mirror. "
    "Forward return is (close[t+horizon]-close[t])/close[t]*100 in the candidate's direction. "
    "Max favourable/adverse excursion measures the high/low path in ATR units and is a "
    "measurement only, not an entry/stop rule. These are algorithmic labels, not reviewed trades."
)


@dataclass(frozen=True, slots=True)
class EvaluationConfig:
    stride: int = 48
    warmup_bars: int = 200
    horizon_bars: int = 16
    material_move_atr: float = 1.0
    max_candles: int = 500
    review_cases: int = 60

    def __post_init__(self) -> None:
        if self.stride < 1:
            raise ValueError("stride must be >= 1")
        if self.warmup_bars < MIN_WARMUP_BARS:
            raise ValueError(f"warmup_bars must be >= {MIN_WARMUP_BARS}")
        if self.horizon_bars < 1:
            raise ValueError("horizon_bars must be >= 1")
        if self.review_cases < 1:
            raise ValueError("review_cases must be >= 1")


def _iso(timestamp: int | None) -> str | None:
    return datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp is not None else None


def _source_hash(candles: list[Candle]) -> str:
    digest = hashlib.sha256()
    for candle in candles:
        digest.update(
            f"{candle.time}|{candle.open}|{candle.high}|{candle.low}|{candle.close}|{candle.tick_volume}".encode()
        )
    return digest.hexdigest()


def _collect_records(candles: list[Candle], config: EvaluationConfig) -> list[dict[str, Any]]:
    clock_box = {"now": datetime.now(UTC)}
    builder = MarketContextBuilder(stale_after_seconds=120.0, clock=lambda: clock_box["now"])
    records: list[dict[str, Any]] = []
    last_index = len(candles) - 1

    for index in range(config.warmup_bars, len(candles) - config.horizon_bars, config.stride):
        window = candles[max(0, index + 1 - config.max_candles) : index + 1]
        if len(window) < MIN_WARMUP_BARS:
            continue
        clock_box["now"] = datetime.fromtimestamp(candles[index].time + 930, UTC)
        snapshot = builder.build(
            symbol="BTCUSDT",
            timeframe="M15",
            candles=window,
            provider="binance",
            source="historical",
            fetched_at=clock_box["now"],
        )
        evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

        close = float(candles[index].close)
        atr = float(snapshot.volatility.atr14 or 0.0)
        forward_close = float(candles[min(index + config.horizon_bars, last_index)].close)
        future = candles[index + 1 : index + config.horizon_bars + 1]
        forward_return_pct = (forward_close - close) / close * 100.0 if close else 0.0
        move_atr = abs(forward_close - close) / atr if atr > 0 else 0.0

        direction = evaluation.direction.value
        hit: bool | None = None
        directional_return_pct: float | None = None
        max_favourable_atr: float | None = None
        max_adverse_atr: float | None = None
        if direction in {"LONG", "SHORT"}:
            hit = forward_close > close if direction == "LONG" else forward_close < close
            directional_return_pct = forward_return_pct if direction == "LONG" else -forward_return_pct
            if atr > 0 and future:
                if direction == "LONG":
                    max_favourable_atr = (max(c.high for c in future) - close) / atr
                    max_adverse_atr = (close - min(c.low for c in future)) / atr
                else:
                    max_favourable_atr = (close - min(c.low for c in future)) / atr
                    max_adverse_atr = (max(c.high for c in future) - close) / atr

        records.append(
            {
                "index": index,
                "candle_time": _iso(candles[index].time),
                "data_as_of": evaluation.data_as_of.isoformat(),
                "evaluation_id": evaluation.evaluation_id,
                "decision": evaluation.decision.value,
                "direction": direction,
                "confirmation_status": evaluation.confirmation_status.value,
                "quality_score": evaluation.quality.score,
                "quality_label": evaluation.quality.label.value,
                "trend_state": snapshot.trend.state.value,
                "structure_state": snapshot.structure.state.value,
                "regime_state": snapshot.regime.state.value,
                "volatility_state": snapshot.volatility.state.value,
                "rejection_codes": [reason.code for reason in evaluation.rejection_reasons],
                "wait_codes": [reason.code for reason in evaluation.wait_reasons],
                "evidence_codes": [item.code for item in evaluation.evidence],
                "snapshot_id": evaluation.market_snapshot_id,
                "reference_price": evaluation.reference_price,
                "atr": atr,
                "forward_close": forward_close,
                "forward_return_pct": round(forward_return_pct, 6),
                "directional_return_pct": round(directional_return_pct, 6)
                if directional_return_pct is not None
                else None,
                "move_atr": round(move_atr, 4),
                "hit": hit,
                "max_favourable_atr": round(max_favourable_atr, 4)
                if max_favourable_atr is not None
                else None,
                "max_adverse_atr": round(max_adverse_atr, 4) if max_adverse_atr is not None else None,
            }
        )
    return records


def _hit_rate(records: list[dict[str, Any]], direction: str | None = None) -> float | None:
    selected = [
        record
        for record in records
        if record["hit"] is not None and (direction is None or record["direction"] == direction)
    ]
    if not selected:
        return None
    return round(sum(1 for record in selected if record["hit"]) / len(selected), 4)


def _mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), 4) if present else None


def _evenly(records: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not records:
        return []
    if count >= len(records):
        return list(records)
    if count == 1:
        return [records[0]]
    return [records[round(position * (len(records) - 1) / (count - 1))] for position in range(count)]


def _select_cases(records: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Stratified, deterministic selection: every candidate, then WAIT, then NO_TRADE.

    A uniform sample of this dataset would be almost entirely trivial NO_TRADE cases.
    Oversampling candidates and WAIT decisions (evenly spaced within each group) keeps
    the review packet informative without cherry-picking outcomes: selection depends
    only on decision type and chronological position.
    """

    candidates = [record for record in records if record["decision"] in {"LONG", "SHORT"}]
    waits = [record for record in records if record["decision"] == "WAIT"]
    no_trades = [record for record in records if record["decision"] == "NO_TRADE"]

    selected_candidates = _evenly(candidates, limit)
    remaining = limit - len(selected_candidates)
    wait_budget = min(len(waits), remaining) if not no_trades else min(len(waits), max(1, remaining // 2))
    selected_waits = _evenly(waits, wait_budget) if remaining > 0 else []
    remaining -= len(selected_waits)
    selected_no_trades = _evenly(no_trades, remaining) if remaining > 0 else []

    selected = [*selected_candidates, *selected_waits, *selected_no_trades]
    if len(selected) < limit:
        used = {record["evaluation_id"] for record in selected}
        leftovers = [record for record in records if record["evaluation_id"] not in used]
        selected.extend(_evenly(leftovers, limit - len(selected)))
    selected.sort(key=lambda record: record["candle_time"])
    return selected, {
        "candidates": len(selected_candidates),
        "wait": len(selected_waits),
        "no_trade": len(selected_no_trades),
    }


def build_review_cases(records: list[dict[str, Any]], limit: int = 60) -> list[dict[str, Any]]:
    """Select cases for the human-reviewed gate; every case starts unreviewed."""

    if not records:
        return []
    selected, _ = _select_cases(records, limit)
    cases: list[dict[str, Any]] = []
    for position, record in enumerate(selected, start=1):
        cases.append(
            {
                "case": position,
                "candle_time": record["candle_time"],
                "evaluation_id": record["evaluation_id"],
                "snapshot_id": record["snapshot_id"],
                "strategy_id": STRATEGY_ID,
                "strategy_version": STRATEGY_VERSION,
                "decision": record["decision"],
                "direction": record["direction"],
                "quality_score": record["quality_score"],
                "trend_state": record["trend_state"],
                "structure_state": record["structure_state"],
                "regime_state": record["regime_state"],
                "rejection_codes": record["rejection_codes"],
                "wait_codes": record["wait_codes"],
                "evidence_codes": record["evidence_codes"],
                "algorithmic_label": {
                    "hit": record["hit"],
                    "directional_return_pct": record["directional_return_pct"],
                    "move_atr": record["move_atr"],
                },
                "review_status": "PENDING",
                "reviewer": None,
                "reviewed_decision": None,
                "review_notes": None,
            }
        )
    return cases


def evaluate_history(candles: list[Candle], config: EvaluationConfig | None = None) -> dict[str, Any]:
    config = config or EvaluationConfig()
    records = _collect_records(candles, config)
    decisions = Counter(record["decision"] for record in records)
    rejections = Counter(code for record in records for code in record["rejection_codes"])
    waits = Counter(code for record in records for code in record["wait_codes"])
    by_regime: dict[str, Counter[str]] = {}
    for record in records:
        by_regime.setdefault(record["regime_state"], Counter())[record["decision"]] += 1

    candidates = [record for record in records if record["decision"] in {"LONG", "SHORT"}]
    misses = [record for record in candidates if record["hit"] is False]
    waits_material = [
        record for record in records if record["decision"] == "WAIT" and record["move_atr"] >= config.material_move_atr
    ]
    no_trades_material = [
        record for record in records if record["decision"] == "NO_TRADE" and record["move_atr"] >= config.material_move_atr
    ]
    quality_histogram = Counter(record["quality_label"] for record in candidates)

    evidence_complete = 0
    for record in records:
        has_market = "MARKET_SNAPSHOT" in record["evidence_codes"]
        has_explanation = bool(record["rejection_codes"] or record["wait_codes"]) or record["decision"] in {
            "LONG",
            "SHORT",
        }
        if has_market and has_explanation and record["snapshot_id"]:
            evidence_complete += 1

    report: dict[str, Any] = {
        "report_version": "phase2-provisional-1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "strategy": {"strategy_id": STRATEGY_ID, "strategy_version": STRATEGY_VERSION},
        "dataset": {
            "symbol": "BTCUSDT",
            "timeframe": "M15",
            "candles": len(candles),
            "first_candle": _iso(candles[0].time) if candles else None,
            "last_candle": _iso(candles[-1].time) if candles else None,
            "source_sha256": _source_hash(candles),
        },
        "sampling": {
            "method": "chronological fixed stride; no randomisation, no peeking",
            "stride_bars": config.stride,
            "warmup_bars": config.warmup_bars,
            "evaluated_bars": len(records),
        },
        "label_definition": LABEL_DEFINITION,
        "counts": {decision: decisions.get(decision, 0) for decision in ("LONG", "SHORT", "WAIT", "NO_TRADE")},
        "quality": {
            "candidate_count": len(candidates),
            "histogram": {label: quality_histogram.get(label, 0) for label in ("LOW", "MEDIUM", "HIGH")},
            "mean_candidate_score": _mean([record["quality_score"] for record in candidates]),
        },
        "decisions_by_regime": {
            regime: {decision: counter.get(decision, 0) for decision in ("LONG", "SHORT", "WAIT", "NO_TRADE")}
            for regime, counter in sorted(by_regime.items())
        },
        "rejection_codes": dict(sorted(rejections.items())),
        "wait_codes": dict(sorted(waits.items())),
        "outcomes": {
            "horizon_bars": config.horizon_bars,
            "candidate_count": len(candidates),
            "hit_rate_all_candidates": _hit_rate(records),
            "hit_rate_long": _hit_rate(records, "LONG"),
            "hit_rate_short": _hit_rate(records, "SHORT"),
            "false_positive_count": len(misses),
            "false_positive_rate": round(len(misses) / len(candidates), 4) if candidates else None,
            "mean_directional_return_pct": _mean([record["directional_return_pct"] for record in candidates]),
            "median_directional_return_pct": round(
                sorted(
                    record["directional_return_pct"]
                    for record in candidates
                    if record["directional_return_pct"] is not None
                )[len(candidates) // 2],
                4,
            )
            if candidates
            else None,
            "mean_max_favourable_atr": _mean([record["max_favourable_atr"] for record in candidates]),
            "mean_max_adverse_atr": _mean([record["max_adverse_atr"] for record in candidates]),
        },
        "missed_opportunities": {
            "material_move_atr": config.material_move_atr,
            "wait_with_material_move": len(waits_material),
            "no_trade_with_material_move": len(no_trades_material),
            "note": (
                "A material move after WAIT/NO_TRADE is a missed opportunity only in hindsight; it is "
                "not counted as an error because the strategy intentionally declines unclear setups."
            ),
        },
        "evidence_completeness": {
            "records": len(records),
            "complete_records": evidence_complete,
            "completeness_rate": round(evidence_complete / len(records), 4) if records else None,
            "mean_evidence_items": _mean([float(len(record["evidence_codes"])) for record in records]),
        },
        "gate": {
            "required_cases": 60,
            "exported_cases": 0,
            "reviewed_cases": 0,
            "status": "PENDING",
            "reason": (
                "No independent human review of the 60 exported cases has been performed. The gate "
                "must not be reported as passed on algorithmic labels alone."
            ),
        },
        "case_selection": {
            "method": (
                "Deterministic stratified sample: every candidate (capped at the limit), then evenly "
                "spaced WAIT decisions, then evenly spaced NO_TRADE decisions in chronological order."
            ),
            "budget": _select_cases(records, config.review_cases)[1],
        },
        "limitations": [
            "Single synthetic/local dataset; not a live-trading sample.",
            "Algorithmic labels only; no independent review.",
            "No fees, funding, slippage or order-fill simulation.",
            "Fixed-stride sampling keeps runtime bounded but still overlaps forward windows.",
            "The strategy emits no entry, stop or target, so no trade PnL is claimed.",
        ],
        "cases": build_review_cases(records, limit=config.review_cases),
    }
    report["gate"]["exported_cases"] = len(report["cases"])
    return report


def aggregate_review(report: dict[str, Any]) -> dict[str, Any]:
    """Summarise review progress without ever inventing review outcomes."""

    cases = report.get("cases") or []
    reviewed = [case for case in cases if case.get("review_status") == "REVIEWED"]
    report["gate"]["reviewed_cases"] = len(reviewed)
    if len(reviewed) < 60:
        report["gate"]["status"] = "PENDING"
    else:
        report["gate"]["status"] = "COMPLETE"
    return report
