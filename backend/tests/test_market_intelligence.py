from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.analysis.service import AnalysisService
from app.core.config import Settings
from app.intelligence.contracts import QwenStatus
from app.intelligence.market_contracts import ForecastAssessmentStatus, MarketCondition
from app.intelligence.service import IntelligenceService
from app.intelligence.visualization import build_chart_overlay
from app.persistence.db import Database
from app.persistence.repositories import (
    MarketSnapshotRepository,
    StrategyEvaluationRepository,
    TradePlanRepository,
)
from app.risk.service import RiskService
from app.strategies.service import StrategyService
from app.trade_planning.service import TradePlanningService
from tests.analysis_fixtures import StaticCandleSource
from tests.strategy_fixtures import build_cycle_candles

CANDLES = build_cycle_candles(1, [-16.0] * 4 + [9.0] * 3)
NOW = datetime.fromtimestamp(int(CANDLES[-1].time) + 930, UTC)


class _FakeForecast:
    def __init__(self, run: dict | None) -> None:
        self.run = run

    def latest(self) -> dict | None:
        return self.run


def _stack(settings: Settings, *, candles=None, now: datetime | None = None):
    candles = candles or CANDLES
    now = now or NOW
    database = Database(settings.db_path)
    database.initialize()
    analysis = AnalysisService(
        source=StaticCandleSource(candles),
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
    return analysis, strategies, planning


def _run(snapshot, *, as_of: datetime | None = None, close_q50: float = 0.001) -> dict:
    as_of = as_of or snapshot.provenance.last_closed_candle_time
    payload = {
        "status": "OK",
        "symbol": "BTC/USDT",
        "as_of": as_of.isoformat(),
        "horizon_minutes": 90,
        "model_version": "patron-1.0.0",
        "feature_version": "features-1.0.0",
        "pattern_scores": {"doji": 0.2},
        "barrier_probabilities": {"tp_first": 0.45, "sl_first": 0.30, "timeout": 0.25},
        "range_quantiles": [
            {
                "step": step,
                "minutes_ahead": step * 15,
                "high": {"q10": 0.001, "q50": 0.004, "q90": 0.010},
                "low": {"q10": -0.010, "q50": -0.004, "q90": -0.001},
                "close": {
                    "q10": close_q50 * step / 6.0 - 0.0015,
                    "q50": close_q50 * step / 6.0,
                    "q90": close_q50 * step / 6.0 + 0.0015,
                },
            }
            for step in range(1, 7)
        ],
        "momentum": {
            "class_probabilities": {
                "strong_bullish": 0.30,
                "bullish": 0.30,
                "sideways": 0.20,
                "bearish": 0.15,
                "strong_bearish": 0.05,
            },
            "predicted_class": "bullish",
        },
        "data_quality": {"valid": True, "closed_candles": 96, "sequence_length": 96, "warnings": []},
    }
    return {
        "id": "run-1",
        "provider": "patron",
        "model_id": "patron-1.0.0",
        "created_at": NOW.isoformat(),
        "input_last_bar_at": int(as_of.timestamp()),
        "candles": [
            {
                "sequence": 0,
                "timestamp_utc": int(as_of.timestamp()) + 900,
                "open": float(snapshot.last_price),
                "high": float(snapshot.last_price) * 1.004,
                "low": float(snapshot.last_price) * 0.998,
                "close": float(snapshot.last_price) * 1.001,
            }
        ],
        "output": {
            "patron": payload,
            "meta": {
                "reference_close": float(snapshot.last_price),
                "checkpoint": "models/patron/best.pt",
                "checkpoint_sha256": "abc123",
            },
        },
    }


def _service(settings, run, *, kie=None, candles=None, now: datetime | None = None):
    now = now or NOW
    analysis, strategies, planning = _stack(settings, candles=candles, now=now)
    return IntelligenceService(
        analysis=analysis,
        strategies=strategies,
        planning=planning,
        forecast=_FakeForecast(run),
        kie=kie,
        clock=lambda: now,
    )


class _FakeKie:
    enabled = True
    ready = True
    config = SimpleNamespace(enabled=True)

    def __init__(self, *, mode: str = "valid") -> None:
        self.mode = mode
        self.prompt: str | None = None

    def status(self):
        return {"identity": {"description": "fake-qwen3-4b"}}

    def chat(self, request):
        self.prompt = request.messages[-1].content
        if self.mode == "timeout":
            raise TimeoutError("generation timed out")
        if self.mode == "malformed":
            return {"text": "not json at all", "run_id": "run-bad"}
        authoritative = json.loads(self.prompt.split("AUTHORITATIVE:\n", 1)[1])
        summary = "Deterministic market evidence is preserved for review."
        if self.mode == "invented-number":
            summary = "Price 99999.99 is the only valid entry."
        if self.mode == "echo-reason":
            reasons = authoritative["forecast_assessment"]["reasons"]
            summary = next((item for item in reasons if "ATR" in item), reasons[0])
        payload = {
            "action": authoritative["authoritative_action"],
            "market_summary": summary,
            "forecast_interpretation": "PATRON is source evidence and its assessment remains authoritative.",
            "bullish_evidence": ["Deterministic trend evidence is available."],
            "bearish_evidence": [],
            "uncertainty": "The strategy gate is pending and the forecast is probabilistic.",
            "missing_information": ["Verified account inputs are unavailable."],
            "next_action": "Wait for human review; execution remains disabled.",
            "evidence_refs": authoritative["allowed_evidence_refs"][:2],
            "warnings": ["No order is placed."],
        }
        return {"text": json.dumps(payload), "run_id": "run-fake"}


def test_unified_response_preserves_patron_source_and_deterministic_risk(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    run = _run(snapshot)
    service = _service(settings, run)
    result = service.market_intelligence(use_qwen=False)
    assert result.forecast_source is not None
    # Exact immutable source values, not a model rewrite.
    assert result.forecast_source.range_quantiles == run["output"]["patron"]["range_quantiles"]
    assert result.forecast_source.predicted_candles == run["candles"]
    assert result.forecast_source.source_hash
    assert result.forecast_assessment.status is ForecastAssessmentStatus.VALID
    assert result.forecast_assessment.usable_in_decision is True
    assert result.decision.value in {"LONG", "SHORT", "WAIT", "NO_TRADE"}
    assert result.execution == "DISABLED"
    assert result.position_size is None
    assert result.position_size_status == "NOT_CALCULATED"
    assert result.risk_validation.status
    assert result.ai_status.status is QwenStatus.DISABLED
    assert result.data_freshness["forecast_as_of"] is not None


def test_chart_overlay_is_derived_from_verified_levels_and_plan(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    result = _service(settings, _run(snapshot)).market_intelligence(use_qwen=False)
    overlay = result.chart_overlay

    assert [scenario.id for scenario in overlay.scenarios] == [
        "bullish_continuation",
        "bearish_reversal",
        "bearish_continuation",
        "bullish_reversal",
        "sideways_consolidation",
    ]
    assert all(level.price > 0 for level in overlay.levels)
    assert all(marker.price > 0 and marker.time for marker in overlay.structure)
    for scenario in overlay.scenarios:
        if scenario.available:
            assert scenario.unavailable_reason is None
            assert scenario.confirmation
            assert scenario.invalidation_text
            if scenario.id != "sideways_consolidation":
                assert scenario.trigger is not None
                assert scenario.path
        else:
            assert scenario.unavailable_reason
            assert scenario.path == []

    plan = result.trade_plan
    if plan is not None:
        expected_confirmation = (
            plan.entry_zone["upper"] if plan.direction == "LONG" else plan.entry_zone["lower"]
        )
        assert plan.confirmation_level == expected_confirmation
        assert plan.stop_basis
        assert plan.strategy_id
        assert plan.expires_at


def test_scenarios_without_verified_levels_are_unavailable() -> None:
    snapshot = SimpleNamespace(
        last_price=100.0,
        structure=SimpleNamespace(levels=[], events=[], state="INSUFFICIENT_DATA"),
        liquidity=SimpleNamespace(pools=[], sweeps=[]),
    )
    condition = MarketCondition(
        trend="NEUTRAL",
        trend_strength="WEAK",
        trend_alignment="MIXED",
        structure="INSUFFICIENT_DATA",
        momentum="NEUTRAL",
        momentum_phase="STEADY",
        volatility="NORMAL",
        volatility_phase="STABLE",
        regime="UNCERTAIN",
        direction="NEUTRAL",
        summary="Insufficient verified structure.",
    )
    overlay = build_chart_overlay(snapshot, condition, None)
    assert overlay.levels == []
    assert [scenario.available for scenario in overlay.scenarios] == [False] * 5
    assert all(scenario.unavailable_reason for scenario in overlay.scenarios)
    assert all(scenario.path == [] for scenario in overlay.scenarios)


def test_stale_patron_forecast_is_marked_and_not_usable(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    stale_as_of = snapshot.provenance.last_closed_candle_time - timedelta(minutes=45)
    result = _service(settings, _run(snapshot, as_of=stale_as_of)).market_intelligence(use_qwen=False)
    assert result.forecast_assessment.status is ForecastAssessmentStatus.STALE
    assert result.forecast_assessment.usable_in_decision is False
    assert "patron_forecast_usable_for_decision" in result.unavailable_fields
    assert result.readiness.patron.status == "STALE"
    assert result.readiness.patron.usable_in_decision is False


def test_missing_and_invalid_patron_are_explicit(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    missing = _service(settings, None).market_intelligence(use_qwen=False)
    assert missing.forecast_source is None
    assert missing.forecast_assessment.status is ForecastAssessmentStatus.UNAVAILABLE

    run = _run(snapshot)
    run["output"]["patron"].pop("range_quantiles")
    invalid = _service(settings, run).market_intelligence(use_qwen=False)
    assert invalid.forecast_assessment.status is ForecastAssessmentStatus.INVALID
    assert invalid.forecast_assessment.usable_in_decision is False


def test_conflicting_patron_path_is_flagged(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    result = _service(settings, _run(snapshot, close_q50=-0.02)).market_intelligence(use_qwen=False)
    assert result.forecast_assessment.status is ForecastAssessmentStatus.CONFLICTING_EVIDENCE
    assert result.forecast_assessment.conflicts
    assert result.forecast_assessment.direction_conflict_material is True
    assert result.forecast_assessment.median_path_atr is not None
    assert result.forecast_assessment.median_path_atr >= 0.25
    assert result.readiness.patron.status == "CONFLICTING"
    # The deterministic decision is not replaced by the conflicting forecast.
    assert result.decision.value in {"LONG", "SHORT", "WAIT", "NO_TRADE"}


def test_bullish_patron_against_bearish_market_is_conflicting(settings: Settings) -> None:
    candles = build_cycle_candles(-1, [-16.0] * 4 + [9.0] * 3)
    now = datetime.fromtimestamp(int(candles[-1].time) + 930, UTC)
    analysis, _, _ = _stack(settings, candles=candles, now=now)
    snapshot = analysis.snapshot()
    service = _service(settings, _run(snapshot, close_q50=0.02), candles=candles, now=now)
    result = service.market_intelligence(use_qwen=False)
    assessment = result.forecast_assessment
    assert assessment.deterministic_direction == "BEARISH"
    assert assessment.forecast_direction == "BULLISH"
    assert assessment.direction_conflict_material is True
    assert assessment.status is ForecastAssessmentStatus.CONFLICTING_EVIDENCE
    assert result.readiness.patron.status == "CONFLICTING"
    # PATRON stays independent evidence; it does not become the decision.
    assert result.decision.value in {"LONG", "SHORT", "WAIT", "NO_TRADE"}


def test_immaterial_opposite_median_is_not_a_directional_conflict(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    # A sign flip without displacement is noise, not a material disagreement. PATRON's
    # raw direction is still reported and measured instead of being silently dropped.
    result = _service(settings, _run(snapshot, close_q50=-1e-9)).market_intelligence(
        use_qwen=False
    )
    assessment = result.forecast_assessment
    assert assessment.forecast_direction == "BEARISH"
    assert assessment.median_path_atr is not None
    assert assessment.median_path_atr < 0.25
    assert assessment.direction_conflict_material is False
    assert assessment.conflicts == []
    assert assessment.status is ForecastAssessmentStatus.VALID
    assert any("materiality threshold" in reason for reason in assessment.reasons)


def test_pipeline_readiness_explains_each_component(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    result = _service(settings, _run(snapshot, close_q50=-0.02)).market_intelligence(
        use_qwen=False
    )
    readiness = result.readiness
    assert readiness.market.status == "READY"
    assert readiness.market.data_as_of is not None
    assert readiness.patron.status == "CONFLICTING"
    assert readiness.patron.usable_in_decision is False
    assert readiness.patron.conflicts
    assert readiness.qwen.status == "DISABLED"
    assert readiness.qwen.reason_code == "DISABLED"
    assert readiness.strategy.status == "PENDING"
    assert readiness.strategy.reason_code == "STRATEGY_GATE_PENDING"
    assert readiness.position_size.status == "NOT_CALCULATED"
    assert readiness.position_size.reason_code == "MISSING_ACCOUNT_INPUTS"
    assert readiness.position_size.missing_inputs
    assert readiness.execution.status == "DISABLED"
    assert result.position_size is None
    if result.trade_plan is None:
        assert readiness.trade_plan.status == "UNAVAILABLE"
        assert readiness.trade_plan.reason_code
        assert readiness.risk.status == "NOT_EVALUATED"
    else:
        assert readiness.trade_plan.status == "AVAILABLE"
        assert readiness.trade_plan.plan_status == result.trade_plan.plan_status
        assert readiness.risk.status == "APPROVED"


def test_missing_trade_plan_reports_the_strategy_reason(settings: Settings) -> None:
    candles = build_cycle_candles(1, [-14.0] * 4 + [9.0, 4.0])
    now = datetime.fromtimestamp(int(candles[-1].time) + 930, UTC)
    analysis, _, _ = _stack(settings, candles=candles, now=now)
    snapshot = analysis.snapshot()
    service = _service(settings, _run(snapshot), candles=candles, now=now)
    result = service.market_intelligence(use_qwen=False)
    assert result.trade_plan is None
    assert "trade_plan" in result.unavailable_fields
    assert result.decision.value in {"WAIT", "NO_TRADE"}
    readiness = result.readiness
    assert readiness.trade_plan.status == "UNAVAILABLE"
    assert readiness.trade_plan.reason_code in {"STRATEGY_WAIT", "STRATEGY_NO_TRADE"}
    assert readiness.trade_plan.detail.startswith("No trade plan was constructed")
    assert readiness.risk.status == "NOT_EVALUATED"
    assert readiness.position_size.status == "NOT_CALCULATED"
    assert result.position_size is None


def test_qwen_receives_patron_context_and_valid_narration_is_accepted(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    kie = _FakeKie()
    result = _service(settings, _run(snapshot), kie=kie).market_intelligence(use_qwen=True)
    assert kie.prompt is not None
    assert "patron_source" in kie.prompt
    assert "forecast_assessment" in kie.prompt
    assert "range_quantiles" in kie.prompt
    assert result.ai_status.status is QwenStatus.USED
    assert result.ai_status.used is True
    assert "Deterministic market evidence" in result.ai_market_interpretation
    assert result.ai_status.validation_notes


def test_qwen_may_quote_a_number_from_deterministic_reason_text(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    # The materiality note contains a rounded number (e.g. "0.11 ATR"). Quoting it is
    # not an invented claim: the number was computed deterministically and sent to Qwen.
    result = _service(settings, _run(snapshot, close_q50=-1e-9), kie=_FakeKie(mode="echo-reason")).market_intelligence(
        use_qwen=True
    )
    assert result.ai_status.status is QwenStatus.USED
    assert "ATR" in result.ai_market_interpretation
    assert any("materiality threshold" in item for item in result.forecast_assessment.reasons)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("invented-number", QwenStatus.INVALID), ("malformed", QwenStatus.INVALID), ("timeout", QwenStatus.TIMEOUT)],
)
def test_qwen_failures_keep_deterministic_response(settings: Settings, mode: str, expected: QwenStatus) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    result = _service(settings, _run(snapshot), kie=_FakeKie(mode=mode)).market_intelligence(use_qwen=True)
    assert result.ai_status.status is expected
    assert result.ai_status.used is False
    assert result.readiness.qwen.status == "FAILED"
    assert result.ai_market_interpretation
    assert result.decision.value in {"LONG", "SHORT", "WAIT", "NO_TRADE"}
    assert result.position_size is None


class _WarmingKie(_FakeKie):
    """Qwen is still loading when the request arrives, then becomes READY."""

    def __init__(self) -> None:
        super().__init__()
        self.ready = False
        self.health_state = "INITIALIZING"
        self.wait_calls: list[float] = []
        self.ensure_calls = 0

    def ensure_loading(self) -> None:
        self.ensure_calls += 1

    def wait_until_ready(self, timeout: float) -> bool:
        self.wait_calls.append(timeout)
        self.ready = True
        self.health_state = "READY"
        return True


class _NeverReadyKie(_FakeKie):
    def __init__(self) -> None:
        super().__init__()
        self.ready = False
        self.health_state = "INITIALIZING"
        self.wait_calls: list[float] = []

    def ensure_loading(self) -> None:
        return None

    def wait_until_ready(self, timeout: float) -> bool:
        self.wait_calls.append(timeout)
        return False


def test_qwen_initializing_then_ready_returns_real_interpretation(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    kie = _WarmingKie()
    result = _service(settings, _run(snapshot), kie=kie).market_intelligence(use_qwen=True)
    assert kie.wait_calls and kie.wait_calls[0] > 0
    assert kie.prompt is not None
    assert result.ai_status.status is QwenStatus.USED
    assert result.ai_status.used is True
    assert result.ai_market_interpretation
    assert result.readiness.qwen.status == "READY"
    assert result.readiness.qwen.reason_code == "USED"


def test_qwen_readiness_timeout_keeps_initializing_state(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    kie = _NeverReadyKie()
    result = _service(settings, _run(snapshot), kie=kie).market_intelligence(use_qwen=True)
    assert kie.wait_calls
    assert result.ai_status.status is QwenStatus.INITIALIZING
    assert result.ai_status.used is False
    assert result.readiness.qwen.status == "INITIALIZING"
    assert result.readiness.qwen.health_state == "INITIALIZING"
    assert result.ai_market_interpretation


def test_qwen_initializing_is_reported_without_waiting(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()

    class InitializingKie:
        enabled = True
        ready = False
        health_state = "INITIALIZING"
        config = SimpleNamespace(enabled=True)

        def __init__(self) -> None:
            self.calls = 0

        def ensure_loading(self) -> None:
            self.calls += 1

        def status(self):
            return {"last_error": None}

    kie = InitializingKie()
    result = _service(settings, _run(snapshot), kie=kie).market_intelligence(use_qwen=True)
    assert kie.calls == 1
    assert result.ai_status.status is QwenStatus.INITIALIZING
    assert result.ai_status.used is False
    assert result.position_size is None


def test_qwen_unavailable_returns_explicit_status(settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    result = _service(settings, _run(snapshot), kie=None).market_intelligence(use_qwen=True)
    assert result.ai_status.status is QwenStatus.UNAVAILABLE
    assert result.ai_status.used is False
    assert result.forecast_source is not None


def test_assistant_market_intelligence_endpoint(make_client, settings: Settings) -> None:
    analysis, _, _ = _stack(settings)
    snapshot = analysis.snapshot()
    service = _service(settings, _run(snapshot))
    client = make_client(
        analysis=analysis,
        strategies=service._strategies,
        risk=service._planning._risk,
        trade_planning=service._planning,
        intelligence=service,
    )
    response = client.get("/api/v1/assistant/market-intelligence?use_qwen=false")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["forecast_source"]["range_quantiles"]
    assert body["forecast_assessment"]["status"] in {
        "VALID",
        "LOW_CONFIDENCE",
        "CONFLICTING_EVIDENCE",
        "STALE",
        "INVALID",
        "UNAVAILABLE",
    }
    assert body["execution"] == "DISABLED"
    assert body["position_size"] is None
    assert body["ai_status"]["status"] == "DISABLED"
