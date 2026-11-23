# Phase 3 — Trade planning, geometry and deterministic risk engine

**Status:** Implementation complete — **acceptance recommended, with the Phase 2 strategy
gate still PENDING**. No order execution, fill, account balance or position size exists.
**Code commit:** `0d102da`
**Scope:** BTCUSDT M15 only.
**Policy:** `risk-policy-1.0.0`

## 1. Implementation summary

Phase 3 turns a confirmed Phase 2 `trend_pullback` candidate into a deterministic,
auditable and explicitly non-executable trade plan. It adds:

- `app/trade_planning` — entry zone, suggested entry, structural ATR stop, TP1–TP3,
  R:R, invalidation, expiry, calculation evidence, plan validation and lifecycle.
- `app/risk` — a pure, versioned risk engine that independently re-checks data,
  confirmation, entry/stop/target geometry, stop distance and minimum R:R.
- `trade_plans` persistence with an audit payload and status updates.
- Read-only endpoints for the current plan, a persisted plan and the current risk view.
- 25 focused tests, plus the unchanged Phase 0–2 suite.

Every plan carries:

```text
strategy_validation_status = PENDING
plan_status               = PLAN_REVIEW_REQUIRED   (when technically valid)
execution_eligibility     = REVIEW_REQUIRED
position_size_status      = NOT_CALCULATED
actual_fill_price         = null
position_size             = null
```

The plan is hypothetical geometry. It is not an order, not a recommendation, and not
evidence of strategy validity or profitability.

## 2. Architecture and data flow

```text
AnalysisService.snapshot()            Phase 1 MarketSnapshot
        │
        ▼
StrategyService.evaluate()            Phase 2 TrendPullbackEvaluation
        │  snapshot_id equality is checked; one aligned refresh is retried
        ▼
build_geometry()                      pure planner, Decimal price math
        │  EntryZone + stop + targets + evidence + checks
        ▼
validate_geometry()                   plan-level invariants
        │
        ▼
RiskService.assess()                  pure risk engine, versioned policy
        │  RiskAssessment + Decimal R:R + eligibility
        ▼
TradePlan + TradePlanningResult       lifecycle, caching, persistence
        │
        ├── GET /api/v1/planning/current
        ├── GET /api/v1/planning/plans/{plan_id}
        └── GET /api/v1/risk/current
```

The planner and risk engine are pure functions: no clock, network, repository or LLM
access. `TradePlanningService` is the only orchestrator. All new services are optional
dependencies in the container, so a test or deployment without Phase 3 still runs.

## 3. Entry zone and suggested entry

For a **LONG**:

```text
lower = max(close − 0.10 ATR, swing_low + 0.05 ATR, EMA21 − 0.10 ATR)
upper = close
suggested_entry = midpoint(lower, upper)
```

For a **SHORT**:

```text
lower = close
upper = min(close + 0.10 ATR, swing_high − 0.05 ATR, EMA21 + 0.10 ATR)
suggested_entry = midpoint(lower, upper)
```

- The latest confirmed Phase 1 swing is required. A missing swing produces
  `MISSING_STRUCTURAL_LEVEL`; a collapsed/inverted band produces
  `INVALID_ENTRY_GEOMETRY`.
- The zone anchor is EMA21 with ATR half-width, floored/capped by the structural swing.
- `reference_price` is the snapshot close; `suggested_entry` is a planning reference,
  not a fill. `actual_fill_price` is always `null`.
- Prices are rounded with `ROUND_HALF_UP` to the policy's two decimals. Entry and stop
  are calculated with `Decimal`, never binary floats.
- Entry outside the declared zone is a lifecycle event: the plan becomes
  `PLAN_EXPIRED` with `ENTRY_MISSED`, rather than being re-priced or chased.

## 4. Structural ATR stop

The stop is placed beyond the latest confirmed swing by a fixed ATR buffer:

- **LONG:** `min(swing_low, entry_zone.lower) − 0.15 ATR`
- **SHORT:** `max(swing_high, entry_zone.upper) + 0.15 ATR`

The stop is never moved to manufacture a better R:R. If the stop is too close
(`< 0.10 ATR`) the plan is blocked with `INVALID_STOP_GEOMETRY`; if it is too wide
(`> 2.50 ATR`) it is blocked with `STOP_DISTANCE_EXCEEDED`. The stop basis and the
swing/ATR references are stored in `stop_basis` and evidence.

## 5. Take-profit targets

Three targets are always produced, ordered and separated by at least `0.35 ATR`:

| Target | Floor | Preferred method |
|---|---|---|
| TP1 | `max(1.0R, nearest structure)` | `STRUCTURE_LEVEL` when it clears the floor; otherwise `RISK_MULTIPLE` |
| TP2 | `1.5R` and at least TP1 + spacing | `STRUCTURE_LEVEL` when beyond TP1 + spacing; otherwise `RISK_MULTIPLE` |
| TP3 | `2.0R` and at least TP2 + spacing | `STRUCTURE_LEVEL` when beyond TP2 + spacing; otherwise `RISK_MULTIPLE` |

Only confirmed Phase 1 structure levels on the profit side of the suggested entry are
considered. If the nearest structural level for TP1 sits **before** the minimum 1R
floor, TP1 uses the floor and the method is recorded as
`RISK_FLOOR_STRUCTURE_CONFLICT`; the conflict also blocks risk validation with
`TARGET_STRUCTURE_CONFLICT`. Targets are projected prices, never promises.

The default fixture demonstrates the complete geometry:

```text
LONG  zone 31880.81–31883.00  entry 31881.91
      stop 31847.72 (1.56 ATR)  ATR 21.88909519  swing low 31851
      TP1 31959.00  TP2 31966.67  TP3 31974.34
      R:R 2.2548 / 2.4791 / 2.7034
```

## 6. Risk/reward and Decimal arithmetic

`RiskReward` records entry-to-stop distance, risk per unit, each reward distance and
`rr_tp1`–`rr_tp3`. Risk and reward are computed as `Decimal`, then quantized:

- prices: 2 decimals, `ROUND_HALF_UP`;
- ratios: 4 decimals, `ROUND_HALF_UP`;
- ATR distances: 4 decimal places for evidence.

The risk engine requires `rr_tp1 >= 1.0`. It never widens the stop or lowers TP1 to
make that check pass; a failing plan is blocked.

## 7. Risk policy and reason codes

`RiskPolicy` is frozen and versioned (`risk-policy-1.0.0`). Any value change requires a
version bump. Parameters include entry half-width (`0.10 ATR`), structural buffer
(`0.05 ATR`), stop buffer (`0.15 ATR`), minimum/maximum stop (`0.10 / 2.50 ATR`), entry
tolerance (`0.10 ATR`), minimum TP1 R:R (`1.0`), target multiples (`1.0/1.5/2.0R`),
minimum target spacing (`0.35 ATR`) and plan lifetime (`2` M15 bars).

Blocking reason codes emitted by the engine or service:

```text
MARKET_DATA_INVALID          MARKET_DATA_STALE
REQUIRED_EVIDENCE_MISSING    INVALID_ENTRY_GEOMETRY
MISSING_STRUCTURAL_LEVEL     INVALID_STOP_GEOMETRY
STOP_DISTANCE_EXCEEDED       TARGET_STRUCTURE_CONFLICT
INVALID_TARGET_GEOMETRY      INSUFFICIENT_RISK_REWARD
INVALID_PLAN_GEOMETRY        STRATEGY_WAIT / STRATEGY_NO_TRADE
PLAN_EXPIRED                 ENTRY_MISSED
INVALIDATION_TRIGGERED       MARKET_DATA_INSUFFICIENT
```

`strategy_validation=PENDING` is a non-blocking check and a warning
(`UNVALIDATED_STRATEGY`), not a reason to claim the strategy failed. It is the
machine-readable reason execution remains review-gated. Position size is a
non-blocking `NOT_CALCULATED` check.

## 8. Position sizing restriction

No position size is calculated, stored or returned as a number. `position_size` is
`null` and `position_size_status` is `NOT_CALCULATED`. `MISSING_ACCOUNT_INPUTS` lists
what a future, explicitly scoped sizing phase would require:

- account balance or equity;
- contract size;
- tick value;
- verified leverage;
- fee model.

None of these values is read from PATRON or invented. This is a deliberate boundary,
not a missing formula.

## 9. Plan states and lifecycle

| State | Meaning | Execution eligibility |
|---|---|---|
| `PLAN_READY` | Valid geometry and a `VALIDATED` strategy | `EXECUTION_DISABLED` in this phase |
| `PLAN_REVIEW_REQUIRED` | Valid geometry, strategy gate `PENDING` | `REVIEW_REQUIRED` |
| `PLAN_BLOCKED` | Strategy `WAIT`/`NO_TRADE`, or risk rejection | `NOT_ELIGIBLE` |
| `PLAN_INVALID` | Invalid data or failed geometry/invariants | `NOT_ELIGIBLE` |
| `PLAN_EXPIRED` | Lifetime elapsed, stale data, or entry missed | `NOT_ELIGIBLE` |

`PLAN_READY` is intentionally unreachable in the current build: `trend_pullback` is
hard-coded to `PENDING` by provenance, so a technically valid plan is
`PLAN_REVIEW_REQUIRED`. The `PLAN_READY` branch exists for a future independent
`VALIDATED` status and still returns `EXECUTION_DISABLED`; no phase enables execution.

A persisted plan is re-evaluated read-only when fetched:

- invalid latest snapshot → `PLAN_INVALID`;
- stale data or elapsed `expires_at` → `PLAN_EXPIRED`;
- a later close beyond the stop → `PLAN_INVALID` with `INVALIDATION_TRIGGERED`;
- a later close beyond the zone plus `0.10 ATR` → `PLAN_EXPIRED` with `ENTRY_MISSED`.

Status and execution eligibility are updated in persistence. The plan ID is a stable
SHA-256 digest of evaluation ID, policy version, plan version, direction and expiry, so
repeated requests cannot fork the same plan.

## 10. Strategy validation provenance

`app/trade_planning/provenance.py` maps `trend_pullback` to `PENDING` and defaults any
unknown strategy to `PENDING`. There is no code path that promotes a strategy based on
plan quality, backtest output, R:R or model confidence. The Phase 2 60-case gate remains
**PENDING acceptance**: 60 cases exported, **60 reviewed by an automated coding agent**
(58 pass, 2 manual flags, 0 disagreements), but the gate requires independent human
sign-off. Phase 3 does not change that status, does not author human labels, and does
not claim validation or profitability.

The provenance is carried in every result and persisted plan:
`strategy_id`, `strategy_version`, `strategy_config_version`,
`strategy_evaluation_id`, `strategy_validation_status`, `strategy_quality_score`,
`market_snapshot_id` and `market_feature_version`.

## 11. Read-only API contract

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/planning/current` | Build or return the current plan attempt |
| `GET` | `/api/v1/planning/plans/{plan_id}` | Fetch a persisted plan and refresh its lifecycle |
| `GET` | `/api/v1/risk/current` | Return the current plan's risk assessment and eligibility |

Unsupported scope returns the existing typed `422` response. An unknown plan returns
`404`. There is no POST, PUT, PATCH or DELETE route; nothing accepts an order, fill,
quantity, account value or execution instruction. Responses include `request_id`,
snapshot/evaluation IDs, `data_as_of`, `generated_at`, provenance, evidence, checks,
reason codes and warnings.

**Path deviation:** the implementation tasks suggested `/api/v1/trade-planning` and
`/api/v1/trades`. The pre-existing Phase 1 contract test
`tests/test_api.py::test_no_trade_execution_routes_exist` rejects any path containing
`trade`, `order`, `position`, `buy` or `sell`. Preserving that test and its security
intent is mandatory, so the read-only routes use `/planning` and `/risk`. No existing
route was renamed or removed.

## 12. Persistence

`trade_plans` stores identity, provenance, symbol/timeframe/direction, reference and
suggested prices, entry-zone bounds, null actual fill, stop, TP1–TP3, R:R ratios and
`risk_reward_json`, policy version, plan/validation/risk statuses, execution
eligibility, timestamps, expiry and the complete JSON payload. A `plan_id` primary key
makes inserts idempotent. `update_status` also updates execution eligibility for
lifecycle changes.

Persistence is audit, not a prerequisite for returning a plan. An insert failure logs,
adds a warning, and still returns the in-memory plan. A read failure in `get_plan`
returns `404`; a failed status update logs and returns the authoritative refreshed
plan.

## 13. Tests

New tests (25):

- `tests/test_trade_planning.py` (21) — LONG/SHORT geometry, Decimal precision, entry
  and stop invariants, target ordering/spacing, structure-vs-floor conflict, stop
  distance limits, missing swing/ATR/EMA, snapshot mismatch, strategy `WAIT`, stale and
  expired data, `PENDING` provenance, `PLAN_REVIEW_REQUIRED`, null fill/position size,
  policy version, entry-miss lifecycle, idempotent persistence and status update.
- `tests/test_trade_planning_api.py` (4) — current plan, plan by ID, unknown plan `404`,
  risk-current consistency, and absence of execution routes.

Full suite: **246 passed, 1 deselected, 1 warning in 51.55 s**. Ruff: **all checks
passed**. The one deselected test is the pre-existing opt-in real-model KIE test. No
existing test assertion was weakened.

## 14. Performance

Measured on the target Windows host, Python 3.12.10, after warm-up, using the confirmed
LONG fixture and an in-process `TestClient`. Times are wall-clock milliseconds per call.

| Measurement | n | Mean | Median | p95 | Max |
|---|---:|---:|---:|---:|---:|
| `build_geometry()` | 1,000 | 0.105 | 0.104 | 0.107 | 0.286 |
| `RiskService.assess()` | 1,000 | 0.063 | 0.062 | 0.067 | 0.135 |
| `TradePlanningService.current()` (cached) | 500 | 1.895 | 1.826 | 2.239 | 3.327 |
| `GET /planning/current` | 200 | 5.176 | 5.101 | 5.607 | 7.115 |
| `GET /risk/current` | 200 | 5.284 | 5.002 | 5.783 | 37.349 |

The planning and API figures use the production-shaped 5-second analysis cache; the
planning cache itself avoids rebuilding an unchanged plan. With the analysis cache
disabled (worst case), `GET /planning/current` averaged **26.518 ms** (p95 27.855 ms),
dominated by recomputing the Phase 1 snapshot. Geometry and risk validation are
sub-millisecond and are not the bottleneck.

## 15. Limitations

- The strategy gate is PENDING; no plan can be validated or executed. `PLAN_READY` is
  unreachable by design.
- No broker, order, fill, account, equity, fee or position-size integration exists.
- Targets and stops are deterministic projections, not predictions or guarantees.
- Only BTCUSDT M15 and the `trend_pullback` candidate are supported.
- Structure is limited to the confirmed Phase 1 swing/level set; no order book, funding,
  news or alternative data is used.
- The plan is refreshed from the latest closed snapshot; intrabar prices never trigger
  lifecycle changes.
- Phase 2 has **60/60** automated evidence reviews but **0/60** independent human reviews.
  Until human sign-off and aggregate acceptance are complete, Phase 3 remains review-gated
  regardless of technical plan quality.

## 16. Files changed

New:

```text
backend/app/risk/{__init__,contracts,engine,service}.py
backend/app/trade_planning/{__init__,contracts,planner,validation,provenance,service}.py
backend/app/api/v1/{risk,trade_planning}.py
backend/tests/test_trade_planning.py
backend/tests/test_trade_planning_api.py
docs/AI_TRADING_UPGRADE/PHASE_3_RESULTS.md
```

Modified:

```text
backend/app/api/v1/router.py
backend/app/container.py
backend/app/core/errors.py
backend/app/main.py
backend/app/persistence/db.py
backend/app/persistence/repositories.py
backend/tests/conftest.py
docs/AI_TRADING_UPGRADE/README.md
```

## 17. Preservation checks

- PATRON (`PATRON/`, `PATROR/`, `backend/app/patron/`) and `backend/app/evaluation/`
  were not modified by Phase 3.
- Phase 1 market intelligence contracts, calculations, feature version and endpoints
  are unchanged.
- Phase 2 strategy rules, thresholds, decision ordering, evaluation IDs and tests are
  unchanged. Phase 3 consumes the evaluation read-only.
- `/api/v1/chat/*` and all pre-existing routes keep their contracts; the route-collision
  test still passes.
- No new runtime dependency, LLM/Qwen call, Ollama process, broker client or account
  data source was added.
- The only schema change is the additive `trade_plans` table and its indexes; existing
  tables are untouched.

## 18. Acceptance status

| Requirement | Status |
|---|---|
| Deterministic entry zone, suggested entry, structural ATR stop, TP1–TP3, R:R | Met |
| Decimal financial arithmetic | Met |
| Versioned risk policy and machine-readable rejection reasons | Met |
| Invalidation, expiry and entry-miss lifecycle | Met |
| `actual_fill_price = null`, `position_size = null`, `NOT_CALCULATED` | Met |
| Strategy provenance stays `PENDING`; no validation/profitability claim | Met |
| Read-only API and persistence | Met, with documented `/planning` path deviation |
| Comprehensive tests and no weakened assertions | Met — 246 passed, 1 deselected |
| Performance measured | Met — sub-millisecond geometry/risk |
| No Phase 4 work, execution, LLM or account fabrication | Met |

**Phase 3 implementation gate: PASS — acceptance recommended with the strategy gate
PENDING.** This is not a claim that `trend_pullback` is valid or profitable. A valid
plan is `PLAN_REVIEW_REQUIRED` with `execution_eligibility = REVIEW_REQUIRED`, and no
plan is executable.

To complete the outstanding Phase 2 review, an independent reviewer must inspect all
60 exported cases in `PHASE_2_EVALUATION.json`, record `reviewed_decision` and notes for
each against the frozen rules, and run the documented aggregate check. Only a passing
reviewed gate can change the strategy status; Phase 3 code must not be edited to bypass
it.
