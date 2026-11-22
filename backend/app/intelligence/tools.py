"""Approved read-only tools exposed to the embedded model.

Only these registered handlers can be reached. Every one is ``Access.READ``; there is
no file, shell, network, order, account or model-promotion tool. The registry validates
arguments and the tool engine enforces timeouts and output bounds.
"""

from __future__ import annotations

from typing import Any

from app.analysis.service import AnalysisService
from app.kie.contracts import ToolSpec
from app.kie.tools.registry import ToolRegistry
from app.trade_planning.service import TradePlanningService

_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}


def register_trading_tools(
    registry: ToolRegistry,
    *,
    analysis: AnalysisService,
    strategies: Any,
    planning: TradePlanningService,
    forecast: Any | None = None,
    journal: Any | None = None,
    outcomes: Any | None = None,
) -> list[str]:
    """Register the read-only intelligence tools and return their names."""

    def market_snapshot(_: dict[str, Any]) -> dict[str, Any]:
        return analysis.snapshot().model_dump(mode="json")

    def market_indicators(_: dict[str, Any]) -> dict[str, Any]:
        snapshot = analysis.snapshot()
        return {
            "snapshot_id": snapshot.snapshot_id,
            "data_as_of": snapshot.data_as_of.isoformat(),
            "trend": snapshot.trend.model_dump(mode="json"),
            "momentum": snapshot.momentum.model_dump(mode="json"),
            "volatility": snapshot.volatility.model_dump(mode="json"),
        }

    def market_structure(_: dict[str, Any]) -> dict[str, Any]:
        snapshot = analysis.snapshot()
        return {
            "snapshot_id": snapshot.snapshot_id,
            "structure": snapshot.structure.model_dump(mode="json"),
            "liquidity": snapshot.liquidity.model_dump(mode="json"),
            "regime": snapshot.regime.model_dump(mode="json"),
        }

    def patron_forecast(_: dict[str, Any]) -> dict[str, Any]:
        if forecast is None:
            return {"available": False, "reason": "Forecast service is not configured."}
        latest = forecast.latest()
        if latest is None:
            return {"available": False, "reason": "No PATRON forecast has completed."}
        return {"available": True, "forecast": latest}

    def strategy_candidates(_: dict[str, Any]) -> dict[str, Any]:
        if strategies is None:
            return {"available": False, "reason": "Strategy service is unavailable."}
        return strategies.evaluate(strategy_id="trend_pullback").model_dump(mode="json")

    def strategy_definition(arguments: dict[str, Any]) -> dict[str, Any]:
        if strategies is None:
            return {"available": False, "reason": "Strategy service is unavailable."}
        catalog = strategies.catalog().model_dump(mode="json")
        wanted = str(arguments.get("strategy_id", "trend_pullback"))
        item = next(
            (row for row in catalog["strategies"] if row["strategy_id"] == wanted),
            None,
        )
        return item or {"available": False, "reason": f"Unknown strategy '{wanted}'."}

    def planning_current(_: dict[str, Any]) -> dict[str, Any]:
        return planning.current().model_dump(mode="json")

    def planning_risk(_: dict[str, Any]) -> dict[str, Any]:
        return planning.risk_current().model_dump(mode="json")

    def journal_open(_: dict[str, Any]) -> dict[str, Any]:
        if journal is None:
            return {"available": False, "reason": "Journal is unavailable."}
        return journal.list_records(status="OPEN", limit=50)

    def performance_summary(_: dict[str, Any]) -> dict[str, Any]:
        if outcomes is None:
            return {"available": False, "reason": "Outcome service is unavailable."}
        return outcomes.summary()

    specs = [
        ToolSpec(
            name="market.snapshot",
            description="Immutable BTCUSDT M15 market snapshot with validation and provenance.",
            parameters=_EMPTY,
        ),
        ToolSpec(
            name="market.indicators",
            description="Trend, momentum and volatility features from the current snapshot.",
            parameters=_EMPTY,
        ),
        ToolSpec(
            name="market.structure",
            description="Confirmed swings, structure events, levels, liquidity candidates and regime.",
            parameters=_EMPTY,
        ),
        ToolSpec(
            name="patron.forecast",
            description="Latest stored PATRON probabilistic forecast, if one exists.",
            parameters=_EMPTY,
        ),
        ToolSpec(
            name="strategies.candidates",
            description="Current deterministic trend-pullback evaluation.",
            parameters=_EMPTY,
        ),
        ToolSpec(
            name="strategies.definition",
            description="Versioned definition and status of one strategy.",
            parameters={
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "string", "maxLength": 64},
                },
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name="planning.current",
            description="Current deterministic trade plan, or the explicit blocked/invalid state.",
            parameters=_EMPTY,
        ),
        ToolSpec(
            name="planning.risk",
            description="Risk assessment for the current plan attempt. Read-only.",
            parameters=_EMPTY,
        ),
        ToolSpec(
            name="journal.open",
            description="Open paper/manual journal records. No position size or execution.",
            parameters=_EMPTY,
        ),
        ToolSpec(
            name="performance.summary",
            description="Reviewed outcome counts and categories. Not a profitability claim.",
            parameters=_EMPTY,
        ),
    ]
    handlers = {
        "market.snapshot": market_snapshot,
        "market.indicators": market_indicators,
        "market.structure": market_structure,
        "patron.forecast": patron_forecast,
        "strategies.candidates": strategy_candidates,
        "strategies.definition": strategy_definition,
        "planning.current": planning_current,
        "planning.risk": planning_risk,
        "journal.open": journal_open,
        "performance.summary": performance_summary,
    }
    registered: list[str] = []
    for spec in specs:
        if spec.name in registry:
            continue
        registry.register(spec, handlers[spec.name])
        registered.append(spec.name)
    return registered


__all__ = ["register_trading_tools"]
