"""One real, opt-in run of the unified market-intelligence endpoint.

Uses local Binance candles and the promoted PATRON checkpoint, then calls the
embedded Qwen3-4B runtime through the production IntelligenceService path. It
writes the actual model output and validation notes; it never fabricates a
successful run.

    cd backend
    PYTHONPATH=. .venv/Scripts/python.exe scripts/qwen_pipeline_smoke.py
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

# PyTorch and the pinned Vulkan llama.cpp DLLs both bundle an OpenMP runtime. This
# diagnostic loads both in one process; the model output is still validated normally.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import pandas as pd  # noqa: E402

from app.analysis.service import AnalysisService
from app.analysis.sources import CandleBatch
from app.core.config import Settings
from app.intelligence.service import IntelligenceService
from app.kie.service import KieService
from app.market_data.candles import Candle
from app.patron.service import PatronInferenceService
from app.persistence.db import Database
from app.persistence.repositories import (
    MarketSnapshotRepository,
    StrategyEvaluationRepository,
    TradePlanRepository,
)
from app.risk.service import RiskService
from app.strategies.service import StrategyService
from app.trade_planning.service import TradePlanningService


class LocalCandleSource:
    provider = "binance"

    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    def fetch(self, symbol: str, timeframe: str, limit: int) -> CandleBatch:
        return CandleBatch(
            candles=list(self.candles[-limit:]),
            provider=self.provider,
            source="local_parquet",
            fetched_at=datetime.now(UTC),
        )


class StaticForecast:
    def __init__(self, run: dict) -> None:
        self.run = run

    def latest(self) -> dict:
        return self.run


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/patron/BTCUSDT_15m.parquet")
    parser.add_argument(
        "--out", default="../docs/AI_TRADING_UPGRADE/LIVE_QWEN_FRONTEND_EVIDENCE.json"
    )
    parser.add_argument("--bars", type=int, default=500)
    args = parser.parse_args()

    settings = Settings()
    settings.ensure_dirs()
    frame = pd.read_parquet(args.data).tail(max(args.bars, 520))
    candles = [
        Candle(
            time=int(row.timestamp_open.timestamp()),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            tick_volume=int(getattr(row, "trades", 0) or 0),
            real_volume=int(row.volume),
            source="binance",
            symbol="BTCUSDT",
        )
        for row in frame.itertuples()
    ]
    now = datetime.fromtimestamp(candles[-1].time, UTC) + timedelta(minutes=15, seconds=30)

    patron = PatronInferenceService(settings)
    patron.ensure_loaded(blocking=True)
    rows = [
        {
            "open_time_ms": int(row.timestamp_open.timestamp() * 1000),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        for row in frame.itertuples()
    ]
    payload = patron.forecast_from_candles(rows, now=now)
    reference_close = candles[-1].close
    derived_candles: list[dict[str, object]] = []
    previous_close = reference_close
    for index, step in enumerate(payload.get("range_quantiles", [])[:6], start=1):
        close = reference_close * (1.0 + float(step["close"]["q50"]))
        open_ = previous_close
        high = max(reference_close * (1.0 + float(step["high"]["q50"])), open_, close)
        low = min(reference_close * (1.0 + float(step["low"]["q50"])), open_, close)
        derived_candles.append(
            {
                "sequence": index - 1,
                "timestamp_utc": candles[-1].time + 900 * index,
                "open": round(open_, 8),
                "high": round(high, 8),
                "low": round(low, 8),
                "close": round(close, 8),
            }
        )
        previous_close = close
    run = {
        "id": "live-unified-smoke",
        "provider": "patron",
        "model_id": "patron-1.0.0",
        "created_at": iso_now(),
        "input_last_bar_at": candles[-1].time,
        "candles": derived_candles,
        "output": {
            "patron": payload,
            "meta": {
                "reference_close": candles[-1].close,
                "checkpoint": str(settings.patron_checkpoint),
                "checkpoint_sha256": patron.status().get("checkpoint_sha256"),
            },
        },
    }

    database = Database(settings.db_path)
    database.initialize()
    analysis = AnalysisService(
        source=LocalCandleSource(candles),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: now,
        cache_seconds=0.0,
    )
    strategies = StrategyService(
        analysis=analysis,
        repository=StrategyEvaluationRepository(database),
        clock=lambda: now,
    )
    planning = TradePlanningService(
        analysis=analysis,
        strategies=strategies,
        risk=RiskService(clock=lambda: now),
        repository=TradePlanRepository(database),
        clock=lambda: now,
    )
    kie = KieService(db=database)
    load = kie.load()
    service = IntelligenceService(
        analysis=analysis,
        strategies=strategies,
        planning=planning,
        forecast=StaticForecast(run),
        kie=kie,
        clock=lambda: now,
    )
    result = service.market_intelligence(use_qwen=True, refresh=True)
    evidence = {
        "generated_at": iso_now(),
        "as_of": now.isoformat(),
        "patron": {
            "state": patron.status()["state"],
            "checkpoint_sha256": patron.status().get("checkpoint_sha256"),
            "last_latency_ms": patron.status().get("last_latency_ms"),
            "as_of": payload.get("as_of"),
            "momentum": payload.get("momentum"),
            "barrier": payload.get("barrier_probabilities"),
        },
        "qwen_load": {
            "backend": load.get("backend"),
            "seconds": load.get("load_seconds"),
            "identity": (load.get("status") or {}).get("identity"),
        },
        "result": result.model_dump(mode="json"),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ai_status": result.ai_status.model_dump(mode="json"),
                "assessment": result.forecast_assessment.status.value,
                "decision": result.decision.value,
                "interpretation": result.ai_market_interpretation,
                "forecast_interpretation": result.ai_forecast_interpretation,
            },
            indent=2,
        )
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
