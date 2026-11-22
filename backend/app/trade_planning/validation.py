"""Plan-geometry validation, separate from risk-policy validation."""

from __future__ import annotations

from datetime import datetime

from app.analysis.contracts import MarketSnapshot
from app.risk.contracts import RiskPolicy
from app.strategies.contracts import StrategyDirection, TrendPullbackEvaluation
from app.trade_planning.contracts import PlanCheck
from app.trade_planning.planner import PlanGeometry


def validate_geometry(
    *,
    geometry: PlanGeometry,
    evaluation: TrendPullbackEvaluation,
    snapshot: MarketSnapshot,
    now: datetime,
    policy: RiskPolicy,
) -> list[PlanCheck]:
    long = geometry.direction is StrategyDirection.LONG
    checks = [
        PlanCheck(
            name="snapshot_link",
            passed=snapshot.snapshot_id == evaluation.market_snapshot_id,
            detail=f"snapshot={snapshot.snapshot_id}, evaluation_snapshot={evaluation.market_snapshot_id}",
        ),
        PlanCheck(
            name="strategy_direction",
            passed=evaluation.direction is geometry.direction,
            detail=f"evaluation={evaluation.direction.value}, geometry={geometry.direction.value}",
        ),
        PlanCheck(
            name="entry_bounds",
            passed=geometry.entry_zone.lower < geometry.entry_zone.upper
            and geometry.entry_zone.lower <= geometry.suggested_entry <= geometry.entry_zone.upper,
            detail=f"lower={geometry.entry_zone.lower}, upper={geometry.entry_zone.upper}",
        ),
        PlanCheck(
            name="stop_geometry",
            passed=geometry.risk_per_unit > 0
            and (
                geometry.stop_loss < geometry.suggested_entry
                if long
                else geometry.stop_loss > geometry.suggested_entry
            ),
            detail=f"stop={geometry.stop_loss}, entry={geometry.suggested_entry}",
        ),
        PlanCheck(
            name="target_count_and_order",
            passed=len(geometry.targets) == 3
            and all(
                (target.price > geometry.suggested_entry if long else target.price < geometry.suggested_entry)
                for target in geometry.targets
            )
            and (
                (geometry.targets[0].price < geometry.targets[1].price < geometry.targets[2].price)
                if long
                else (geometry.targets[0].price > geometry.targets[1].price > geometry.targets[2].price)
            ),
            detail="; ".join(f"{target.label}={target.price}" for target in geometry.targets),
        ),
        PlanCheck(
            name="expiry_after_data",
            passed=now < evaluation.valid_until,
            detail=f"now={now.isoformat()}, strategy_valid_until={evaluation.valid_until.isoformat()}",
        ),
        PlanCheck(
            name="price_precision",
            passed=policy.price_decimals >= 0,
            detail=f"price_decimals={policy.price_decimals}",
        ),
    ]
    return checks


def all_passed(checks: list[PlanCheck]) -> bool:
    return all(check.passed for check in checks)
