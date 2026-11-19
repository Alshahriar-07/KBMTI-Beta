from __future__ import annotations

import pytest

from app.strategies.evaluation import EvaluationConfig, build_review_cases, evaluate_history
from tests.strategy_fixtures import build_cycle_candles


def test_evaluation_config_rejects_unsafe_warmup() -> None:
    with pytest.raises(ValueError):
        EvaluationConfig(warmup_bars=10)
    with pytest.raises(ValueError):
        EvaluationConfig(stride=0)


def test_provisional_report_is_reproducible_and_gate_stays_pending() -> None:
    candles = build_cycle_candles(1, [-16.0] * 4 + [9.0] * 3)
    config = EvaluationConfig(stride=20, warmup_bars=120, horizon_bars=4, review_cases=60)

    first = evaluate_history(candles, config)
    second = evaluate_history(candles, config)

    assert first["sampling"]["evaluated_bars"] > 0
    assert first["counts"] == second["counts"]
    assert first["sampling"]["evaluated_bars"] == second["sampling"]["evaluated_bars"]
    assert [case["candle_time"] for case in first["cases"]] == [case["candle_time"] for case in second["cases"]]
    assert set(first["counts"]) == {"LONG", "SHORT", "WAIT", "NO_TRADE"}
    assert sum(first["counts"].values()) == first["sampling"]["evaluated_bars"]
    assert first["dataset"]["source_sha256"] == second["dataset"]["source_sha256"]
    assert first["gate"]["status"] == "PENDING"
    assert first["gate"]["required_cases"] == 60
    assert first["gate"]["reviewed_cases"] == 0
    assert first["gate"]["exported_cases"] == len(first["cases"])
    assert first["evidence_completeness"]["completeness_rate"] == 1.0
    assert "algorithmic labels" in first["label_definition"].lower()
    assert first["outcomes"]["horizon_bars"] == 4
    assert all(case["review_status"] == "PENDING" for case in first["cases"])


def test_review_case_selection_is_even_and_bounded() -> None:
    records = [
        {"candle_time": f"2026-01-01T{index:02d}:00:00Z", "evaluation_id": f"evl_{index}", "snapshot_id": "mkt_x",
         "decision": "WAIT", "direction": "NONE", "quality_score": 0, "trend_state": "NEUTRAL",
         "structure_state": "RANGING", "regime_state": "RANGING", "rejection_codes": [], "wait_codes": [],
         "evidence_codes": ["MARKET_SNAPSHOT"], "hit": None, "directional_return_pct": None, "move_atr": 0.0}
        for index in range(25)
    ]
    cases = build_review_cases(records, limit=5)
    assert len(cases) == 5
    assert [case["case"] for case in cases] == [1, 2, 3, 4, 5]
    assert cases[0]["candle_time"] == records[0]["candle_time"]
    assert cases[-1]["candle_time"] == records[-1]["candle_time"]
    assert len(build_review_cases(records, limit=60)) == len(records)  # bounded by available records
    assert build_review_cases([], limit=60) == []
