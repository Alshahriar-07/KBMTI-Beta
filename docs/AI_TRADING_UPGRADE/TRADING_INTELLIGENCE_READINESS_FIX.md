# Trading Intelligence readiness fix

**Date:** 2026-11-22
**Scope:** Trading Assistant (`/api/v1/assistant/market-intelligence`), Qwen readiness
synchronisation, PATRON conflict materiality, trade-plan/position-size reasons and the
visual assistant's component states.
**Outcome:** the pipeline now waits for a real Qwen readiness gate before inference, reports
one machine-readable state per component, and explains each unavailable output. No gate was
weakened: the strategy gate remains **PENDING**, execution remains **DISABLED**, and position
size remains **NOT_CALCULATED**.

## 1. Observed symptoms and actual root causes

The reported response was internally consistent but presented as one `INITIALIZING` state:

| Component | Observed | Actual cause |
| --- | --- | --- |
| Qwen | `INITIALIZING`, interpretation not available | `market_intelligence` returned immediately when the background load was in flight. There was no bounded wait for the load + smoke test (measured ~3.3 s), so the first response carried a placeholder. |
| PATRON | median path `BEARISH`, `CONFLICTING_EVIDENCE` | The conflict rule used only the sign of the final median (`q50 > 0` / `< 0`). A median a few hundredths of an ATR from zero was treated exactly like a material directional call. |
| Trade plan | unavailable | Expected gate behaviour: the deterministic strategy returned `WAIT`/`NO_TRADE`, so no plan was constructed (`STRATEGY_WAIT` / `STRATEGY_NO_TRADE`). This is not a bug and must not be bypassed. |
| Position size | unavailable | Expected: no verified account/equity, contract size, tick value, leverage or fee model exists, so no size is calculated. |
| Header/UI | a single `INITIALIZING` badge | Qwen's state was reused as the only pipeline state, so a Qwen-only condition looked like the whole pipeline was initializing. |

No fabricated Qwen response, price, size or validation status was found. The deterministic
decision, risk authority and disabled execution were already correct.

## 2. Qwen initialization and interpretation

### Changes

- `ModelManager.wait_until_ready(timeout)` blocks on the load condition until the model is
  READY (load **and** inference smoke test) or until a terminal failure/timeout. Readiness,
  unload and shutdown notify waiting callers.
- `KieService.wait_until_ready(timeout)` starts the single background load if it has not
  started and forwards the bounded wait. It never raises.
- `IntelligenceService.market_intelligence` calls the wait before inference, bounded by
  `QWEN_READY_WAIT_SECONDS = 25.0` (much longer than the measured 3.3 s, short enough to
  avoid an unbounded HTTP request). If the runtime becomes READY, the same request proceeds
  to a real Qwen inference through the existing schema and evidence validator.
- If the wait times out or the runtime fails, the response keeps the deterministic answer and
  reports Qwen's real health state (`INITIALIZING`, `FAILED`, `DISABLED`, `UNAVAILABLE`).
- The Vulkan runtime itself was **not** rebuilt or replaced.

### Two live-run integration issues found and fixed

1. **A faithful quote was rejected as an invented number.** The new materiality note contains a
   rounded display value (`0.11 ATR`) while `median_path_atr` is stored as `0.111`. Qwen quoted
   the note verbatim and the strict validator rejected `0.11` because prose numbers were not in
   the allowed set. The fix adds numbers that appear in *deterministic* assessment reason and
   conflict text to the allowed set. Arbitrary numbers are still rejected; only values the
   deterministic services computed are quotable.
2. **The cache timestamp was taken before inference.** With a real 43 s generation, the cached
   entry was already older than its 45 s TTL when written, so the next poll could start a second
   inference. Both intelligence caches now timestamp at write time.

### What the user sees

`Qwen interpretation` is its own row. `INITIALIZING` appears only while the load/inference
gate is genuinely pending; a pre-existing `USED` response shows `READY`, a rejected or failed
inference shows `FAILED` with the validator or runtime error.

## 3. PATRON conflict audit

The audit paths were checked end to end:

- **Timestamps/horizon:** `forecast_as_of`, `input_last_bar_at`, `generated_at`,
  `horizon_candles` and `horizon_minutes` are preserved from the run. Freshness is measured
  against the latest closed bar, not against wall-clock alone.
- **Alignment/preprocessing:** PATRON is fed the same closed candles as the snapshot; the
  readiness detail reports the model version, and the raw quantiles and predicted candles stay
  byte-for-byte source evidence.
- **Direction calculation:** `forecast_direction` is still the sign of the final median close
  `q50`. That raw direction is never rewritten.
- **Why the disagreement looked total:** the previous rule had no magnitude. A median of
  `0.0003` (a small fraction of an ATR) and a median of `2 ATR` produced the same
  `CONFLICTING_EVIDENCE` label.

### Materiality rule (new)

`MATERIAL_DIRECTION_ATR = 0.25` (one quarter of a 15-minute bar's average true range). A
direction disagreement is material when either:

1. the final median displacement is at least `0.25 ATR`, or
2. the entire 80% close interval lies on the opposite side of zero (the model rules out the
   deterministic sign).

When a disagreement is below that threshold, PATRON's raw direction and the measured
`median_path_atr` are still reported, with an explicit reason in `forecast_assessment.reasons`
explaining that the sign flip was not treated as material. Genuine disagreements keep
`CONFLICTING_EVIDENCE`, are listed in `forecast_assessment.conflicts`, and are surfaced by the
UI. PATRON is never discarded, overridden or converted into the decision.

## 4. Trade plan and position size

These are represented as explicit, machine-readable blockers:

- `trade_plan.status = UNAVAILABLE` with `reason_code` from the deterministic planner
  (`STRATEGY_WAIT`, `STRATEGY_NO_TRADE`, `MARKET_DATA_STALE`, `PLAN_EXPIRED`, …) and the first
  rejection messages. `plan_status` carries the planner's status.
- `position_size.status = NOT_CALCULATED`, `reason_code = MISSING_ACCOUNT_INPUTS`, with the
  concrete missing inputs (`account_balance_or_equity`, `contract_size`, `tick_value`,
  `verified_leverage`, `fee_model`).
- `risk.status` is `APPROVED` only when deterministic risk checks actually passed,
  `REJECTED` when they failed, and `NOT_EVALUATED` when no plan existed.
- `strategy.status` maps the independent gate to `PENDING` / `PASSED` / `FAILED`; today it is
  `PENDING` because the 60-case automated review (60/60) still lacks independent human
  sign-off and a documented aggregate acceptance threshold.

A plan is never made available by bypassing strategy validation, and no size is calculated or
invented without account inputs.

## 5. API contract

`MarketIntelligence.readiness` is a new required object with eight independent components:

```json
{
  "market":       {"status": "READY", ...},
  "patron":       {"status": "CONFLICTING", "usable_in_decision": false, "median_path_atr": 0.42, ...},
  "qwen":         {"status": "INITIALIZING", "health_state": "INITIALIZING", "waited_seconds": 3.2, ...},
  "strategy":     {"status": "PENDING", "reason_code": "STRATEGY_GATE_PENDING", ...},
  "trade_plan":   {"status": "UNAVAILABLE", "reason_code": "STRATEGY_WAIT", ...},
  "risk":         {"status": "NOT_EVALUATED", "reason_code": "NO_PLAN_TO_ASSESS", ...},
  "position_size":{"status": "NOT_CALCULATED", "reason_code": "MISSING_ACCOUNT_INPUTS", "missing_inputs": [...]},
  "execution":    {"status": "DISABLED", "reason_code": "EXECUTION_DISABLED", ...}
}
```

Each scenario now also carries `structure`, `data_as_of` and `data_is_stale`, so its
confirmation/invalidation conditions are tied to the snapshot that produced them.

## 6. UI changes

- The header shows Market, PATRON, Qwen, Gate, Plan and Execution badges separately instead of
  a single AI status.
- `PipelineReadinessPanel` lists every component with its status, detail, reason code and
  missing inputs. Only the component that is actually initializing shows `INITIALIZING`.
- Scenario cards show their structure state and data freshness; unavailable scenarios still
  explain the missing verified level.
- The Qwen runtime panel and retry action are unchanged.

## 7. Tests added

Backend (`backend/tests`):

- `test_qwen_initializing_then_ready_returns_real_interpretation` — bounded wait reaches READY,
  then a validated structured response is used.
- `test_qwen_readiness_timeout_keeps_initializing_state` — bounded wait expires, Qwen stays
  `INITIALIZING`, deterministic output survives.
- `test_wait_until_ready_loads_in_background`, `test_wait_until_ready_times_out_then_recovers`,
  `test_wait_until_ready_returns_false_on_load_failure` — KIE lifecycle and no duplicate load.
- `test_conflicting_patron_path_is_flagged` and
  `test_bullish_patron_against_bearish_market_is_conflicting` — genuine disagreements stay
  `CONFLICTING_EVIDENCE` with material displacement.
- `test_immaterial_opposite_median_is_not_a_directional_conflict` — a sub-threshold sign flip
  stays visible but is not labelled a conflict.
- `test_pipeline_readiness_explains_each_component` — per-component states, risk, strategy,
  position size, execution.
- `test_missing_trade_plan_reports_the_strategy_reason` — WAIT/NO_TRADE with
  `STRATEGY_WAIT`/`STRATEGY_NO_TRADE` and no fabricated size.
- `test_qwen_may_quote_a_number_from_deterministic_reason_text` — quoting a deterministic
  materiality value is accepted; an invented number remains rejected by the existing test.
- Existing stale-forecast, invalid-forecast and Qwen failure/timeout tests now also assert the
  readiness component state.

Frontend (`apps/desktop/src`):

- `PipelineReadinessPanel.test.tsx` — only Qwen is `INITIALIZING` while Market is `READY` and
  PATRON is `CONFLICTING`; plan, risk, position size and execution states render separately.
- Fixtures updated for `readiness` and scenario freshness.

## 8. Verification

```
backend: 298 passed, 1 deselected (kie_runtime marker)
ruff:    All checks passed
frontend: typecheck clean, eslint clean (--max-warnings 0),
          34 tests passed, production build succeeded
```

A real GPU run was also executed through the production service with
`backend/scripts/qwen_pipeline_smoke.py` (RX 580 Vulkan, model load 2.991 s):

- Qwen status `USED`, 11 known evidence references, all numeric claims verified, 43.19 s
  latency (the 4B model on this GPU).
- `readiness.qwen.status = READY`, `health_state = READY`.
- PATRON final median `0.111 ATR`: `direction_conflict_material = false`, so the median sign
  flip stayed reported but was not a conflict. Qwen's own `PATRON momentum is strong_bullish`
  remained a **genuine** conflict and the assessment stayed `CONFLICTING_EVIDENCE`.
- Decision `NO_TRADE`; `trade_plan = UNAVAILABLE` (`STRATEGY_NO_TRADE`), `risk = NOT_EVALUATED`,
  `position_size = NOT_CALCULATED`.
- Scenario entries carried `structure = DOWNTREND`, `data_as_of` and `data_is_stale = false`.

The live run pre-loaded the model before the service call, so it validates real
inference/validation/readiness, not the wait timing. The bounded load wait itself is covered by
the `INITIALIZING → READY`, timeout and load-failure tests.

## 9. Remaining blockers

1. **Strategy gate is PENDING.** The automated 60-case review is complete (60/60, 58 pass,
   2 manual flags, 0 disagreements), but independent human sign-off and an aggregate
   acceptance threshold are still missing. Plans, when they exist, stay
   `PLAN_REVIEW_REQUIRED` and non-executable.
2. **Position sizing is unavailable.** Verified account, contract, tick-value, leverage and fee
   inputs do not exist; no size is or should be produced.
3. **PATRON is not predictive yet.** The candidate is a numerical-sanity fix (close MAE
   24.13 bp vs persistence 23.44 bp) and fails the persistence gate. Materiality filtering
   removes false conflicts; it does not create alpha.
4. **Qwen startup is bounded, not instant.** A cold start can still exceed the 25 s wait on a
   slower machine; the response then honestly reports `INITIALIZING` and the UI retries. On this
   workstation a real narration takes ~43 s, longer than the 60 s frontend poll interval when a
   cold load is added, so the first populated answer can lag the first poll.
5. **No automatic execution.** Execution remains disabled by design; nothing in this change
   introduces an order path.
