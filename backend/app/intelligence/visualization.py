"""Deterministic chart annotations and conditional scenarios.

Everything in this module is derived from the immutable market snapshot and the
trade planner's geometry. No model is called, and a scenario without verified
levels is returned as unavailable rather than filled with a synthetic price.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.intelligence.market_contracts import (
    ChartLevelView,
    ChartMarkerView,
    ChartOverlay,
    MarketCondition,
    MarketScenario,
    ScenarioPoint,
)

MAX_LEVELS = 6
MAX_MARKERS = 18


def _value(item: Any) -> str:
    return str(getattr(item, "value", item))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    return None


def _level_views(snapshot: Any, last_price: float) -> list[ChartLevelView]:
    levels: list[ChartLevelView] = []
    for index, level in enumerate(getattr(snapshot.structure, "levels", []) or []):
        price = _number(getattr(level, "price", None))
        if price is None or price <= 0:
            continue
        kind = _value(getattr(level, "kind", "")).upper()
        if kind not in {"SUPPORT", "RESISTANCE"}:
            continue
        if kind == "SUPPORT" and price >= last_price:
            continue
        if kind == "RESISTANCE" and price <= last_price:
            continue
        levels.append(
            ChartLevelView(
                id=f"level:{kind.lower()}:{index}",
                kind=kind,
                price=price,
                label=f"{kind.title()} {index + 1}",
                touches=int(getattr(level, "touches", 0) or 0),
                time=_iso(getattr(level, "last_time", None)),
                detail=(
                    f"Cluster of {int(getattr(level, 'touches', 0) or 0)} verified swing "
                    f"touches; last tested {_iso(getattr(level, 'last_time', None)) or 'unknown time'}."
                ),
            )
        )
    levels.sort(key=lambda item: abs(item.price - last_price))
    selected = levels[:MAX_LEVELS]

    pools = list(getattr(snapshot.liquidity, "pools", []) or [])[:3]
    for index, pool in enumerate(pools):
        price = _number(getattr(pool, "price", None))
        if price is None or price <= 0:
            continue
        selected.append(
            ChartLevelView(
                id=f"liquidity:{getattr(pool, 'id', index)}",
                kind="LIQUIDITY",
                price=price,
                label=f"Liquidity {getattr(pool, 'side', '').title()}",
                touches=int(getattr(pool, "touches", 0) or 0),
                time=_iso(getattr(pool, "last_time", None)),
                detail=str(
                    getattr(pool, "evidence", None)
                    or "Repeated swing-level liquidity; not order-book depth."
                ),
            )
        )
    return selected


def _marker_views(snapshot: Any) -> list[ChartMarkerView]:
    markers: list[ChartMarkerView] = []
    seen: set[str] = set()
    for index, event in enumerate(getattr(snapshot.structure, "events", []) or []):
        kind = _value(getattr(event, "type", "")).upper()
        price = _number(getattr(event, "price", None))
        time = _iso(getattr(event, "candle_time", None))
        if price is None or time is None or kind in seen:
            continue
        seen.add(kind)
        bullish = kind.endswith("_UP") or kind in {"HH", "HL"}
        bearish = kind.endswith("_DOWN") or kind in {"LH", "LL"}
        markers.append(
            ChartMarkerView(
                id=f"structure:{index}:{kind}",
                kind=kind,
                price=price,
                time=time,
                label=kind,
                detail=str(
                    getattr(event, "evidence", None)
                    or "Confirmed structure event from closed candles."
                ),
                direction="BULLISH" if bullish else "BEARISH" if bearish else "NEUTRAL",
            )
        )
    for index, sweep in enumerate(getattr(snapshot.liquidity, "sweeps", []) or []):
        price = _number(getattr(sweep, "level", None))
        time = _iso(getattr(sweep, "candle_time", None))
        if price is None or time is None:
            continue
        kind = _value(getattr(sweep, "kind", "SWEEP")).upper()
        markers.append(
            ChartMarkerView(
                id=f"sweep:{index}:{kind}",
                kind=f"SWEEP_{kind}" if kind in {"HIGH", "LOW"} else "SWEEP",
                price=price,
                time=time,
                label=f"Liquidity sweep {kind.lower()}",
                detail=str(
                    getattr(sweep, "confirmation", None)
                    or "Verified sweep of a repeated swing level."
                ),
                direction="BEARISH" if kind == "HIGH" else "BULLISH",
            )
        )
    return markers[-MAX_MARKERS:]


def _levels_by_side(snapshot: Any, last_price: float) -> tuple[list[float], list[float]]:
    supports: list[float] = []
    resistances: list[float] = []
    for level in getattr(snapshot.structure, "levels", []) or []:
        price = _number(getattr(level, "price", None))
        if price is None:
            continue
        kind = _value(getattr(level, "kind", "")).upper()
        if kind == "SUPPORT" and price < last_price:
            supports.append(price)
        elif kind == "RESISTANCE" and price > last_price:
            resistances.append(price)
    supports.sort(key=lambda value: last_price - value)
    resistances.sort(key=lambda value: value - last_price)
    return supports, resistances


def _evidence(condition: MarketCondition) -> tuple[list[str], list[str]]:
    bullish = [
        f"Trend is {condition.trend} with {condition.trend_strength} strength.",
        f"Structure is {condition.structure}.",
        f"Momentum is {condition.momentum} ({condition.momentum_phase}).",
    ]
    bearish = [
        f"Trend is {condition.trend} with {condition.trend_strength} strength.",
        f"Structure is {condition.structure}.",
        f"Momentum is {condition.momentum} ({condition.momentum_phase}).",
    ]
    if "BULLISH" in condition.direction:
        bearish.append("Deterministic direction is bullish, opposing this bearish path.")
    elif "BEARISH" in condition.direction:
        bullish.append("Deterministic direction is bearish, opposing this bullish path.")
    else:
        bullish.append("Deterministic direction is neutral; no breakout is confirmed.")
        bearish.append("Deterministic direction is neutral; no breakdown is confirmed.")
    return bullish[:4], bearish[:4]


def _path(trigger: float | None, target: float | None) -> list[ScenarioPoint]:
    if trigger is None:
        return []
    points = [ScenarioPoint(offset_bars=1, price=trigger)]
    if target is not None:
        points.append(ScenarioPoint(offset_bars=3, price=target))
    return points


def _scenario(
    *,
    scenario_id: str,
    title: str,
    bias: str,
    available: bool,
    condition: str,
    trigger: float | None,
    target: float | None,
    invalidation: float | None,
    confirmation: str,
    invalidation_text: str,
    evidence_for: list[str],
    evidence_against: list[str],
    unavailable_reason: str | None = None,
) -> MarketScenario:
    return MarketScenario(
        id=scenario_id,  # type: ignore[arg-type]
        title=title,
        bias=bias,  # type: ignore[arg-type]
        available=available,
        condition=condition,
        trigger=trigger,
        target=target,
        invalidation=invalidation,
        confirmation=confirmation,
        invalidation_text=invalidation_text,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        unavailable_reason=unavailable_reason,
        path=_path(trigger, target) if available else [],
    )


def _stamp_freshness(
    scenarios: list[MarketScenario], snapshot: Any, condition: MarketCondition
) -> list[MarketScenario]:
    """Attach the snapshot's structure state and freshness to every scenario."""

    data_as_of = getattr(snapshot, "data_as_of", None)
    if not isinstance(data_as_of, datetime):
        data_as_of = None
    is_stale = bool(getattr(snapshot, "is_stale", False))
    return [
        scenario.model_copy(
            update={
                "structure": condition.structure,
                "data_as_of": data_as_of,
                "data_is_stale": is_stale,
            }
        )
        for scenario in scenarios
    ]


def build_scenarios(snapshot: Any, condition: MarketCondition, plan: Any) -> list[MarketScenario]:
    last_price = _number(getattr(snapshot, "last_price", None))
    if last_price is None or last_price <= 0:
        reason = "A verified last price is unavailable; no scenario can be drawn."
        return _stamp_freshness(
            [
                _scenario(
                scenario_id=scenario_id,
                title=title,
                bias=bias,
                available=False,
                condition=condition.summary,
                trigger=None,
                target=None,
                invalidation=None,
                confirmation="Unavailable until a verified last price exists.",
                invalidation_text="Unavailable.",
                    evidence_for=[],
                    evidence_against=[],
                    unavailable_reason=reason,
                )
                for scenario_id, title, bias in (
                    ("bullish_continuation", "Bullish continuation", "BULLISH"),
                    ("bearish_reversal", "Bearish reversal", "BEARISH"),
                    ("bearish_continuation", "Bearish continuation", "BEARISH"),
                    ("bullish_reversal", "Bullish reversal", "BULLISH"),
                    ("sideways_consolidation", "Sideways consolidation", "SIDEWAYS"),
                )
            ],
            snapshot,
            condition,
        )

    supports, resistances = _levels_by_side(snapshot, last_price)
    support = supports[0] if supports else None
    next_support = supports[1] if len(supports) > 1 else None
    resistance = resistances[0] if resistances else None
    next_resistance = resistances[1] if len(resistances) > 1 else None
    bullish_evidence, bearish_evidence = _evidence(condition)
    plan_direction = _value(getattr(plan, "direction", "")).upper() if plan else ""
    plan_targets = [
        _number(getattr(target, "price", None))
        for target in (getattr(plan, "take_profits", []) or [])
    ]
    plan_targets = [target for target in plan_targets if target is not None]
    plan_stop = _number(getattr(plan, "stop_loss", None)) if plan else None

    def unavailable(
        scenario_id: str, title: str, bias: str, reason: str
    ) -> MarketScenario:
        return _scenario(
            scenario_id=scenario_id,
            title=title,
            bias=bias,
            available=False,
            condition=condition.summary,
            trigger=None,
            target=None,
            invalidation=None,
            confirmation="Unavailable until the required verified levels exist.",
            invalidation_text="Unavailable.",
            evidence_for=[],
            evidence_against=[],
            unavailable_reason=reason,
        )

    bullish_target = (
        plan_targets[-1]
        if plan_direction == "LONG" and plan_targets
        else next_resistance
    )
    bearish_target = (
        plan_targets[-1]
        if plan_direction == "SHORT" and plan_targets
        else next_support
    )

    if resistance is None:
        bullish_continuation = unavailable(
            "bullish_continuation",
            "Bullish continuation",
            "BULLISH",
            "No verified resistance above the last price; a breakout target is unavailable.",
        )
    else:
        bullish_continuation = _scenario(
            scenario_id="bullish_continuation",
            title="Bullish continuation",
            bias="BULLISH",
            available=True,
            condition=f"Price is below resistance {resistance:.2f}.",
            trigger=resistance,
            target=bullish_target,
            invalidation=support or plan_stop,
            confirmation=(
                f"A closed 15m candle above {resistance:.2f} with the level holding as support."
            ),
            invalidation_text=(
                f"A close back below {support:.2f} invalidates the bullish continuation."
                if support is not None
                else "A failed breakout without a verified support level invalidates the setup."
            ),
            evidence_for=bullish_evidence,
            evidence_against=bearish_evidence,
        )

    if support is None:
        bearish_continuation = unavailable(
            "bearish_continuation",
            "Bearish continuation",
            "BEARISH",
            "No verified support below the last price; a breakdown target is unavailable.",
        )
        bullish_reversal = unavailable(
            "bullish_reversal",
            "Bullish reversal",
            "BULLISH",
            "No verified support below the last price; a reversal base is unavailable.",
        )
    else:
        bearish_continuation = _scenario(
            scenario_id="bearish_continuation",
            title="Bearish continuation",
            bias="BEARISH",
            available=True,
            condition=f"Price is above support {support:.2f}.",
            trigger=support,
            target=bearish_target,
            invalidation=resistance or plan_stop,
            confirmation=f"A closed 15m candle below {support:.2f}.",
            invalidation_text=(
                f"A close back above {resistance:.2f} invalidates the bearish continuation."
                if resistance is not None
                else "A failed breakdown without a verified resistance level invalidates the setup."
            ),
            evidence_for=bearish_evidence,
            evidence_against=bullish_evidence,
        )
        bullish_reversal = _scenario(
            scenario_id="bullish_reversal",
            title="Bullish reversal",
            bias="BULLISH",
            available=True,
            condition=f"Support {support:.2f} is the nearest verified downside level.",
            trigger=support,
            target=resistance,
            invalidation=support,
            confirmation=(
                f"A closed 15m candle rejects {support:.2f} and momentum turns bullish."
            ),
            invalidation_text=f"A close below {support:.2f} invalidates the reversal.",
            evidence_for=bullish_evidence,
            evidence_against=bearish_evidence,
        )

    if resistance is None:
        bearish_reversal = unavailable(
            "bearish_reversal",
            "Bearish reversal",
            "BEARISH",
            "No verified resistance above the last price; a reversal ceiling is unavailable.",
        )
    else:
        bearish_reversal = _scenario(
            scenario_id="bearish_reversal",
            title="Bearish reversal",
            bias="BEARISH",
            available=True,
            condition=f"Resistance {resistance:.2f} is the nearest verified upside level.",
            trigger=resistance,
            target=support,
            invalidation=resistance,
            confirmation=(
                f"A closed 15m candle rejects {resistance:.2f} and momentum turns bearish."
            ),
            invalidation_text=f"A close above {resistance:.2f} invalidates the reversal.",
            evidence_for=bearish_evidence,
            evidence_against=bullish_evidence,
        )

    if support is None or resistance is None:
        sideways = unavailable(
            "sideways_consolidation",
            "Sideways consolidation",
            "SIDEWAYS",
            "Both a verified support and resistance are required to define the range.",
        )
    else:
        sideways = _scenario(
            scenario_id="sideways_consolidation",
            title="Sideways consolidation",
            bias="SIDEWAYS",
            available=True,
            condition=f"Verified range {support:.2f} – {resistance:.2f}.",
            trigger=None,
            target=None,
            invalidation=None,
            confirmation=(
                f"Price remains between {support:.2f} and {resistance:.2f}; wait for a close outside the range."
            ),
            invalidation_text=(
                f"A closed candle outside {support:.2f} – {resistance:.2f} invalidates the range."
            ),
            evidence_for=[
                f"Structure is {condition.structure}.",
                f"Volatility is {condition.volatility} ({condition.volatility_phase}).",
            ],
            evidence_against=[
                "A range edge break can turn consolidation into a directional move.",
            ],
        )

    return _stamp_freshness(
        [
            bullish_continuation,
            bearish_reversal,
            bearish_continuation,
            bullish_reversal,
            sideways,
        ],
        snapshot,
        condition,
    )


def build_chart_overlay(snapshot: Any, condition: MarketCondition, plan: Any) -> ChartOverlay:
    last_price = _number(getattr(snapshot, "last_price", None)) or 0.0
    return ChartOverlay(
        levels=_level_views(snapshot, last_price),
        structure=_marker_views(snapshot),
        scenarios=build_scenarios(snapshot, condition, plan),
    )
