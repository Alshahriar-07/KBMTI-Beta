"""Journal orchestration: setup actions, paper/manual records and monitoring."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.errors import ApiError, NotFoundError, ValidationError
from app.outcomes.analyzer import analyze_outcome
from app.outcomes.metrics import net_r_multiple
from app.persistence.repositories import CandleRepository
from app.trade_journal.contracts import (
    JournalEvent,
    JournalTrade,
    MonitoringGuidance,
    MonitoringResult,
    OutcomeCategory,
    SetupAction,
    SetupActionRequest,
    SetupActionType,
    TradeCreateRequest,
    TradeEventRequest,
    TradeEventType,
    TradeMode,
    TradeStatus,
)
from app.trade_journal.repository import JournalRepository
from app.trade_planning.service import TradePlanningService


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JournalService:
    def __init__(
        self,
        *,
        planning: TradePlanningService,
        repository: JournalRepository,
        candles: CandleRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._planning = planning
        self._repository = repository
        self._candles = candles
        self._clock = clock or _utc_now

    # -- setup actions ------------------------------------------------------
    def record_setup_action(self, plan_id: str, action: SetupActionType, request: SetupActionRequest) -> dict[str, Any]:
        plan = self._planning.get_plan(plan_id)
        if plan.plan_status.value not in {"PLAN_READY", "PLAN_REVIEW_REQUIRED"}:
            raise ApiError(
                "SETUP_NOT_ACTIONABLE",
                f"Setup {plan_id} is {plan.plan_status.value} and cannot be accepted.",
                409,
                {"plan_id": plan_id, "plan_status": plan.plan_status.value},
            )
        row = self._repository.insert_action(
            plan_id,
            action.value,
            request.actor.strip() or "local_operator",
            request.note,
            {
                "plan_id": plan_id,
                "action": action.value,
                "plan_status": plan.plan_status.value,
                "strategy_version": plan.strategy_version,
                "strategy_validation_status": plan.strategy_validation_status.value,
            },
        )
        action_row = {key: value for key, value in row.items() if key != "payload_json"}
        return {
            "action": SetupAction.model_validate(action_row).model_dump(mode="json"),
            "plan_status": plan.plan_status.value,
            "execution_eligibility": plan.execution_eligibility.value,
            "note": "Accepting a setup records a paper/manual intent only; no order is placed.",
        }

    def actions(self, plan_id: str) -> dict[str, Any]:
        rows = self._repository.actions(plan_id)
        return {
            "plan_id": plan_id,
            "actions": [SetupAction.model_validate(row).model_dump(mode="json") for row in rows],
            "count": len(rows),
        }

    # -- records ------------------------------------------------------------
    def create_record(self, request: TradeCreateRequest) -> JournalTrade:
        plan = self._planning.get_plan(request.plan_id)
        if plan.plan_status.value in {"PLAN_INVALID", "PLAN_EXPIRED"}:
            raise ValidationError(f"Plan {request.plan_id} is {plan.plan_status.value} and cannot be journaled.")
        latest = self._repository.latest_action(request.plan_id)
        if latest is None or latest["action"] != SetupActionType.ACCEPT.value:
            raise ApiError(
                "SETUP_NOT_ACCEPTED",
                "The setup must be accepted before a paper/manual record can be created.",
                409,
                {"plan_id": request.plan_id, "latest_action": latest["action"] if latest else None},
            )
        if latest["action"] != SetupActionType.ACCEPT.value:
            raise ApiError("SETUP_NOT_ACCEPTED", "The setup was not accepted.", 409)

        entry = request.actual_entry
        if request.mode is TradeMode.MANUAL and entry is None:
            raise ValidationError("A manual record requires the actual entry price that was supplied.")
        if entry is None:
            entry = plan.suggested_entry
        if entry <= 0:
            raise ValidationError("Entry price must be positive.")
        if request.fees < 0 or request.slippage < 0:
            raise ValidationError("Fees and slippage cannot be negative.")

        now = self._clock()
        trade_id = f"rec_{uuid.uuid4().hex[:24]}"
        row = {
            "trade_id": trade_id,
            "plan_id": plan.plan_id,
            "mode": request.mode.value,
            "status": TradeStatus.OPEN.value,
            "direction": plan.direction,
            "symbol": plan.symbol,
            "timeframe": plan.timeframe,
            "strategy_id": plan.strategy_id,
            "strategy_version": plan.strategy_version,
            "strategy_validation_status": plan.strategy_validation_status.value,
            "qwen_model_version": None,
            "planned_entry": str(plan.suggested_entry),
            "actual_entry": str(entry),
            "stop_loss": str(plan.stop_loss),
            "tp1": str(plan.take_profits[0].price),
            "tp2": str(plan.take_profits[1].price),
            "tp3": str(plan.take_profits[2].price),
            "exit_price": None,
            "fees": str(request.fees),
            "slippage": str(request.slippage),
            "outcome": None,
            "r_multiple": None,
            "mfe": None,
            "mae": None,
            "opened_at": now.isoformat(),
            "closed_at": None,
            "notes": request.notes,
            "payload_json": "{}",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self._repository.insert_trade(row)
        self._repository.insert_event(
            trade_id,
            TradeEventType.ENTRY.value,
            price=str(entry),
            note=(
                "Simulated paper entry; no order was placed."
                if request.mode is TradeMode.PAPER
                else "Manually supplied entry; no order was placed by KBMTI."
            ),
            occurred_at=now.isoformat(),
            payload={"mode": request.mode.value, "actor": request.actor},
        )
        return self.get_record(trade_id)

    def get_record(self, trade_id: str) -> JournalTrade:
        row = self._repository.get_trade(trade_id)
        if row is None:
            raise NotFoundError(f"Journal record '{trade_id}' was not found.", {"trade_id": trade_id})
        return self._to_contract(row)

    def list_records(self, *, status: str | None = None, limit: int = 100) -> dict[str, Any]:
        if status:
            try:
                TradeStatus(status)
            except ValueError as exc:
                raise ValidationError("Unknown journal status.", {"status": status}) from exc
        rows = self._repository.list_trades(status=status, limit=limit)
        return {
            "records": [self._to_contract(row).model_dump(mode="json") for row in rows],
            "count": len(rows),
            "open": self._repository.count_trades(TradeStatus.OPEN.value),
            "closed": self._repository.count_trades(TradeStatus.CLOSED.value),
            "expired": self._repository.count_trades(TradeStatus.EXPIRED.value),
            "note": "Paper/manual records only. No position size or live execution exists.",
        }

    def append_event(self, trade_id: str, request: TradeEventRequest) -> JournalTrade:
        row = self._repository.get_trade(trade_id)
        if row is None:
            raise NotFoundError(f"Journal record '{trade_id}' was not found.", {"trade_id": trade_id})
        if row["status"] != TradeStatus.OPEN.value:
            raise ApiError(
                "RECORD_CLOSED",
                f"Record is {row['status']}; only notes can be appended.",
                409,
                {"trade_id": trade_id},
            )
        if request.event_type is TradeEventType.ENTRY:
            raise ApiError("INVALID_TRANSITION", "An entry event is created with the record.", 409)
        occurred = request.occurred_at or self._clock()
        price = request.price
        if request.event_type in {
            TradeEventType.EXIT,
            TradeEventType.STOP_HIT,
            TradeEventType.TP_HIT,
            TradeEventType.PARTIAL_EXIT,
        } and price is None:
            raise ValidationError("A price is required for this event.")
        if request.event_type is TradeEventType.STOP_HIT and price is None:
            price = Decimal(row["stop_loss"])

        self._repository.insert_event(
            trade_id,
            request.event_type.value,
            price=str(price) if price is not None else None,
            note=request.note,
            occurred_at=occurred.isoformat(),
            payload={"actor": request.actor},
        )
        if request.event_type in {TradeEventType.NOTE, TradeEventType.PARTIAL_EXIT}:
            return self.get_record(trade_id)

        closed_row = dict(row)
        closed_row["closed_at"] = occurred.isoformat()
        if request.event_type is TradeEventType.INVALIDATED:
            updates = {
                "status": TradeStatus.EXPIRED.value,
                "closed_at": occurred.isoformat(),
                "outcome": OutcomeCategory.INVALID_SETUP.value,
                "updated_at": _now_iso(),
            }
        else:
            assert price is not None
            entry = Decimal(str(row["actual_entry"] or row["planned_entry"]))
            stop = Decimal(row["stop_loss"])
            net_r, _, _ = net_r_multiple(
                direction=row["direction"],
                entry=entry,
                stop=stop,
                exit_price=price,
                fees=Decimal(row["fees"]),
                slippage=Decimal(row["slippage"]),
            )
            category = OutcomeCategory.INSUFFICIENT_DATA
            if net_r is not None:
                category = (
                    OutcomeCategory.SUCCESS
                    if net_r > Decimal("0.05")
                    else OutcomeCategory.LOSS
                    if net_r < Decimal("-0.05")
                    else OutcomeCategory.BREAKEVEN
                )
            updates = {
                "status": TradeStatus.CLOSED.value,
                "exit_price": str(price),
                "closed_at": occurred.isoformat(),
                "outcome": category.value,
                "r_multiple": str(net_r) if net_r is not None else None,
                "updated_at": _now_iso(),
            }
            closed_row.update(
                {
                    "exit_price": str(price),
                    "outcome": category.value,
                    "r_multiple": str(net_r) if net_r is not None else None,
                }
            )
        # Recompute excursions from recorded candles when available.
        result = analyze_outcome(
            trade=closed_row,
            events=self._repository.events(trade_id),
            candles=self._holding_candles(closed_row),
        )
        updates.update(
            {
                "mfe": str(result.mfe_r) if result.mfe_r is not None else None,
                "mae": str(result.mae_r) if result.mae_r is not None else None,
            }
        )
        self._repository.update_trade(trade_id, updates)
        return self.get_record(trade_id)

    def monitor(self, trade_id: str, price: Decimal | None = None) -> MonitoringResult:
        row = self._repository.get_trade(trade_id)
        if row is None:
            raise NotFoundError(f"Journal record '{trade_id}' was not found.", {"trade_id": trade_id})
        if price is None:
            latest = self._latest_price(row)
            if latest is None:
                raise ValidationError("No current price is available; supply a price explicitly.")
            price = latest
        if price <= 0:
            raise ValidationError("Price must be positive.")
        status = row["status"]
        direction = row["direction"]
        stop = Decimal(row["stop_loss"])
        tp1 = Decimal(row["tp1"])
        if status != TradeStatus.OPEN.value:
            return MonitoringResult(
                trade_id=trade_id,
                guidance=MonitoringGuidance.RE_EVALUATE,
                price=price,
                reasons=[f"Record is {status}; monitoring is complete."],
                next_check="Review the outcome instead of monitoring this record.",
            )
        plan = None
        try:
            plan = self._planning.get_plan(row["plan_id"])
        except Exception:  # noqa: BLE001 - lifecycle still works from the journal row
            plan = None
        if plan is not None and self._clock() >= plan.expires_at:
            return MonitoringResult(
                trade_id=trade_id,
                guidance=MonitoringGuidance.EXPIRED,
                price=price,
                reasons=[f"Plan expired at {plan.expires_at.isoformat()}."],
                next_check="Do not enter a new position from this plan; request a fresh setup.",
            )
        stop_hit = price <= stop if direction == "LONG" else price >= stop
        tp1_reached = price >= tp1 if direction == "LONG" else price <= tp1
        if stop_hit:
            return MonitoringResult(
                trade_id=trade_id,
                guidance=MonitoringGuidance.STOP_HIT,
                price=price,
                reasons=[f"Price {price} reached the recorded stop {stop}."],
                invalidation_triggered=True,
                stop_hit=True,
                next_check="Record the stop event; do not widen the stop.",
            )
        if tp1_reached:
            return MonitoringResult(
                trade_id=trade_id,
                guidance=MonitoringGuidance.TP1_REACHED,
                price=price,
                reasons=[f"Price {price} reached TP1 {tp1}. The plan permits a partial-exit review."],
                tp1_reached=True,
                next_check="Record a partial exit or hold only according to the predeclared plan.",
            )
        return MonitoringResult(
            trade_id=trade_id,
            guidance=MonitoringGuidance.HOLD,
            price=price,
            reasons=[f"Price is between the stop {stop} and TP1 {tp1}."],
            next_check="Re-check only on a closed M15 candle or a new recorded event.",
        )

    # -- helpers ------------------------------------------------------------
    def _to_contract(self, row: dict[str, Any]) -> JournalTrade:
        events = [
            JournalEvent.model_validate(event) for event in self._repository.events(row["trade_id"])
        ]
        return JournalTrade(
            **{key: row[key] for key in (
                "trade_id",
                "plan_id",
                "mode",
                "status",
                "direction",
                "symbol",
                "timeframe",
                "strategy_id",
                "strategy_version",
                "strategy_validation_status",
                "qwen_model_version",
                "planned_entry",
                "actual_entry",
                "stop_loss",
                "tp1",
                "tp2",
                "tp3",
                "exit_price",
                "fees",
                "slippage",
                "outcome",
                "r_multiple",
                "mfe",
                "mae",
                "opened_at",
                "closed_at",
                "notes",
            )},
            events=events,
        )

    def _holding_candles(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        if self._candles is None or not row.get("closed_at"):
            return []
        try:
            start = int(datetime.fromisoformat(str(row["opened_at"])).timestamp())
            end = int(datetime.fromisoformat(str(row["closed_at"])).timestamp())
            return self._candles.between(row["symbol"], row["timeframe"], start, end)
        except Exception:  # noqa: BLE001 - metrics degrade rather than fail a close
            return []

    def _latest_price(self, row: dict[str, Any]) -> Decimal | None:
        if self._candles is None:
            return None
        try:
            candles = self._candles.recent(row["symbol"], row["timeframe"], limit=1, source="binance")
            return Decimal(str(candles[-1]["close"])) if candles else None
        except Exception:  # noqa: BLE001
            return None


__all__ = ["JournalService"]
