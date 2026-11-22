"""Outcome review service: compute, review and gate dataset eligibility."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.errors import NotFoundError, ValidationError
from app.outcomes.analyzer import analyze_outcome
from app.persistence.repositories import CandleRepository, ForecastRepository
from app.trade_journal.contracts import (
    OutcomeCategory,
    OutcomeReview,
    OutcomeReviewRequest,
    OutcomeReviewStatus,
    TradeOutcome,
    TradeStatus,
)
from app.trade_journal.repository import JournalRepository


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class OutcomeService:
    def __init__(
        self,
        *,
        journal: JournalRepository,
        candles: CandleRepository | None = None,
        forecasts: ForecastRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._journal = journal
        self._candles = candles
        self._forecasts = forecasts
        self._clock = clock or (lambda: datetime.now(UTC))

    def get_outcome(self, trade_id: str) -> TradeOutcome:
        row = self._journal.get_trade(trade_id)
        if row is None:
            raise NotFoundError(f"Journal record '{trade_id}' was not found.", {"trade_id": trade_id})
        return self._analyze(row)

    def list_outcomes(self, *, category: str | None = None, limit: int = 100) -> dict[str, Any]:
        rows = self._journal.list_trades(limit=max(1, min(int(limit), 500)))
        outcomes = [self._analyze(row) for row in rows if row["status"] != TradeStatus.OPEN.value]
        if category:
            try:
                wanted = OutcomeCategory(category)
            except ValueError as exc:
                raise ValidationError("Unknown outcome category.", {"category": category}) from exc
            outcomes = [item for item in outcomes if item.category is wanted]
        return {
            "outcomes": [item.model_dump(mode="json") for item in outcomes],
            "count": len(outcomes),
            "note": "Outcomes are computed from journal records; they are not profitability claims.",
        }

    def review(self, trade_id: str, request: OutcomeReviewRequest) -> OutcomeReview:
        row = self._journal.get_trade(trade_id)
        if row is None:
            raise NotFoundError(f"Journal record '{trade_id}' was not found.", {"trade_id": trade_id})
        if row["status"] == TradeStatus.OPEN.value:
            raise ValidationError("An open record has no outcome to review.")
        reviewer = request.reviewer.strip()
        if not reviewer:
            raise ValidationError("A reviewer is required.")
        outcome = self._analyze(row)
        eligible = (
            request.status is OutcomeReviewStatus.APPROVED_FOR_DATASET
            and outcome.category
            in {OutcomeCategory.SUCCESS, OutcomeCategory.LOSS, OutcomeCategory.BREAKEVEN}
            and outcome.r_multiple is not None
        )
        stored = self._journal.upsert_review(
            trade_id,
            status=request.status.value,
            reviewer=reviewer,
            note=request.note,
            findings=[finding.model_dump(mode="json") for finding in outcome.findings],
            dataset_eligible=eligible,
        )
        return OutcomeReview(
            trade_id=stored["trade_id"],
            status=stored["status"],
            reviewer=stored["reviewer"],
            note=stored["note"],
            findings=outcome.findings,
            dataset_eligible=stored["dataset_eligible"],
            created_at=stored["created_at"],
            updated_at=stored["updated_at"],
        )

    def get_review(self, trade_id: str) -> OutcomeReview | None:
        stored = self._journal.get_review(trade_id)
        if stored is None:
            return None
        return OutcomeReview(
            trade_id=stored["trade_id"],
            status=stored["status"],
            reviewer=stored["reviewer"],
            note=stored["note"],
            findings=stored["findings"],
            dataset_eligible=stored["dataset_eligible"],
            created_at=stored["created_at"],
            updated_at=stored["updated_at"],
        )

    def summary(self) -> dict[str, Any]:
        rows = self._journal.list_trades(limit=500)
        closed = [row for row in rows if row["status"] != TradeStatus.OPEN.value]
        reviewed = [row for row in closed if self._journal.get_review(row["trade_id"]) is not None]
        approved = [row for row in closed if (self._journal.get_review(row["trade_id"]) or {}).get("dataset_eligible")]
        categories: dict[str, int] = {}
        for row in closed:
            category = self._analyze(row).category.value
            categories[category] = categories.get(category, 0) + 1
        return {
            "records": len(rows),
            "closed_or_expired": len(closed),
            "reviewed": len(reviewed),
            "approved_for_dataset": len(approved),
            "categories": categories,
            "note": "No aggregate edge or profitability is inferred from these counts.",
        }

    # -- helpers ------------------------------------------------------------
    def _analyze(self, row: dict[str, Any]) -> TradeOutcome:
        return analyze_outcome(
            trade=row,
            events=self._journal.events(row["trade_id"]),
            candles=self._holding_candles(row),
            patron_alignment=self._patron_alignment(row),
        )

    def _patron_alignment(self, row: dict[str, Any]) -> dict[str, Any] | None:
        if self._forecasts is None:
            return None
        try:
            forecast = self._forecasts.latest_before(
                row["symbol"], row["timeframe"], str(row["opened_at"])
            )
            if forecast is None:
                return None
            evaluations = self._forecasts.evaluations(forecast["id"])
            predicted = next(
                (str(item.get("predicted_direction") or "") for item in evaluations if item.get("predicted_direction")),
                "",
            )
            correct = [item for item in evaluations if item.get("success") is not None]
            return {
                "forecast_id": forecast["id"],
                "evaluated_steps": len(correct),
                "direction_accuracy": (
                    sum(1 for item in correct if item.get("success")) / len(correct)
                    if correct
                    else None
                ),
                "predicted_direction": predicted,
                "forecast_created_at": forecast["created_at"],
            }
        except Exception:  # noqa: BLE001 - alignment must not block outcome calculation
            return None

    def _holding_candles(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        if self._candles is None or not row.get("closed_at"):
            return []
        try:
            start = int(datetime.fromisoformat(str(row["opened_at"])).timestamp())
            end = int(datetime.fromisoformat(str(row["closed_at"])).timestamp())
            return self._candles.between(row["symbol"], row["timeframe"], start, end)
        except Exception:  # noqa: BLE001 - metrics degrade to null
            return []


__all__ = ["OutcomeService"]
