"""Deterministic entry, stop and take-profit geometry.

The planner uses only the Phase 1 snapshot and the confirmed Phase 2 evaluation. It
never fetches data, never reads a clock, and never produces an order or fill. Price
arithmetic uses Decimal with the policy's price precision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.analysis.contracts import MarketSnapshot
from app.risk.contracts import DEFAULT_RISK_POLICY, RiskPolicy
from app.strategies.contracts import StrategyDirection, TrendPullbackEvaluation
from app.trade_planning.contracts import (
    EntryZone,
    PlanCheck,
    PlanEvidence,
    PlanReason,
    TradeTarget,
)


@dataclass(frozen=True, slots=True)
class PlanGeometry:
    direction: StrategyDirection
    reference_price: Decimal
    entry_zone: EntryZone
    suggested_entry: Decimal
    stop_loss: Decimal
    stop_basis: str
    targets: list[TradeTarget]
    risk_per_unit: Decimal
    atr: Decimal
    target_conflict: bool
    invalidation_conditions: list[str] = field(default_factory=list)
    confirmation_requirements: list[str] = field(default_factory=list)
    evidence: list[PlanEvidence] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GeometryResult:
    geometry: PlanGeometry | None
    reasons: list[PlanReason] = field(default_factory=list)
    checks: list[PlanCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _decimal(value: float | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _price(value: Decimal, policy: RiskPolicy) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-policy.price_decimals), rounding=ROUND_HALF_UP)


def _ratio(value: Decimal, policy: RiskPolicy) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-policy.ratio_decimals), rounding=ROUND_HALF_UP)


def _reason(code: str, message: str, detail: str | None = None) -> PlanReason:
    return PlanReason(code=code, message=message, detail=detail)


def _last_swing(snapshot: MarketSnapshot, kind: str):
    for swing in reversed(snapshot.structure.swings):
        if swing.kind == kind:
            return swing
    return None


def _structural_levels(
    snapshot: MarketSnapshot, direction: StrategyDirection, entry: Decimal
) -> list[Decimal]:
    kind = "RESISTANCE" if direction is StrategyDirection.LONG else "SUPPORT"
    prices = [
        _decimal(float(level.price))
        for level in snapshot.structure.levels
        if level.kind.value == kind
        and (
            (direction is StrategyDirection.LONG and _decimal(float(level.price)) > entry)
            or (direction is StrategyDirection.SHORT and _decimal(float(level.price)) < entry)
        )
    ]
    return sorted(prices) if direction is StrategyDirection.LONG else sorted(prices, reverse=True)


def build_geometry(
    *,
    evaluation: TrendPullbackEvaluation,
    snapshot: MarketSnapshot,
    policy: RiskPolicy = DEFAULT_RISK_POLICY,
) -> GeometryResult:
    direction = evaluation.direction
    if direction not in {StrategyDirection.LONG, StrategyDirection.SHORT}:
        return GeometryResult(
            geometry=None,
            reasons=[_reason("STRATEGY_NOT_A_CANDIDATE", "Only confirmed LONG/SHORT candidates can be planned.")],
        )
    if snapshot.snapshot_id != evaluation.market_snapshot_id:
        return GeometryResult(
            geometry=None,
            reasons=[
                _reason(
                    "SNAPSHOT_MISMATCH",
                    "The strategy evaluation does not belong to the supplied market snapshot.",
                    f"{evaluation.market_snapshot_id} != {snapshot.snapshot_id}",
                )
            ],
        )

    atr_value = snapshot.volatility.atr14
    ema21 = snapshot.trend.ema21
    if atr_value is None or atr_value <= 0 or ema21 is None:
        return GeometryResult(
            geometry=None,
            reasons=[
                _reason(
                    "REQUIRED_EVIDENCE_MISSING",
                    "ATR14 and EMA21 are required to construct entry and stop geometry.",
                )
            ],
        )
    atr = _decimal(float(atr_value))
    ema21_d = _decimal(float(ema21))
    close = _decimal(float(snapshot.last_price))
    half_width = Decimal(str(policy.entry_zone_half_width_atr)) * atr
    structural_buffer = Decimal(str(policy.structural_buffer_atr)) * atr

    swing = _last_swing(snapshot, "low" if direction is StrategyDirection.LONG else "high")
    if swing is None:
        return GeometryResult(
            geometry=None,
            reasons=[
                _reason(
                    "MISSING_STRUCTURAL_LEVEL",
                    "The latest confirmed swing required for the stop is unavailable.",
                    f"kind={'low' if direction is StrategyDirection.LONG else 'high'}",
                )
            ],
        )
    swing_price = _decimal(float(swing.price))

    checks: list[PlanCheck] = []
    evidence: list[PlanEvidence] = [
        PlanEvidence(
            code="STRATEGY_REFERENCE",
            message=f"Confirmed {direction.value} candidate at {close}.",
            refs=[evaluation.evaluation_id, snapshot.snapshot_id],
        ),
        PlanEvidence(
            code="ATR_CONTEXT",
            message=f"ATR14={atr} drives the entry band and stop buffer.",
            refs=["volatility.atr14"],
        ),
    ]

    if direction is StrategyDirection.LONG:
        lower = max(close - half_width, swing_price + structural_buffer, ema21_d - half_width)
        upper = close
        if lower >= upper:
            return GeometryResult(
                geometry=None,
                reasons=[
                    _reason(
                        "INVALID_ENTRY_GEOMETRY",
                        "Entry-zone bounds collapsed or are inverted for a long plan.",
                        f"lower={lower}, upper={upper}",
                    )
                ],
            )
        anchor_type = "EMA21_ATR_BAND_FLOORED_BY_SWING_LOW"
        stop_basis = f"below latest confirmed swing low {swing_price} by {policy.stop_buffer_atr} ATR"
        stop_raw = min(swing_price, lower) - Decimal(str(policy.stop_buffer_atr)) * atr
    else:
        lower = close
        upper = min(close + half_width, swing_price - structural_buffer, ema21_d + half_width)
        if upper <= lower:
            return GeometryResult(
                geometry=None,
                reasons=[
                    _reason(
                        "INVALID_ENTRY_GEOMETRY",
                        "Entry-zone bounds collapsed or are inverted for a short plan.",
                        f"lower={lower}, upper={upper}",
                    )
                ],
            )
        anchor_type = "EMA21_ATR_BAND_CAPPED_BY_SWING_HIGH"
        stop_basis = f"above latest confirmed swing high {swing_price} by {policy.stop_buffer_atr} ATR"
        stop_raw = max(swing_price, upper) + Decimal(str(policy.stop_buffer_atr)) * atr

    entry_low = _price(lower, policy)
    entry_high = _price(upper, policy)
    if entry_low >= entry_high:
        return GeometryResult(
            geometry=None,
            reasons=[
                _reason(
                    "INVALID_ENTRY_GEOMETRY",
                    "Entry zone is narrower than the configured price precision.",
                    f"lower={entry_low}, upper={entry_high}",
                )
            ],
        )
    suggested_entry = _price((entry_low + entry_high) / Decimal(2), policy)
    stop_loss = _price(stop_raw, policy)
    risk_per_unit = abs(suggested_entry - stop_loss)
    if risk_per_unit <= 0:
        return GeometryResult(
            geometry=None,
            reasons=[_reason("INVALID_STOP_GEOMETRY", "Entry and stop produce a zero stop distance.")],
        )

    entry_zone = EntryZone(
        lower=entry_low,
        upper=entry_high,
        anchor=_price(ema21_d, policy),
        anchor_type=anchor_type,
        half_width_atr=policy.entry_zone_half_width_atr,
        evidence=[
            f"reference_close={close}",
            f"ema21={ema21_d}",
            f"atr14={atr}",
            f"{'swing_low' if direction is StrategyDirection.LONG else 'swing_high'}={swing_price}",
        ],
    )

    spacing = Decimal(str(policy.min_target_spacing_atr)) * atr
    levels = _structural_levels(snapshot, direction, suggested_entry)
    target_conflict = False
    targets: list[TradeTarget] = []

    def floor_for(multiple: float, previous: Decimal | None) -> Decimal:
        floor = (
            suggested_entry + Decimal(str(multiple)) * risk_per_unit
            if direction is StrategyDirection.LONG
            else suggested_entry - Decimal(str(multiple)) * risk_per_unit
        )
        if previous is None:
            return floor
        return max(floor, previous + spacing) if direction is StrategyDirection.LONG else min(
            floor, previous - spacing
        )

    def choose_target(
        label: str,
        multiple: float,
        previous: Decimal | None,
        minimum_floor: Decimal,
    ) -> tuple[Decimal, str, list[str]]:
        nonlocal target_conflict
        candidate: Decimal | None = None
        for level in levels:
            beyond_previous = (
                previous is None
                or (direction is StrategyDirection.LONG and level > previous + spacing)
                or (direction is StrategyDirection.SHORT and level < previous - spacing)
            )
            beyond_floor = (
                level >= minimum_floor
                if direction is StrategyDirection.LONG
                else level <= minimum_floor
            )
            if beyond_previous and beyond_floor:
                candidate = level
                break
        if label == "TP1":
            nearest = levels[0] if levels else None
            if nearest is not None and (
                (direction is StrategyDirection.LONG and nearest < minimum_floor)
                or (direction is StrategyDirection.SHORT and nearest > minimum_floor)
            ):
                target_conflict = True
                return minimum_floor, "RISK_FLOOR_STRUCTURE_CONFLICT", [f"structure_level={nearest}"]
        if candidate is not None:
            method = "STRUCTURE_LEVEL"
            return candidate, method, [f"structure_level={candidate}"]
        multiplier = f"{multiple:.2f}R"
        return minimum_floor, "RISK_MULTIPLE", [multiplier]

    def target_price(value: Decimal) -> Decimal:
        rounding = ROUND_CEILING if direction is StrategyDirection.LONG else ROUND_FLOOR
        return value.quantize(Decimal(1).scaleb(-policy.price_decimals), rounding=rounding)

    tp1_floor = floor_for(max(policy.min_rr_tp1, policy.tp1_risk_multiple), None)
    tp1, method1, refs1 = choose_target("TP1", policy.tp1_risk_multiple, None, tp1_floor)
    tp1 = target_price(tp1)
    tp2_floor = floor_for(policy.tp2_risk_multiple, tp1)
    tp2, method2, refs2 = choose_target("TP2", policy.tp2_risk_multiple, tp1, tp2_floor)
    tp2 = target_price(tp2)
    tp3_floor = floor_for(policy.tp3_risk_multiple, tp2)
    tp3, method3, refs3 = choose_target("TP3", policy.tp3_risk_multiple, tp2, tp3_floor)
    tp3 = target_price(tp3)

    for label, price, method, refs in (
        ("TP1", tp1, method1, refs1),
        ("TP2", tp2, method2, refs2),
        ("TP3", tp3, method3, refs3),
    ):
        multiple = _ratio(abs(price - suggested_entry) / risk_per_unit, policy)
        targets.append(
            TradeTarget(
                label=label,
                price=price,
                risk_multiple=multiple,
                atr_distance=round(float(abs(price - suggested_entry) / atr), 4),
                method=method,
                evidence=[f"target={price}", f"risk_multiple={multiple}", *refs],
            )
        )

    checks.append(
        PlanCheck(
            name="entry_zone_bounds",
            passed=entry_low < entry_high and entry_low <= suggested_entry <= entry_high,
            detail=f"lower={entry_low}, suggested={suggested_entry}, upper={entry_high}",
        )
    )
    checks.append(
        PlanCheck(
            name="stop_side",
            passed=(stop_loss < suggested_entry)
            if direction is StrategyDirection.LONG
            else (stop_loss > suggested_entry),
            detail=f"stop={stop_loss}, suggested_entry={suggested_entry}",
        )
    )
    checks.append(
        PlanCheck(
            name="target_ordering",
            passed=(tp1 < tp2 < tp3)
            if direction is StrategyDirection.LONG
            else (tp1 > tp2 > tp3),
            detail=f"tp1={tp1}, tp2={tp2}, tp3={tp3}",
        )
    )
    checks.append(
        PlanCheck(
            name="target_sides",
            passed=all(
                target > suggested_entry
                if direction is StrategyDirection.LONG
                else target < suggested_entry
                for target in (tp1, tp2, tp3)
            ),
            detail=f"entry={suggested_entry}, targets={tp1},{tp2},{tp3}",
        )
    )

    invalidation = [
        (
            f"Closed M15 close below {stop_loss} invalidates the long structural setup."
            if direction is StrategyDirection.LONG
            else f"Closed M15 close above {stop_loss} invalidates the short structural setup."
        ),
        f"Phase 2 candidate expiry at {evaluation.valid_until.isoformat()}.",
        "Entry outside the declared zone expires the plan; a new plan is required.",
    ]
    confirmations = [
        "The Phase 2 closed-bar confirmation must remain CONFIRMED.",
        "Only closed M15 candles may trigger invalidation or entry.",
        "A real fill price must be recorded from an execution record; this plan has none.",
    ]
    evidence.extend(
        [
            PlanEvidence(
                code="ENTRY_ZONE",
                message=(
                    f"{anchor_type}: [{entry_low}, {entry_high}] around reference {close}; "
                    f"suggested entry is the zone midpoint."
                ),
                refs=entry_zone.evidence,
            ),
            PlanEvidence(
                code="STOP_STRUCTURE",
                message=f"Stop {stop_loss} is {stop_basis}, using ATR buffer {policy.stop_buffer_atr}.",
                refs=[f"swing={swing_price}", f"atr={atr}"],
            ),
            *[
                PlanEvidence(
                    code=f"TARGET_{target.label[-1]}",
                    message=f"{target.label} {target.price} via {target.method} at {target.atr_distance} ATR.",
                    refs=target.evidence,
                )
                for target in targets
            ],
        ]
    )
    warnings = [
        "Targets are projections, not promises; no target is guaranteed to be reached.",
        "The plan is hypothetical geometry only; no order was placed and no fill exists.",
    ]
    return GeometryResult(
        geometry=PlanGeometry(
            direction=direction,
            reference_price=close,
            entry_zone=entry_zone,
            suggested_entry=suggested_entry,
            stop_loss=stop_loss,
            stop_basis=stop_basis,
            targets=targets,
            risk_per_unit=risk_per_unit,
            atr=atr,
            target_conflict=target_conflict,
            invalidation_conditions=invalidation,
            confirmation_requirements=confirmations,
            evidence=evidence,
        ),
        checks=checks,
        warnings=warnings,
    )
