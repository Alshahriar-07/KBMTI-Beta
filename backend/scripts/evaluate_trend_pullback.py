"""Run the provisional Phase 2 Trend Pullback evaluation on local BTCUSDT M15 data.

Example (from ``backend/``):

    .venv/Scripts/python.exe scripts/evaluate_trend_pullback.py \
        --data data/patron/BTCUSDT_15m.parquet \
        --output ../docs/AI_TRADING_UPGRADE/PHASE_2_EVALUATION.json

The script is read-only. It does not fetch market data, touch PATRON, or place any
order. The exported 60 cases start unreviewed, so the acceptance gate stays PENDING.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from app.market_data.candles import Candle
from app.strategies.evaluation import EvaluationConfig, evaluate_history

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "patron" / "BTCUSDT_15m.parquet"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "AI_TRADING_UPGRADE" / "PHASE_2_EVALUATION.json"


def load_candles(path: Path) -> list[Candle]:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stride", type=int, default=48)
    parser.add_argument("--warmup", type=int, default=200)
    parser.add_argument("--horizon", type=int, default=16)
    parser.add_argument("--review-cases", type=int, default=60)
    args = parser.parse_args(argv)

    if not args.data.exists():
        raise SystemExit(f"Data file not found: {args.data}")
    candles = load_candles(args.data)
    config = EvaluationConfig(
        stride=args.stride,
        warmup_bars=args.warmup,
        horizon_bars=args.horizon,
        review_cases=args.review_cases,
    )
    report = evaluate_history(candles, config)
    report["dataset"]["file"] = str(args.data)
    report["dataset"]["sha256"] = __import__("hashlib").sha256(args.data.read_bytes()).hexdigest()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(
        f"evaluated={report['sampling']['evaluated_bars']} "
        f"decisions={report['counts']} "
        f"candidates={report['outcomes']['candidate_count']} "
        f"hit_rate={report['outcomes']['hit_rate_all_candidates']} "
        f"gate={report['gate']['status']} "
        f"cases={report['gate']['exported_cases']}"
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
