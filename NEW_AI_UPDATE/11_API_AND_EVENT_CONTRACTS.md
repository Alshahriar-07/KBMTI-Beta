# 11 — Proposed API and Event Contracts

These are conceptual additive contracts. Inspect the existing backend and naming conventions before implementing. Do not break existing endpoints or response shapes.

## 1. Suggested read endpoints

- `GET /api/v1/market/context`
- `GET /api/v1/market/analysis`
- `GET /api/v1/patron/forecast` (read-only adapter to existing output)
- `GET /api/v1/strategies`
- `GET /api/v1/trade-assistant/current`
- `GET /api/v1/trades`
- `GET /api/v1/trades/{trade_id}`
- `GET /api/v1/trades/{trade_id}/review`
- `GET /api/v1/learning/status`
- `GET /api/v1/models/active`

## 2. Suggested user actions

- `POST /api/v1/trade-assistant/evaluate`
- `POST /api/v1/setups/{setup_id}/accept`
- `POST /api/v1/setups/{setup_id}/reject`
- `POST /api/v1/trades/{trade_id}/event`
- `POST /api/v1/trades/{trade_id}/review`
- `POST /api/v1/learning/datasets/prepare`
- `POST /api/v1/learning/jobs` (permission-gated, offline candidate only)
- `POST /api/v1/models/{candidate_id}/promote` (explicit operator approval required)

No endpoint should allow the LLM to execute arbitrary shell commands or place exchange orders.

## 3. Common response metadata

Every analysis/setup response should include:
- `request_id`;
- `generated_at`;
- `data_as_of`;
- `is_stale`;
- `symbol`;
- `timeframe`;
- `strategy_version`;
- `patron_model_version` when relevant;
- `qwen_model_version`;
- `risk_engine_version`;
- `evidence_refs`;
- `warnings`.

## 4. Decision schema

```json
{
  "action": "WAIT",
  "market_regime": "uncertain",
  "directional_bias": "neutral",
  "strategy_id": null,
  "setup_id": null,
  "entry_plan": null,
  "risk_plan": null,
  "confirmation_conditions": [],
  "invalidation_conditions": [],
  "reasons_for": [],
  "reasons_against": [],
  "evidence_refs": [],
  "uncertainty_notes": [],
  "warnings": []
}
```

## 5. Event stream

If the backend already uses SSE, extend its established pattern. Suggested events:
- `market_context_updated`;
- `analysis_updated`;
- `setup_proposed`;
- `setup_waiting_confirmation`;
- `setup_invalidated`;
- `trade_state_changed`;
- `trade_closed`;
- `outcome_review_ready`;
- `learning_candidate_ready`;
- `model_candidate_evaluated`.

Events must include IDs and timestamps. Avoid sending secrets or full account details.

## 6. Error states

Use explicit machine-readable codes:
- `MARKET_DATA_STALE`;
- `PATRON_UNAVAILABLE`;
- `QWEN_UNAVAILABLE`;
- `RISK_VALIDATION_FAILED`;
- `NO_ELIGIBLE_STRATEGY`;
- `SETUP_EXPIRED`;
- `INSUFFICIENT_ACCOUNT_INPUTS`;
- `LEARNING_JOB_NOT_APPROVED`.

A failed dependency must result in a safe degraded state, not a fabricated setup.
