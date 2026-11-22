"""Contracts for the Qwen-backed trading-intelligence layer.

The model only narrates facts that already exist in the deterministic snapshot, strategy
evaluation and plan. It cannot change the action, invent a price or override risk; those
constraints are enforced by :mod:`app.intelligence.validator`, not by prompt wording.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntelligenceAction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"


class QwenOutput(StrictModel):
    """The only JSON shape accepted from Qwen."""

    action: IntelligenceAction
    market_context: str = Field(min_length=20, max_length=1200)
    strategy_rationale: str = Field(min_length=20, max_length=1200)
    plan_rationale: str = Field(min_length=20, max_length=1200)
    uncertainty: str = Field(min_length=10, max_length=800)
    next_action: str = Field(min_length=5, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=10)


class QwenStatus(StrEnum):
    USED = "USED"
    INITIALIZING = "INITIALIZING"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"
    TIMEOUT = "TIMEOUT"
    DISABLED = "DISABLED"


class QwenMetadata(StrictModel):
    used: bool
    status: QwenStatus
    model: str | None = None
    run_id: str | None = None
    latency_ms: float | None = None
    error: str | None = None
    validation_notes: list[str] = Field(default_factory=list)


class KnowledgeHit(StrictModel):
    id: str
    version: str
    title: str
    text: str
    score: float
    refs: list[str] = Field(default_factory=list)


class KnowledgeSearchResponse(StrictModel):
    query: str
    hits: list[KnowledgeHit]
    count: int
    corpus_version: str


class StrategyComparison(StrictModel):
    strategy_id: str
    strategy_version: str
    decision: str
    quality_score: int
    quality_label: str
    validation_status: str
    eligible: bool
    reason: str


class TradingIntelligence(StrictModel):
    request_id: str
    generated_at: AwareDatetime
    data_as_of: AwareDatetime
    is_stale: bool
    snapshot_id: str
    strategy_evaluation_id: str
    plan_id: str | None = None
    symbol: str
    timeframe: str

    action: IntelligenceAction
    plan_status: str
    execution_eligibility: str
    strategy_validation_status: str

    market_explanation: str
    strategy_comparison: list[StrategyComparison]
    plan_explanation: str
    uncertainty: str
    next_action: str

    evidence_refs: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    knowledge: list[KnowledgeHit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    qwen: QwenMetadata

    position_size_status: Literal["NOT_CALCULATED"] = "NOT_CALCULATED"
    position_size: None = None
    execution: Literal["DISABLED"] = "DISABLED"
    disclaimer: str = (
        "Deterministic analysis and a PENDING strategy gate. Not investment advice, "
        "not a validated edge, and no order or position size exists."
    )


class IntelligenceStatus(StrictModel):
    enabled: bool
    deterministic_available: bool
    qwen_enabled: bool
    qwen_ready: bool
    qwen_model: str | None = None
    knowledge_documents: int
    knowledge_version: str
    strategy_validation_status: str
    execution: Literal["DISABLED"] = "DISABLED"
    generated_at: AwareDatetime
    notes: list[str] = Field(default_factory=list)


class ExplainRequest(StrictModel):
    use_qwen: bool = True
    question: str | None = Field(default=None, max_length=1000)
