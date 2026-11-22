"""Response envelopes for outcome review."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.trade_journal.contracts import OutcomeReview, TradeOutcome


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewEnvelope(StrictModel):
    review: OutcomeReview
    outcome: TradeOutcome


__all__ = ["ReviewEnvelope"]
