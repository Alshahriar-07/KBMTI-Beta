"""Rebuild full input evidence for the 60 exported Phase 2 review cases.

The canonical ``PHASE_2_EVALUATION.json`` intentionally stores only a compact
summary per case. An independent review needs the actual snapshot values that the
frozen rules consume. This read-only script replays each case's closed bar from the
same parquet and records the strategy inputs, checks and reasons.

It never fills in a reviewed decision. Review status and decisions stay exactly as
they are in the source file.

Run from ``backend``::

    PYTHONPATH=. .venv/Scripts/python.exe scripts/build_phase2_review_evidence.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.analysis.context import MarketContextBuilder
from app.analysis.contracts import SCOPE_TIMEFRAME_SECONDS
from app.market_data.candles import Candle
from app.strategies.trend_pullback import evaluate_trend_pullback

DEFAULT_EVALUATION = (
    Path(__file__).resolve().parents[2] / "docs" / "AI_TRADING_UPGRADE" / "PHASE_2_EVALUATION.json"
)
DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "patron" / "BTCUSDT_15m.parquet"
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "AI_TRADING_UPGRADE"
    / "PHASE_2_REVIEW_EVIDENCE.json"
)
WINDOW_BARS = 500
STALE_AFTER_SECONDS = 120.0


def _value(item: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(item, name):
            value = getattr(item, name)
            return value.value if hasattr(value, "value") else value
    return default


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def load_candles(path: Path) -> list[Candle]:
    """Load closed candles exactly as the evaluation harness does."""

    import pandas as pd

    frame = pd.read_parquet(path)
    required = {"timestamp_open", "open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise SystemExit(f"{path} is missing columns: {sorted(missing)}")
    frame = frame.sort_values("timestamp_open").drop_duplicates("timestamp_open")
    return [
        Candle(
            time=int(row.timestamp_open.timestamp()),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            tick_volume=int(float(row.volume)) if "volume" in frame.columns else 0,
            source="binance",
            symbol="BTCUSDT",
        )
        for row in frame.itertuples(index=False)
    ]


def _bar(candle: Candle) -> dict[str, Any]:
    return {
        "time": datetime.fromtimestamp(candle.time, UTC).isoformat(),
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.tick_volume,
    }


def _structure(snapshot: Any) -> dict[str, Any]:
    def age(item: Any) -> float | None:
        value = _value(item, "candle_time", "time")
        if not isinstance(value, datetime):
            return None
        return round((snapshot.data_as_of - value).total_seconds() / SCOPE_TIMEFRAME_SECONDS, 2)

    return {
        "state": _value(snapshot.structure, "state"),
        "swings": [
            {
                "kind": _value(item, "kind"),
                "price": _value(item, "price"),
                "time": _jsonable(_value(item, "candle_time", "time")),
                "confirmed": _value(item, "confirmed"),
            }
            for item in getattr(snapshot.structure, "swings", [])[-8:]
        ],
        "levels": [
            {
                "kind": _value(item, "kind"),
                "price": _value(item, "price"),
                "touches": _value(item, "touches"),
                "time": _jsonable(_value(item, "candle_time", "time", "created_at")),
            }
            for item in getattr(snapshot.structure, "levels", [])[-12:]
        ],
        "events": [
            {
                "type": _value(item, "type"),
                "price": _value(item, "price"),
                "time": _jsonable(_value(item, "candle_time", "time")),
                "age_bars": age(item),
                "confirmed": _value(item, "confirmed"),
            }
            for item in getattr(snapshot.structure, "events", [])[-60:]
            if age(item) is None or age(item) <= 48
        ],
    }


def _liquidity(snapshot: Any, close: float, atr: float) -> dict[str, Any]:
    def age(item: Any) -> float | None:
        value = _value(item, "candle_time", "time")
        if not isinstance(value, datetime):
            return None
        return round((snapshot.data_as_of - value).total_seconds() / SCOPE_TIMEFRAME_SECONDS, 2)

    return {
        "sweeps": [
            {
                "kind": _value(item, "kind"),
                "level": _value(item, "level"),
                "distance_atr": (
                    abs(float(_value(item, "level", default=close)) - close) / atr
                    if atr
                    else None
                ),
                "age_bars": age(item),
                "time": _jsonable(_value(item, "candle_time", "time")),
                "confirmation": _value(item, "confirmation"),
            }
            for item in getattr(snapshot.liquidity, "sweeps", [])[-12:]
        ],
        "pools": [
            {
                "kind": _value(item, "kind"),
                "price": _value(item, "price"),
                "touches": _value(item, "touches"),
            }
            for item in getattr(snapshot.liquidity, "pools", [])[-8:]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--window", type=int, default=WINDOW_BARS)
    args = parser.parse_args()

    report = json.loads(args.evaluation.read_text(encoding="utf-8"))
    cases = report.get("cases") or []
    if len(cases) != 60:
        raise SystemExit(f"expected 60 cases, found {len(cases)}")
    candles = load_candles(args.data)
    by_time = {
        datetime.fromtimestamp(candle.time, UTC).isoformat(): index
        for index, candle in enumerate(candles)
    }

    evidence_cases: list[dict[str, Any]] = []
    for case in cases:
        candle_time = case["candle_time"]
        if candle_time not in by_time:
            raise SystemExit(f"case {case['case']}: candle {candle_time} not found")
        index = by_time[candle_time]
        window = candles[max(0, index + 1 - args.window) : index + 1]
        clock = datetime.fromtimestamp(candles[index].time + 930, UTC)
        builder = MarketContextBuilder(
            stale_after_seconds=STALE_AFTER_SECONDS, clock=lambda clock=clock: clock
        )
        snapshot = builder.build(
            symbol="BTCUSDT",
            timeframe="M15",
            candles=window,
            provider="binance",
            source="historical",
            fetched_at=clock,
        )
        evaluation = evaluate_trend_pullback(snapshot, evaluated_at=snapshot.generated_at)

        atr = float(snapshot.volatility.atr14 or 0.0)
        close = float(snapshot.last_price)
        ema21 = float(snapshot.trend.ema21 or 0.0)
        ema50 = float(snapshot.trend.ema50 or 0.0)
        last_high = next(
            (s for s in reversed(snapshot.structure.swings) if _value(s, "kind") == "high"),
            None,
        )
        last_low = next(
            (s for s in reversed(snapshot.structure.swings) if _value(s, "kind") == "low"),
            None,
        )
        resistances = [
            level for level in snapshot.structure.levels if float(_value(level, "price", default=0)) > close
        ]
        supports = [
            level for level in snapshot.structure.levels if float(_value(level, "price", default=0)) < close
        ]
        nearest_resistance = (
            min(resistances, key=lambda level: float(_value(level, "price")))
            if resistances
            else None
        )
        nearest_support = (
            max(supports, key=lambda level: float(_value(level, "price"))) if supports else None
        )
        long_depth = (
            float(_value(last_high, "price", default=close)) - close
        ) / atr if atr else 0.0
        short_depth = (
            close - float(_value(last_low, "price", default=close))
        ) / atr if atr else 0.0
        trend = snapshot.trend.state.value
        direction_bias = "SHORT" if "BEARISH" in trend else "LONG" if "BULLISH" in trend else "NONE"
        depth = short_depth if direction_bias == "SHORT" else long_depth if direction_bias == "LONG" else 0.0

        evidence_cases.append(
            {
                "case": case["case"],
                "candle_time": candle_time,
                "evaluation_id": case["evaluation_id"],
                "snapshot_id": case["snapshot_id"],
                "recorded_decision": case["decision"],
                "recorded_direction": case["direction"],
                "recorded_rejection_codes": case["rejection_codes"],
                "recorded_wait_codes": case["wait_codes"],
                "algorithmic_label": case["algorithmic_label"],
                "market": {
                    "symbol": snapshot.symbol,
                    "timeframe": snapshot.timeframe,
                    "data_as_of": snapshot.data_as_of.isoformat(),
                    "generated_at": snapshot.generated_at.isoformat(),
                    "reference_price": close,
                    "validation": snapshot.validation.status.value,
                    "is_stale": snapshot.is_stale,
                    "last_8_closed_candles": [
                        _bar(item) for item in candles[max(0, index - 7) : index + 1]
                    ],
                },
                "indicators": {
                    "atr14": atr,
                    "atr_percentile": snapshot.volatility.atr_percentile,
                    "ema9": snapshot.trend.ema9,
                    "ema21": ema21,
                    "ema50": ema50,
                    "fast_distance_atr": (close - ema21) / atr if atr else None,
                    "slow_distance_atr": (close - ema50) / atr if atr else None,
                    "rsi14": snapshot.momentum.rsi14,
                    "rsi_change": snapshot.momentum.rsi_change,
                    "macd_histogram": snapshot.momentum.macd_histogram,
                    "macd_histogram_change": snapshot.momentum.macd_histogram_change,
                    "roc_pct": snapshot.momentum.roc_pct,
                    "trend_state": snapshot.trend.state.value,
                    "trend_strength": snapshot.trend.strength.value,
                    "trend_slope_pct_per_bar": snapshot.trend.slope_pct_per_bar,
                    "momentum_state": snapshot.momentum.state.value,
                    "regime_state": snapshot.regime.state.value,
                    "volatility_state": snapshot.volatility.state.value,
                    "structure_state": snapshot.structure.state.value,
                    "latest_swing_high": (
                        {
                            "price": _value(last_high, "price"),
                            "time": _jsonable(_value(last_high, "candle_time", "time")),
                        }
                        if last_high
                        else None
                    ),
                    "latest_swing_low": (
                        {
                            "price": _value(last_low, "price"),
                            "time": _jsonable(_value(last_low, "candle_time", "time")),
                        }
                        if last_low
                        else None
                    ),
                    "trend_direction": direction_bias,
                    "long_retracement_depth_atr": long_depth,
                    "short_retracement_depth_atr": short_depth,
                    "retracement_depth_atr": depth,
                    "nearest_resistance": (
                        {
                            "price": _value(nearest_resistance, "price"),
                            "distance_atr": (
                                float(_value(nearest_resistance, "price")) - close
                            )
                            / atr
                            if atr
                            else None,
                        }
                        if nearest_resistance
                        else None
                    ),
                    "nearest_support": (
                        {
                            "price": _value(nearest_support, "price"),
                            "distance_atr": (
                                close - float(_value(nearest_support, "price"))
                            )
                            / atr
                            if atr
                            else None,
                        }
                        if nearest_support
                        else None
                    ),
                },
                "structure": _structure(snapshot),
                "liquidity": _liquidity(snapshot, close, atr),
                "recomputed": {
                    "decision": evaluation.decision.value,
                    "direction": evaluation.direction.value,
                    "confirmation_status": evaluation.confirmation_status.value,
                    "quality_score": evaluation.quality.score,
                    "rejection_codes": [reason.code for reason in evaluation.rejection_reasons],
                    "wait_codes": [reason.code for reason in evaluation.wait_reasons],
                    "checks": [check.model_dump(mode="json") for check in evaluation.eligibility.checks],
                    "reasons": [
                        reason.model_dump(mode="json")
                        for reason in [*evaluation.rejection_reasons, *evaluation.wait_reasons]
                    ],
                    "evidence_codes": [item.code for item in evaluation.evidence],
                },
                "reproduction": {
                    "evaluation_id_matches": evaluation.evaluation_id == case["evaluation_id"],
                    "snapshot_id_matches": evaluation.market_snapshot_id == case["snapshot_id"],
                    "decision_matches": evaluation.decision.value == case["decision"],
                    "direction_matches": evaluation.direction.value == case["direction"],
                },
            }
        )

    payload = {
        "report_version": "phase2-review-evidence-1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_evaluation": str(args.evaluation.resolve()),
        "source_sha256": hashlib.sha256(args.evaluation.read_bytes()).hexdigest(),
        "data": str(args.data.resolve()),
        "data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "window_bars": args.window,
        "method": (
            "Each exported case is replayed from the same closed parquet bar with the "
            "frozen Phase 1 snapshot builder. The packet records the actual rule inputs and "
            "checks. It does not assign a review decision; review status stays PENDING."
        ),
        "counts": {
            "cases": len(evidence_cases),
            "reproduced_decisions": sum(
                1 for item in evidence_cases if item["reproduction"]["decision_matches"]
            ),
            "reproduced_ids": sum(
                1 for item in evidence_cases if item["reproduction"]["evaluation_id_matches"]
            ),
        },
        "cases": evidence_cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "cases": payload["counts"]["cases"],
                "reproduced_decisions": payload["counts"]["reproduced_decisions"],
                "reproduced_ids": payload["counts"]["reproduced_ids"],
                "out": str(args.output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
