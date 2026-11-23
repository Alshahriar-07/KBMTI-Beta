"""Independently review the 60 exported Phase 2 cases against the frozen rules.

This tool is an **automated coding agent**, not a human reviewer. It reads the
reconstructed evidence packet, re-applies the documented gate order and numeric
thresholds from ``trend_pullback`` config 1.0.0, derives a reviewed decision, and
compares it with the original algorithmic decision. The original decision is never
used to derive the reviewed one.

The Phase 2 acceptance gate requires independent human review and has no documented
minimum-agreement threshold. Therefore this tool records review progress and keeps
acceptance PENDING even when all 60 cases are reviewed.

Run from ``backend``::

    PYTHONPATH=. .venv/Scripts/python.exe scripts/review_phase2_cases.py --dry-run
    PYTHONPATH=. .venv/Scripts/python.exe scripts/review_phase2_cases.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.strategies.contracts import StrategyDecision
from app.strategies.evaluation import aggregate_review

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ROOT / "docs" / "AI_TRADING_UPGRADE" / "PHASE_2_REVIEW_EVIDENCE.json"
DEFAULT_EVALUATION = ROOT / "docs" / "AI_TRADING_UPGRADE" / "PHASE_2_EVALUATION.json"
DEFAULT_RESULTS = ROOT / "docs" / "AI_TRADING_UPGRADE" / "PHASE_2_REVIEW_RESULTS.json"

REVIEWER = "Freebuff automated coding agent (LLM); not a human"
REVIEW_METHOD = (
    "Replayed each case from the frozen BTCUSDT M15 parquet, reconstructed the Phase 1 "
    "snapshot, then independently re-applied the documented trend-pullback gate order and "
    "numeric thresholds to the recorded inputs. The original decision was hidden during "
    "derivation and used only for comparison. No frozen threshold was changed."
)
MANUAL_FLAGS = {
    40: (
        "No support level existed below price, so the frozen 'room to support >= 1.0 ATR' "
        "check was not applicable rather than passed. Manual review should confirm that a "
        "missing support level is intended to permit a short candidate."
    ),
    53: (
        "The blocking CHOCH_DOWN was exactly 40 bars old (the inclusive lookback limit), and "
        "two later CHOCH_UP events did not clear it under the frozen rules. Borderline "
        "invalidation; manual review should confirm the lookback semantics."
    ),
}


def _derive(case: dict[str, Any]) -> tuple[str, str, str, str, list[str]]:
    """Return (decision, direction, gate, explanation, flags) from evidence only."""

    market = case["market"]
    m = case["indicators"]
    structure = case["structure"]
    flags: list[str] = []

    if market["validation"] != "OK" or market["is_stale"]:
        return "NO_TRADE", "NONE", "snapshot_validation", (
            f"validation={market['validation']}, stale={market['is_stale']}."
        ), flags

    required = (
        "atr14",
        "ema21",
        "ema50",
        "rsi14",
        "rsi_change",
        "macd_histogram",
        "macd_histogram_change",
        "roc_pct",
    )
    if any(m.get(key) is None for key in required) or not m["atr14"] or m["atr14"] <= 0:
        return "NO_TRADE", "NONE", "required_features", (
            f"missing or unusable inputs: {[key for key in required if m.get(key) is None]}."
        ), flags

    trend = m["trend_state"]
    if "BULLISH" in trend:
        side, expected_regime, expected_structure = "LONG", "TRENDING_UP", "UPTREND"
    elif "BEARISH" in trend:
        side, expected_regime, expected_structure = "SHORT", "TRENDING_DOWN", "DOWNTREND"
    else:
        return "NO_TRADE", "NONE", "trend", f"trend={trend} has no directional pullback.", flags

    if m["regime_state"] != expected_regime:
        return "NO_TRADE", "NONE", "regime_compatibility", (
            f"regime={m['regime_state']} is not required {expected_regime} for {trend}."
        ), flags

    if m["volatility_state"] == "EXTREME":
        return "NO_TRADE", "NONE", "volatility", (
            f"ATR percentile {m['atr_percentile']:.4f} is EXTREME."
        ), flags

    opposite = "DOWNTREND" if side == "LONG" else "UPTREND"
    if m["structure_state"] == opposite:
        return "NO_TRADE", "NONE", "structure_conflict", (
            f"structure={m['structure_state']} opposes {side}."
        ), flags

    adverse_choch = "CHOCH_DOWN" if side == "LONG" else "CHOCH_UP"
    recent = [
        event
        for event in structure["events"]
        if event["type"] == adverse_choch
        and event["age_bars"] is not None
        and 0 <= event["age_bars"] <= 40
    ]
    if recent:
        event = recent[-1]
        if event["age_bars"] == 40:
            flags.append(MANUAL_FLAGS[53])
        return "NO_TRADE", "NONE", "structure_invalidated", (
            f"adverse {event['type']} at age {event['age_bars']} bars (limit 40)."
        ), flags

    if m["structure_state"] != expected_structure:
        return "WAIT", "NONE", "structure_alignment", (
            f"structure={m['structure_state']} has not confirmed {trend}."
        ), flags

    close = float(market["reference_price"])
    fast = float(m["fast_distance_atr"])
    slow = float(m["slow_distance_atr"])
    depth = float(m["retracement_depth_atr"])
    last_low = (m["latest_swing_low"] or {}).get("price")
    last_high = (m["latest_swing_high"] or {}).get("price")

    if side == "LONG":
        too_deep = slow < -0.25 or fast < -0.75
        broken = last_low is not None and close < float(last_low)
        pullback = -0.75 <= fast <= 0.35 and depth >= 0.25
        extended = fast > 0.60
    else:
        too_deep = slow > 0.25 or fast > 0.75
        broken = last_high is not None and close > float(last_high)
        pullback = -0.75 <= -fast <= 0.35 and depth >= 0.25
        extended = fast < -0.60

    if too_deep:
        return "NO_TRADE", "NONE", "pullback_too_deep", (
            f"close-EMA21={fast:+.2f} ATR, close-EMA50={slow:+.2f} ATR exceeds the frozen area."
        ), flags
    if broken:
        return "NO_TRADE", "NONE", "pullback_invalidated", (
            f"close {close:.2f} is beyond the latest confirmed swing."
        ), flags
    if not pullback or extended:
        return "WAIT", "NONE", "pullback_not_present", (
            f"fast EMA distance {fast:+.2f} ATR, depth {depth:.2f} ATR, extended={extended}; "
            "price is not in the frozen pullback zone."
        ), flags

    rsi = float(m["rsi14"])
    rsi_change = float(m["rsi_change"])
    hist_change = float(m["macd_histogram_change"])
    roc = float(m["roc_pct"])
    if side == "LONG":
        deteriorated = rsi <= 30.0 or (
            m["momentum_state"] == "BEARISH" and hist_change < 0 and roc < -0.75
        )
    else:
        deteriorated = rsi >= 70.0 or (
            m["momentum_state"] == "BULLISH" and hist_change > 0 and roc > 0.75
        )
    if deteriorated:
        return "NO_TRADE", "NONE", "momentum_deterioration", (
            f"RSI {rsi:.2f}, histogram change {hist_change:+.6f}, ROC {roc:+.3f}%."
        ), flags

    if side == "LONG":
        confirmed = close > float(m["ema21"]) and hist_change > 0 and rsi_change > 0
    else:
        confirmed = close < float(m["ema21"]) and hist_change < 0 and rsi_change < 0
    if not confirmed:
        gate = "AWAITING_RECLAIM" if (
            (side == "LONG" and close <= float(m["ema21"]))
            or (side == "SHORT" and close >= float(m["ema21"]))
        ) else "AWAITING_MOMENTUM_CONFIRMATION"
        return "WAIT", "NONE", gate, (
            f"close={close:.2f}, EMA21={float(m['ema21']):.2f}, histogram change "
            f"{hist_change:+.6f}, RSI change {rsi_change:+.2f}; confirmation incomplete."
        ), flags

    if side == "LONG":
        room = m["nearest_resistance"]
        if room is None:
            flags.append(
                "No resistance level existed above price, so the frozen room check was not "
                "applicable. Manual review should confirm this is intended."
            )
        elif room["distance_atr"] < 1.0:
            return "NO_TRADE", "NONE", "resistance_too_close", (
                f"nearest resistance is {room['distance_atr']:.2f} ATR away (minimum 1.0)."
            ), flags
    else:
        room = m["nearest_support"]
        if room is None:
            flags.append(MANUAL_FLAGS[40])
        elif room["distance_atr"] < 1.0:
            return "NO_TRADE", "NONE", "support_too_close", (
                f"nearest support is {room['distance_atr']:.2f} ATR away (minimum 1.0)."
            ), flags

    adverse_kind = "high" if side == "LONG" else "low"
    adverse_sweeps = [
        sweep
        for sweep in case["liquidity"]["sweeps"]
        if sweep["kind"] == adverse_kind
        and sweep["confirmation"] == "CONFIRMED"
        and sweep["distance_atr"] is not None
        and sweep["distance_atr"] <= 0.75
        and sweep["age_bars"] is not None
        and 0 <= sweep["age_bars"] <= 8
    ]
    if adverse_sweeps:
        sweep = adverse_sweeps[-1]
        return "NO_TRADE", "NONE", "liquidity_conflict", (
            f"confirmed {sweep['kind']} sweep {sweep['distance_atr']:.2f} ATR away at age "
            f"{sweep['age_bars']} bars."
        ), flags

    return side, side, "candidate", (
        f"all frozen gates passed: fast EMA {fast:+.2f} ATR, depth {depth:.2f} ATR, "
        f"RSI {rsi:.2f}, histogram change {hist_change:+.6f}, "
        f"room {'not applicable (no level)' if room is None else f'{room['distance_atr']:.2f} ATR'}."
    ), flags


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    evaluation = json.loads(args.evaluation.read_text(encoding="utf-8"))
    evidence_cases = {item["case"]: item for item in evidence["cases"]}
    if len(evidence_cases) != 60:
        raise SystemExit("evidence packet does not contain 60 unique cases")

    reviewed_at = datetime.now(UTC).isoformat()
    reviews: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    results_counts: Counter[str] = Counter()
    disagreements: list[int] = []

    for case in evaluation["cases"]:
        number = case["case"]
        item = evidence_cases.get(number)
        if item is None:
            raise SystemExit(f"case {number} missing from evidence packet")
        decision, direction, gate, explanation, flags = _derive(item)
        recorded = case["decision"]
        match = decision == recorded
        if not match:
            disagreements.append(number)
        result = "PASS" if match and not flags else "PASS_WITH_MANUAL_FLAG" if match else "FAIL"
        note = (
            f"{gate}: {explanation} Independent review decision {decision} "
            f"{'matches' if match else 'DIFFERS FROM'} the recorded {recorded}."
        )
        if flags:
            note += " Manual flag: " + " ".join(flags)
        counts[decision] += 1
        results_counts[result] += 1
        reviews.append(
            {
                "case": number,
                "candle_time": case["candle_time"],
                "evaluation_id": case["evaluation_id"],
                "recorded_decision": recorded,
                "reviewed_decision": decision,
                "reviewed_direction": direction,
                "review_result": result,
                "decisive_gate": gate,
                "review_notes": note,
                "manual_review_required": bool(flags),
                "manual_review_reasons": flags,
                "evidence_ref": f"PHASE_2_REVIEW_EVIDENCE.json#case-{number}",
            }
        )

    print(f"reviewed={len(reviews)} decisions={dict(counts)} results={dict(results_counts)}")
    print(f"disagreements={disagreements}")
    if args.dry_run:
        for review in reviews:
            if review["review_result"] != "PASS" or review["recorded_decision"] != review["reviewed_decision"]:
                print(
                    f"case {review['case']}: {review['recorded_decision']} -> "
                    f"{review['reviewed_decision']} ({review['review_result']}) "
                    f"{review['review_notes']}"
                )
        return 0

    if disagreements:
        raise SystemExit(
            f"refusing to write a completed review with disagreements: {disagreements}"
        )

    reviews_by_case = {item["case"]: item for item in reviews}
    for case in evaluation["cases"]:
        review = reviews_by_case[case["case"]]
        case["review_status"] = "REVIEWED"
        case["reviewer"] = REVIEWER
        case["reviewed_decision"] = review["reviewed_decision"]
        case["reviewed_direction"] = review["reviewed_direction"]
        case["review_result"] = review["review_result"]
        case["review_notes"] = review["review_notes"]
        case["manual_review_required"] = review["manual_review_required"]
        case["evidence_ref"] = review["evidence_ref"]

    evaluation = aggregate_review(evaluation)
    evaluation["review"] = {
        "reviewed_at": reviewed_at,
        "reviewer": REVIEWER,
        "method": REVIEW_METHOD,
        "cases_reviewed": len(reviews),
        "results": dict(results_counts),
        "decisions": dict(counts),
        "disagreements": disagreements,
        "manual_flags": [item["case"] for item in reviews if item["manual_review_required"]],
        "provenance": (
            "Automated review by a coding agent. This is not independent human approval and "
            "must not be described as such."
        ),
    }
    evaluation["gate"]["acceptance_status"] = "PENDING"
    evaluation["gate"]["reason"] = (
        "All 60 cases have an evidence-based automated review, but the documented Phase 2 "
        "gate requires independent human review, and the repository defines no minimum "
        "agreement or candidate-performance acceptance threshold. Acceptance therefore "
        "remains PENDING; strategy_validation_status stays PENDING and no trade plan is "
        "enabled."
    )

    validation = {
        "exported_cases": len(evaluation["cases"]),
        "unique_case_ids": len({item["case"] for item in evaluation["cases"]}),
        "unique_evaluation_ids": len({item["evaluation_id"] for item in evaluation["cases"]}),
        "reviewed_cases": sum(
            1 for item in evaluation["cases"] if item["review_status"] == "REVIEWED"
        ),
        "missing_reviews": [
            item["case"]
            for item in evaluation["cases"]
            if item["review_status"] != "REVIEWED" or not item["reviewed_decision"]
        ],
        "invalid_decisions": [
            item["case"]
            for item in evaluation["cases"]
            if item["reviewed_decision"] not in {choice.value for choice in StrategyDecision}
        ],
        "gate_status": evaluation["gate"]["status"],
        "acceptance_status": evaluation["gate"]["acceptance_status"],
    }
    if (
        validation["reviewed_cases"] != 60
        or validation["unique_case_ids"] != 60
        or validation["unique_evaluation_ids"] != 60
        or validation["missing_reviews"]
        or validation["invalid_decisions"]
    ):
        raise SystemExit(f"aggregate validation failed: {validation}")

    results_doc = {
        "report_version": "phase2-review-results-1.0.0",
        "reviewed_at": reviewed_at,
        "reviewer": REVIEWER,
        "method": REVIEW_METHOD,
        "provenance": (
            "Automated coding-agent review. Not human approval. The original decisions were "
            "kept separate and compared only after independent derivation."
        ),
        "gate": evaluation["gate"],
        "validation": validation,
        "counts": dict(counts),
        "results": dict(results_counts),
        "manual_flags": [item["case"] for item in reviews if item["manual_review_required"]],
        "disagreements": disagreements,
        "cases": reviews,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(results_doc, indent=2), encoding="utf-8")
    args.evaluation.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))
    print(f"wrote {args.results}")
    print(f"updated {args.evaluation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
