# Phase 2 — Deterministic Trend Pullback Strategy Engine: Results

**Phase:** 2 — Strategy registry and candidate engine
**Date:** 2026-11-19
**Scope delivered:** one versioned deterministic strategy (`trend_pullback`) evaluated from the
Phase 1 `MarketSnapshot`, an append-only evaluation audit trail, and two additive read-only
endpoints.
**Implementation status:** **Complete.**
**60-case acceptance gate:** **PENDING — not passed.** 60 cases were exported for human review,
but no independent review has been performed. Algorithmic labels alone cannot pass the gate.
**Phase 3 has not started. PATRON, PATROR, chat, KIE and the desktop client are unchanged.**

---

## 1. Summary

Phase 2 adds a pure strategy layer on top of Phase 1:

- **Contracts** (`app/strategies/contracts.py`): frozen `TrendPullbackEvaluation`,
  `StrategyQuality`, `EligibilityAssessment`, `CheckResult`, `StrategyReason`,
  `StrategyEvidence`, catalog models. No order, entry, stop, target, leverage or size field exists.
- **Configuration** (`app/strategies/config.py`): every threshold is explicit, frozen and
  versioned (`trend-pullback-config-1.0.0`). Changing a value requires a version bump.
- **Strategy** (`app/strategies/trend_pullback.py`): a pure function of a snapshot and the config.
  It fetches nothing, reads no clock implicitly and produces no position geometry.
- **Registry** (`app/strategies/registry.py`): exactly one active, implemented strategy.
- **Service** (`app/strategies/service.py`): reuses `AnalysisService.snapshot()` (and therefore
  the Phase 1 cache, scope check, validation, staleness and persistence), evaluates, persists.
- **Persistence** (`strategy_evaluations` + `StrategyEvaluationRepository`): idempotent by
  deterministic `evaluation_id`; the full typed payload is stored.
- **API**: `GET /api/v1/strategies` (catalog) and `GET /api/v1/strategies/trend-pullback`
  (evaluation). Both read-only and additive.
- **Evaluation harness** (`app/strategies/evaluation.py` + `scripts/evaluate_trend_pullback.py`):
  chronological fixed-stride replay, post-hoc labels, and a deterministic 60-case review packet.
- **Tests**: 34 new tests; all pre-existing tests still pass.

No second strategy, no `breakout_retest`, no trade planning, no risk sizing, no broker execution,
no Qwen/LLM call, no vector database, no UI and no training were added.

---

## 2. Version table

| Component | Version |
|---|---|
| Strategy id | `trend_pullback` |
| Strategy version | `1.0.0` |
| Config version | `trend-pullback-config-1.0.0` |
| Market feature version consumed | `market-intelligence-1.0.0` |
| Evaluation contract | Phase 2 `TrendPullbackEvaluation` (no order fields) |
| Provisional evaluation report | `phase2-provisional-1.0.0` |
| Symbol / timeframe | `BTCUSDT` / `M15` only |

---

## 3. Decision semantics

| Decision | Meaning |
|---|---|
| `LONG` | A confirmed bullish pullback candidate. Quality is a heuristic checklist score. |
| `SHORT` | A confirmed bearish pullback candidate. Mirror of every long rule. |
| `WAIT` | Trend and structure are eligible, but price is not in the pullback zone or confirmation is incomplete. `wait_reasons` explains what is missing. |
| `NO_TRADE` | The setup is invalid or out of scope. `rejection_reasons` explains why. |

`direction` is `LONG`/`SHORT` only for candidates and `NONE` otherwise. `confirmation_status` is
`CONFIRMED`, `PENDING`, `FAILED` or `NOT_APPLICABLE`.

`StrategyQuality` is a **deterministic 0–100 checklist score** with `is_probability=false`. It is
not a probability, expected edge, win rate or position-size input. Non-candidates score 0.

A candidate is valid for two closed M15 bars; `WAIT`/`NO_TRADE` for one. `valid_until` is derived
from `data_as_of` and the config, never from wall-clock guessing.

---

## 4. Rule order (long; shorts mirror)

Evaluation stops at the first failing gate, so every decision has one primary explanation:

1. Snapshot validation and freshness (`MARKET_DATA_INVALID`, `MARKET_DATA_STALE`).
2. Required features present (`FEATURE_UNAVAILABLE`; missing features are named).
3. Established EMA trend (`NO_ESTABLISHED_TREND`) and direction.
4. Regime compatibility (`REGIME_INCOMPATIBLE`) and structure alignment.
5. Extreme volatility (`VOLATILITY_INCOMPATIBLE`).
6. Opposite structure (`STRUCTURE_CONFLICT`) and recent adverse CHoCH
   (`STRUCTURE_INVALIDATED`).
7. Pullback location: within `[-0.75, +0.35]` ATR of EMA21, no more than `-0.25` ATR below EMA50,
   depth ≥ `0.25` ATR, and no close beyond the latest confirmed swing (`PULLBACK_TOO_DEEP`,
   `PULLBACK_INVALIDATED`, `WAIT PULLBACK_NOT_PRESENT`).
8. Momentum health (`MOMENTUM_DETERIORATION`).
9. Closed-bar confirmation: close above EMA21 (long) with MACD histogram and RSI improving versus
   three bars earlier (`WAIT AWAITING_RECLAIM` / `WAIT AWAITING_MOMENTUM_CONFIRMATION`).
10. Room to the nearest resistance ≥ `1.0` ATR (`RESISTANCE_TOO_CLOSE`) and no confirmed adverse
    sweep within `0.75` ATR and 8 bars (`LIQUIDITY_CONFLICT`).

All numeric thresholds are in `TrendPullbackConfig`.

---

## 5. Output contract

`TrendPullbackEvaluation` contains: `evaluation_id`, `strategy_id`, `strategy_version`,
`config_version`, `symbol`, `timeframe`, `decision`, `direction`, `quality`, `eligibility`,
`confirmation_status`, `reference_price`, `evidence`, `rejection_reasons`, `wait_reasons`,
`warnings`, `market_snapshot_id`, `market_feature_version`, `data_as_of`, `evaluated_at`,
`valid_until`.

`evaluation_id` is a deterministic hash of the snapshot id, strategy/config versions, decision and
direction. Re-evaluating the same closed bar is idempotent in persistence.

There is deliberately **no** entry, entry zone, stop, stop loss, target, take profit, leverage,
position size, risk amount or order field. Order geometry belongs to Phase 3.

---

## 6. API and failure behavior

| Route | Purpose |
|---|---|
| `GET /api/v1/strategies` | Catalog of implemented strategies and approved scope |
| `GET /api/v1/strategies/trend-pullback?symbol=BTCUSDT&timeframe=M15&refresh=false` | Evaluate the latest closed bar |

Errors use the existing envelope:

- `422 UNSUPPORTED_SCOPE` for any symbol/timeframe outside `BTCUSDT` `M15`.
- `404 NOT_FOUND` for an unimplemented strategy id (direct service use).
- `503 STRATEGY_UNAVAILABLE` if the strategy service failed to construct; `/api/v1/health` and all
  pre-existing routes remain available.

Construction is defensive in `build_container`: a strategy failure degrades only these two routes.

---

## 7. Persistence

`strategy_evaluations` is additive and append-only:

`evaluation_id` (PK), `strategy_id`, `strategy_version`, `config_version`, `symbol`, `timeframe`,
`decision`, `direction`, `quality_score`, `confirmation_status`, `market_snapshot_id`,
`data_as_of`, `evaluated_at`, `payload_json`, `created_at`.

An index on `(strategy_id, symbol, timeframe, data_as_of DESC)` supports audit queries. No existing
table or column was altered. Persistence failure returns the evaluation with an explicit warning;
it never fabricates success or blocks the response.

---

## 8. Tests

New tests (34), run from `backend/`:

| File | Coverage |
|---|---|
| `tests/test_strategy_contracts.py` | Contract shape, no order fields, non-probability quality, determinism, lifetimes, immutability |
| `tests/test_trend_pullback.py` | Confirmed LONG/SHORT, WAIT paths, room rejection (both sides), volatility, no trend, insufficient/invalid data, missing features, adverse CHoCH, adverse sweep, too-deep and invalidated guards |
| `tests/test_strategy_service.py` | Snapshot reuse, persistence idempotency, catalog, unknown strategy, unsupported scope, persistence degradation, status |
| `tests/test_strategies_api.py` | Catalog route, evaluation route, scope errors, unavailable-service degradation, existing health route |
| `tests/test_strategy_evaluation.py` | Config validation, reproducible report, gate remains PENDING, bounded stratified case selection |

Fixtures (`tests/strategy_fixtures.py`) are generated by a documented arithmetic cycle rather than
committed candle blobs. They are synthetic and prove rule behavior, not historical edge.

Commands:

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check app tests scripts
```

Observed after the Phase 2 changes: **221 passed, 1 deselected**; ruff reports **All checks
passed**. The 1 deselected test is the opt-in real-model KIE runtime test, unchanged from Phase 1.

Note: two defensive guards (`PULLBACK_TOO_DEEP`, `PULLBACK_INVALIDATED`) are not reachable from
ordinary trending candle series: an established bullish trend requires close above EMA21 while
those conditions require close below EMA50 or below the latest swing low. They are tested against
targeted, explicitly documented snapshot copies to prove the branch is deterministic and fails
safe. This is a guard-rail test, not evidence that those situations occur in live data.

---

## 9. Provisional historical evaluation

Run:

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe scripts/evaluate_trend_pullback.py
```

Dataset: local `backend/data/patron/BTCUSDT_15m.parquet`, 100,930 closed bars, 2024-01-01 →
2026-11-17. Sampling: every 48th bar after a 200-bar warm-up, forward horizon 16 bars, labels
computed only after each evaluation. Full report and 60 exported cases:
[`PHASE_2_EVALUATION.json`](PHASE_2_EVALUATION.json).

| Metric | Value |
|---|---|
| Evaluated bars | 2,099 |
| `LONG` / `SHORT` / `WAIT` / `NO_TRADE` | 0 / 1 / 306 / 1,792 |
| Candidates | 1 |
| Algorithmic hit rate, all candidates | 0.0% (1 case — not statistically meaningful) |
| Candidate quality | 1 HIGH, mean score 85.0 |
| Rejections | `REGIME_INCOMPATIBLE` 1,217; `NO_ESTABLISHED_TREND` 387; `STRUCTURE_INVALIDATED` 92; `VOLATILITY_INCOMPATIBLE` 81; `PULLBACK_TOO_DEEP` 13; `RESISTANCE_TOO_CLOSE` 2 |
| Waits | `PULLBACK_NOT_PRESENT` 264; `AWAITING_MOMENTUM_CONFIRMATION` 31; `AWAITING_RECLAIM` 11 |
| Material moves (≥1 ATR/16 bars) after WAIT | 205 |
| Material moves after NO_TRADE | 1,172 |
| Evidence completeness | 100% (all 2,099 records have snapshot id, strategy versions and an explanation) |

The candidate rate is extremely low on this sample. That is an honest observation, not a claim of
quality: one candidate cannot establish an edge, and the single hit/miss label is noise. The
material-move counts after WAIT/NO_TRADE are hindsight measurements, not errors; the strategy
intentionally declines unclear setups.

---

## 10. 60-case gate status

- **Exported cases:** 60 (`PHASE_2_EVALUATION.json` → `cases`), stratified deterministically:
  1 candidate, 29 `WAIT`, 30 `NO_TRADE`, in chronological order.
- **Reviewed cases:** 0.
- **Gate status:** **PENDING.**
- **Reason:** no independent human review exists. Selection oversamples informative decisions;
  it does not cherry-pick outcomes. Every case carries `review_status: "PENDING"`,
  `reviewer: null`, `reviewed_decision: null`.
- **Why not authored expected labels:** the brief forbids fabricating a completed reviewed gate.
  Authored labels from the same engineer who wrote the rules would not be independent review.
- **What passing requires:** a reviewer must inspect all 60 cases against the frozen rules,
  record `reviewed_decision` and notes, and the aggregate must meet the Phase 2 gate. The harness
  helper `aggregate_review()` only counts recorded reviews; it cannot invent them.

The implementation gate (deterministic rules, tests, API, safe failure) is met. The 60-case
acceptance gate is not.

---

## 11. Limitations and known failure modes

- **Very few candidates on the provisional sample.** The conjunction of trend, regime, structure,
  shallow pullback, three-way closed-bar confirmation, room and no adverse sweep is strict. This
  may be correct conservatism or over-restriction; the reviewed 60-case gate must decide.
- **Dataset provenance.** The local parquet is the same warm-up artifact used for PATRON and its
  timestamps extend into late 2026. It is not a live broker sample and may be synthetic.
- **Algorithmic labels only.** Close-to-close direction over 16 bars, no fees, funding, slippage,
  fills, stop/target simulation or survivorship correction.
- **Overlapping labels.** Fixed-stride sampling reduces but does not eliminate overlap between
  forward windows, so hit-rate confidence intervals would be wide even with more candidates.
- **Unreachable guard rails.** `PULLBACK_TOO_DEEP` and `PULLBACK_INVALIDATED` are defensive paths
  tested through targeted snapshots; their live frequency is unknown.
- **Regime dependency.** 58% of sampled bars were not in a trending regime, so most bars reject
  before pullback evaluation. That is by design but concentrates any edge or failure in a minority
  of bars.
- **No execution semantics.** A candidate is not an order, has no entry/stop/target and cannot be
  used for PnL or risk sizing in Phase 2.

---

## 12. Acceptance checklist

| Phase 2 acceptance condition | Status |
|---|---|
| Deterministic decisions | Met — pure evaluator, no implicit clock/network, deterministic ids |
| Phase 1 contracts reused | Met — `MarketSnapshot`, analyzers, `AnalysisService`; no duplicate indicators |
| Closed candles only | Met — strategy sees only the Phase 1 snapshot built from closed bars |
| Structured machine-readable explanation | Met — typed evidence, checks, rejection/wait reasons |
| Safe failure | Met — explicit rejections, `FEATURE_UNAVAILABLE`, `503 STRATEGY_UNAVAILABLE` |
| API works | Met — two routes, tested |
| Tests pass, no weakened regressions | Met — 221 passed, 1 deselected; ruff clean |
| PATRON unchanged | Met — verified by path diff (see §13) |
| Evaluation limits honest | Met — PENDING gate, algorithmic labels, no fabricated review |
| Report complete | Met — this document |

---

## 13. Preservation checks

```bash
git diff --stat <baseline>..HEAD -- PATRON PATROR backend/app/patron
git diff --stat <baseline>..HEAD -- backend/app/evaluation
```

Expected: empty for PATRON/PATROR. Phase 2 touches only additive strategy, persistence, API,
container wiring, tests, scripts and docs files. No existing endpoint contract, chat route, PATRON
artifact or evaluation module was modified.

---

## 14. Explicitly not done

- Phase 3 trade planning, validation, risk engine or position sizing.
- `breakout_retest` (waits for its own reviewed gate).
- Entry, stop, target, leverage, size or order fields in strategy output.
- Qwen/LLM calls, vector retrieval, training or LoRA.
- UI, chart overlays or desktop changes.
- Broker/exchange execution.
- Any change to PATRON, PATROR, chat, KIE or existing market/indicator/signal/forecast routes.
