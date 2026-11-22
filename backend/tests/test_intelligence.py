from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.analysis.service import AnalysisService
from app.core.config import Settings
from app.intelligence.contracts import QwenOutput
from app.intelligence.knowledge import KnowledgeBase
from app.intelligence.service import IntelligenceService
from app.intelligence.tools import register_trading_tools
from app.intelligence.validator import parse_output, validate_output
from app.kie.contracts import ToolCall
from app.kie.tools.engine import ToolEngine
from app.kie.tools.registry import ToolRegistry
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


def _stack(settings: Settings):
    database = Database(settings.db_path)
    database.initialize()
    analysis = AnalysisService(
        source=StaticCandleSource(CANDLES),
        repository=MarketSnapshotRepository(database),
        settings=settings,
        clock=lambda: NOW,
        cache_seconds=0.0,
    )
    strategies = StrategyService(
        analysis=analysis,
        repository=StrategyEvaluationRepository(database),
        clock=lambda: NOW,
    )
    planning = TradePlanningService(
        analysis=analysis,
        strategies=strategies,
        risk=RiskService(clock=lambda: NOW),
        repository=TradePlanRepository(database),
        clock=lambda: NOW,
    )
    return analysis, strategies, planning


def test_knowledge_retrieval_is_versioned_and_deterministic() -> None:
    kb = KnowledgeBase()
    assert kb.document_count >= 4
    first = kb.search("change of character liquidity sweep", limit=3)
    second = kb.search("change of character liquidity sweep", limit=3)
    assert [hit.id for hit in first.hits] == [hit.id for hit in second.hits]
    assert first.hits[0].version == "1.0.0"
    assert all(hit.refs[0].startswith("knowledge:") for hit in first.hits)
    assert first.corpus_version == "trading-knowledge-1.0.0"


def _output(**overrides):
    payload = {
        "action": "LONG",
        "market_context": "Trend and structure are aligned while momentum remains constructive.",
        "strategy_rationale": "The deterministic candidate passed its checklist.",
        "plan_rationale": "The hypothetical geometry is incomplete without execution.",
        "uncertainty": "The strategy gate is pending independent review.",
        "next_action": "Human review is required before any further action.",
        "evidence_refs": ["snapshot:abc"],
        "warnings": [],
    }
    payload.update(overrides)
    return QwenOutput.model_validate(payload)


def test_validator_rejects_invented_numbers_and_wrong_action() -> None:
    validate_output(
        _output(),
        authoritative_action="LONG",
        allowed_refs={"snapshot:abc"},
        allowed_numbers={Decimal("31881.91")},
    )
    with pytest.raises(ValueError, match="does not match"):
        validate_output(_output(), authoritative_action="WAIT", allowed_refs={"snapshot:abc"}, allowed_numbers=[])
    with pytest.raises(ValueError, match="not present"):
        validate_output(
            _output(market_context="Price is 99999.99 and trend is aligned."),
            authoritative_action="LONG",
            allowed_refs={"snapshot:abc"},
            allowed_numbers={Decimal("31881.91")},
        )
    with pytest.raises(ValueError, match="unknown evidence_refs"):
        validate_output(
            _output(evidence_refs=["snapshot:unknown"]),
            authoritative_action="LONG",
            allowed_refs={"snapshot:abc"},
            allowed_numbers=[],
        )
    with pytest.raises(ValueError, match="prohibited"):
        validate_output(
            _output(next_action="Buy now and widen the stop if needed."),
            authoritative_action="LONG",
            allowed_refs={"snapshot:abc"},
            allowed_numbers=[],
        )


def test_parse_output_accepts_fences() -> None:
    raw = "```json\n" + json.dumps(_output().model_dump(mode="json")) + "\n```"
    assert parse_output(raw).action.value == "LONG"


class _FakeKie:
    enabled = True
    ready = True
    config = SimpleNamespace(enabled=True)

    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid

    def status(self):
        return {"identity": {"description": "fake-qwen3-4b"}}

    def chat(self, request):
        prompt = request.messages[-1].content
        authoritative = json.loads(prompt.split("AUTHORITATIVE:\n", 1)[1])
        action = authoritative["authoritative_action"] if self.valid else "NO_TRADE"
        refs = authoritative["allowed_evidence_refs"][:3]
        payload = {
            "action": action,
            "market_context": "Trend, structure and momentum are described by deterministic features.",
            "strategy_rationale": "The candidate is explained by its checklist, not a probability.",
            "plan_rationale": "The geometry is hypothetical and no execution record exists.",
            "uncertainty": "The strategy gate remains pending independent review.",
            "next_action": "Human review is required before any execution decision.",
            "evidence_refs": refs,
            "warnings": ["No order is placed."],
        }
        return {"text": json.dumps(payload), "run_id": "run_fake"}


def test_deterministic_intelligence_is_review_gated(settings: Settings) -> None:
    analysis, strategies, planning = _stack(settings)
    service = IntelligenceService(analysis=analysis, strategies=strategies, planning=planning, kie=None, clock=lambda: NOW)
    result = service.current(use_qwen=True)
    assert result.action.value in {"LONG", "SHORT"}
    assert result.plan_status == "PLAN_REVIEW_REQUIRED"
    assert result.execution_eligibility == "REVIEW_REQUIRED"
    assert result.strategy_validation_status == "PENDING"
    assert result.position_size is None
    assert result.position_size_status == "NOT_CALCULATED"
    assert result.qwen.used is False
    assert result.knowledge_refs
    assert "PENDING" in result.uncertainty


def test_valid_qwen_narration_is_accepted(settings: Settings) -> None:
    analysis, strategies, planning = _stack(settings)
    service = IntelligenceService(
        analysis=analysis, strategies=strategies, planning=planning, kie=_FakeKie(valid=True), clock=lambda: NOW
    )
    result = service.current(use_qwen=True)
    assert result.qwen.used is True
    assert result.qwen.status.value == "USED"
    assert result.qwen.model == "fake-qwen3-4b"
    assert "deterministic features" in result.market_explanation


def test_invalid_qwen_action_is_rejected(settings: Settings) -> None:
    analysis, strategies, planning = _stack(settings)
    service = IntelligenceService(
        analysis=analysis, strategies=strategies, planning=planning, kie=_FakeKie(valid=False), clock=lambda: NOW
    )
    result = service.current(use_qwen=True)
    assert result.qwen.used is False
    assert result.qwen.status.value == "INVALID"
    assert "rejected" in result.warnings[-1].lower()
    # Deterministic action survives the model attempt.
    assert result.action.value in {"LONG", "SHORT"}


def test_read_only_tools_are_registered_and_execute(settings: Settings) -> None:
    analysis, strategies, planning = _stack(settings)
    registry = ToolRegistry()
    names = register_trading_tools(
        registry, analysis=analysis, strategies=strategies, planning=planning, forecast=None
    )
    assert "market.indicators" in names
    assert {spec.access.value for spec in registry.specs()} == {"read"}
    engine = ToolEngine(registry)
    result = engine.execute(ToolCall(name="market.indicators", arguments={}, call_id="c1"))
    assert result.ok is True
    assert "snapshot_id" in result.content
    assert "trend" in result.content
    assert "order" not in result.content.lower()
