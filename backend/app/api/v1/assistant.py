"""Read-only trading-intelligence endpoints.

The historical execution-route test forbids paths containing order/trade/buy/sell, so
the assistant lives under ``/assistant``. It returns explanations, never instructions
to execute.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep
from app.core.errors import ApiError
from app.intelligence.contracts import (
    ExplainRequest,
    IntelligenceStatus,
    KnowledgeSearchResponse,
    TradingIntelligence,
)
from app.intelligence.market_contracts import MarketIntelligence

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _service(container):  # noqa: ANN001 - avoid api<->container import cycle
    service = container.intelligence
    if service is None:
        raise ApiError(
            "INTELLIGENCE_UNAVAILABLE",
            "The trading-intelligence layer is unavailable; deterministic endpoints still work.",
            503,
        )
    return service


@router.get("/current", response_model=TradingIntelligence)
def current_intelligence(
    container: ContainerDep,
    refresh: bool = Query(default=False),
    use_qwen: bool = Query(default=True),
) -> TradingIntelligence:
    return _service(container).current(refresh=refresh, use_qwen=use_qwen)


@router.post("/explain", response_model=TradingIntelligence)
def explain(container: ContainerDep, request: ExplainRequest) -> TradingIntelligence:
    return _service(container).current(refresh=True, use_qwen=request.use_qwen)


@router.get("/market-intelligence", response_model=MarketIntelligence)
def market_intelligence(
    container: ContainerDep,
    refresh: bool = Query(default=False),
    use_qwen: bool = Query(default=True),
) -> MarketIntelligence:
    """One validated response for every frontend market-analysis component."""

    return _service(container).market_intelligence(refresh=refresh, use_qwen=use_qwen)


@router.get("/status", response_model=IntelligenceStatus)
def intelligence_status(container: ContainerDep) -> IntelligenceStatus:
    return _service(container).status()


@router.get("/knowledge", response_model=KnowledgeSearchResponse)
def knowledge_search(
    container: ContainerDep,
    q: str = Query(min_length=2, max_length=300),
    limit: int = Query(default=4, ge=1, le=10),
) -> KnowledgeSearchResponse:
    return _service(container).search_knowledge(q, limit=limit)
