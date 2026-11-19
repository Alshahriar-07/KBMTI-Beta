# KBMTI AI Trading Upgrade — Implementation Tasks

**Date:** 2026-11-19
**Status:** plan for approval. Phase 0 is complete (audit documents); **no Phase 1 task has started.**
**Basis:** `REPOSITORY_AUDIT.md`, `EXISTING_ARCHITECTURE.md`, `IMPLEMENTATION_GAP_ANALYSIS.md`,
and `NEW_AI_UPDATE/01`–`14`.

Task IDs are stable references for phase reports. Each phase ends with a report in
`docs/AI_TRADING_UPGRADE/PHASE_<n>_RESULTS.md` and an explicit pass/fail table against its exit gate.
A phase does not begin until the previous phase's gate is accepted.

---

## 0. Global rules for every task

**Allowed by default**

- Additive modules under `backend/app/<new or existing domain>/`.
- Additive tables/indexes in `backend/app/persistence/db.py`.
- Additive routers in `backend/app/api/v1/` + `api_router.include_router(...)`.
- Additive fields in `AppContainer` / `build_container` / `create_app` (optional args only).
- Additive UI routes, panels, API client methods, chart layers.
- New tests, fixtures, docs.

**Forbidden without a separate approved change**

- Any edit under `PATRON/`, `PATROR/`, `backend/app/patron/`.
- Any rewrite of `backend/app/chat/service.py`, `RuleBasedResponder`, or `/api/v1/chat/*` payloads.
- Changing existing endpoint paths, required fields, status codes or error shape.
- Altering or dropping existing SQLite tables/columns.
- Any order placement, exchange credential handling, shell execution, or cloud inference.
- Enabling Qwen or any strategy by default in a way that changes current user-visible behaviour.
- Training that runs inside the inference process or blocks model loading.

**Definition of done (per task and per phase)**

1. Scope implemented exactly as listed; nothing extra.
2. Unit tests for every new deterministic calculation, with frozen fixtures.
3. Existing suite still passes; no assertion weakened, no test skipped to hide a failure.
4. `ruff check app tests scripts` clean for backend changes.
5. Frontend `npm run typecheck` and `npm run lint` clean for UI changes; new vitest tests where behaviour is non-trivial.
6. Existing features verified (market, indicators, signals, forecast, chart, chat, KIE status).
7. Performance measured where the phase claims a budget; numbers reported with method.
8. Limitations and known defects listed; unimplemented items stated as unimplemented.
9. Phase report written with exact files changed, commands run, raw results, pass/fail per gate.

**Standard verification commands**

```bash
# backend
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check app tests scripts

# opt-in real model (only when the phase needs it; loads the 2.4 GB GGUF)
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -m kie_runtime tests/test_kie_runtime_smoke.py

# desktop
cd apps/desktop
npm run typecheck
npm run lint
npm run test
```

Baseline at Phase 0: backend `152 passed, 1 deselected` in 35.86 s.

---

## 1. Cross-cutting tasks (do before Phase 1 implementation)

| ID | Task | Files | Notes / acceptance |
|---|---|---|---|
| C0-1 | Establish change tracking | project root | Root is **not** a git repository. Recommend `git init` + baseline commit before Phase 1 so every phase can be diffed and reverted. Requires user approval; if declined, each report must list changed files exactly. |
| C0-2 | Shared response metadata + error codes | `backend/app/analysis/contracts.py` (`ResponseMeta`), `backend/app/core/errors.py` | `ResponseMeta` = `request_id, generated_at, data_as_of, is_stale, symbol, timeframe, strategy_version, patron_model_version, qwen_model_version, risk_engine_version, evidence_refs, warnings`. New `ApiError` subclasses for `MARKET_DATA_STALE`, `NO_ELIGIBLE_STRATEGY`, `RISK_VALIDATION_FAILED`, `SETUP_EXPIRED`, `INSUFFICIENT_ACCOUNT_INPUTS`, `PATRON_UNAVAILABLE`, `QWEN_UNAVAILABLE`, `LEARNING_JOB_NOT_APPROVED`. Unit test: handler renders `{error:{code,message,details}}`. |
| C0-3 | Feature flags + observe mode | `backend/app/core/config.py`, `backend/app/api/v1/settings.py` | `KBMTI_ASSISTANT_ENABLED=0`, `KBMTI_STRATEGIES_ENABLED=0` (or equivalent settings keys), `KBMTI_RISK_MODE=observe`. Default install must show no actionable plan. Test: disabled service returns `enabled=false`, no plan. |
| C0-4 | Frozen market fixtures | `backend/tests/fixtures/` (BTCUSDT M15 windows) + loader | Hand-checked OHLCV windows: trending up, trending down, range, volatile, thin/warm-up, invalid (high<low, gaps). Used by all analysis/strategy tests. |
| C0-5 | Clock/staleness test utilities | `backend/tests/conftest.py` (helpers) | Freeze "now" and candle times; assert stale vs fresh transitions deterministically. |
| C0-6 | Phase report template + docs index | `docs/AI_TRADING_UPGRADE/` | A short template (scope/files/tests/measurements/limitations/gate table). Update `docs/AI_TRADING_UPGRADE/README.md` index (create) linking all phase documents. |

Exit for cross-cutting: contracts and flags import cleanly, tests pass, no behaviour change with
flags off.

---

## 2. Phase 1 — Market context and deterministic analysis

**Goal:** one immutable, reproducible BTCUSDT M15 snapshot with structure, momentum, volatility,
liquidity and regime, plus explicit `unavailable` states.
**Depends on:** C0. **Exit gate:** hand-checked fixtures reproduce every value; invalid/stale data
rejected; snapshot metadata complete.

| ID | Task | Files / symbols | Acceptance |
|---|---|---|---|
| P1-01 | Snapshot contracts + builder | `analysis/contracts.py` (`MarketSnapshot`, `FeatureValue`, `StructureState`, `MomentumState`, `VolatilityState`, `LiquidityState`, `RegimeState`), `analysis/context.py` (`MarketContextBuilder.build`) | `as_of` = last **closed** candle close time; only candles with `open_time + tf <= as_of` are read; `feature_version` and per-feature `valid/unavailable_reason/source` present; forming candle excluded. |
| P1-02 | Trend features | `analysis/trend.py` | EMA 9/21/50 alignment, price-vs-EMA distance, EMA slope over N bars, score → `bullish/bearish/neutral/undetermined`; reuses `indicators.engine.ema` rather than reimplementing. |
| P1-03 | Structure engine | `analysis/structure.py` | Closed-bar swing detection (fractal window), HH/HL/LH/LL labelling, BOS/CHoCH with the broken swing level and timestamp; returns `insufficient_data` below warm-up. |
| P1-04 | Momentum engine | `analysis/momentum.py` | RSI level + change, MACD histogram change, ROC; optional divergence candidate flagged as `unconfirmed` (never presented as a signal). |
| P1-05 | Volatility engine | `analysis/volatility.py` | ATR 14, ATR as % of price, ATR percentile over a fixed lookback, Bollinger width state; `low/normal/high/extreme` with thresholds documented and tested. |
| P1-06 | Regime classifier | `analysis/regime.py` | Deterministic rules over trend + volatility (+ range width) → `trending/ranging/volatile/uncertain`; `uncertain` when evidence conflicts. No LLM. |
| P1-07 | Liquidity features | `analysis/liquidity.py` | Equal highs/lows within tolerance, recent sweep candidates (wick beyond level + close back), distance to nearest pool; all `candidate`, never asserted fact. |
| P1-08 | Snapshot persistence | `persistence/db.py` (`market_snapshots`), `persistence/repositories.py` (`MarketSnapshotRepository`) | Insert-only; `payload_json`; index `(symbol, timeframe, as_of DESC)`; repository unit tests. |
| P1-09 | Analysis service + cache | `analysis/service.py` (`AnalysisService`) | Builds on closed-bar change; caches by `(symbol, timeframe, last_closed_bar, feature_version)`; reports `stale` using existing freshness rules; never crashes the app if the provider is down. |
| P1-10 | API | `api/v1/market_context.py` (new router) or extend `api/v1/market.py` additively | `GET /api/v1/market/context`, `GET /api/v1/market/analysis`, `POST /api/v1/market/context/refresh` (throttled). Response includes `ResponseMeta`. |
| P1-11 | Wiring | `container.py`, `main.py`, `api/v1/router.py` | Service constructs even when disabled; startup guarded; no existing service modified. |
| P1-12 | Multi-timeframe (optional 1b) | `analysis/multi_timeframe.py` | M15 + H1 alignment; `unavailable` if H1 fetch fails; latency measured. Only if the H1 fetch does not exceed the snapshot budget. |
| P1-13 | Tests + report | `tests/test_analysis_*.py`, `docs/AI_TRADING_UPGRADE/PHASE_1_RESULTS.md` | See test matrix below; report includes snapshot build timing. |

Phase 1 test matrix (minimum): trend up/down/range fixtures; swing + BOS + CHoCH known-answer cases;
RSI/MACD change; ATR percentile edge cases; regime transitions; equal-high tolerance; invalid OHLCV
rejected; stale snapshot flagged; forming candle never used; feature versions present; API contract
shape; disabled flag returns `enabled=false`.

---

## 3. Phase 2 — Strategy registry and candidate engine

**Goal:** versioned, explicit strategies that return explainable candidates or explicit rejection.
**Depends on:** Phase 1 gate. **Exit gate:** one strategy passes deterministic tests and a 60-case
labelled snapshot benchmark; WAIT/NO_TRADE/rejections are correct; conflicting strategies never
produce a forced signal.

| ID | Task | Files / symbols | Acceptance |
|---|---|---|---|
| P2-01 | Strategy contracts + catalog | `strategies/contracts.py` (`StrategyDefinition`, `CandidateSetup`, `RejectionReason`), `strategies/base.py`, `strategies/catalog.py` | Definition includes id, semver, supported symbol/timeframe, allowed regimes, required features + versions, entry/confirmation/invalidation, stop/target methodology, max horizon, cooldown, risk constraints, known failure modes, status. |
| P2-02 | Measurable conditions | `strategies/base.py` | No qualitative term without a numeric predicate; helpers return `(met, evidence)`; missing feature → `unavailable`, not `false` silently. |
| P2-03 | First strategy: trend pullback | `strategies/trend_pullback.py` | BTCUSDT M15 only; requires trend regime + pullback into EMA/structure zone + confirmation (closed-bar reclaim); outputs entry zone, structural stop reference, target references, confirmation and invalidation. |
| P2-04 | Strategy engine | `strategies/engine.py` (`StrategyEngine.evaluate`) | Eligibility filter → per-strategy condition evaluation → candidates; missing confirmation ⇒ `WAIT`; nothing eligible/stale/conflict ⇒ `NO_TRADE` with reasons; ranking documented; duplicate suppression. |
| P2-05 | Persistence | `strategy_evaluations` table + repository | Every evaluation stored with snapshot id, versions, action, conditions, rejections, expiry. |
| P2-06 | API | `api/v1/strategies.py` | `GET /strategies`, `/strategies/{id}`, `/strategies/candidates`; additive, flag-gated. |
| P2-07 | 60-case benchmark | `tests/fixtures/strategy_cases/` + `tests/test_strategy_benchmark.py` | 60 labelled snapshots (LONG/SHORT/WAIT/NO_TRADE) with expected reasons; report exact confusion matrix. Cases authored from real fixture data, not invented. |
| P2-08 | Second strategy (only if gate passes) | `strategies/breakout_retest.py` | Separate benchmark; must not regress the first strategy's cases. |
| P2-09 | Report | `docs/AI_TRADING_UPGRADE/PHASE_2_RESULTS.md` | Include version table, benchmark matrix, known failure modes, limitations. |

Do not: add more than two strategies before Phase 5; tune thresholds against the final benchmark
after seeing results (thresholds are frozen before the run and documented).

---

## 4. Phase 3 — Trade planner, validation and risk

**Goal:** deterministic plans with correct geometry and enforced risk limits; no fabricated size.
**Depends on:** Phase 2. **Exit gate:** all invariants tested; no plan can be produced without a
passing risk assessment; missing account inputs yield `not_calculated`.

| ID | Task | Files / symbols | Acceptance |
|---|---|---|---|
| P3-01 | Planning contracts | `trade_planning/contracts.py` | `TradePlan` with side, entry type/zone, stop + rationale, TP1-3 + rationale, invalidation, RR, fees/slippage assumptions, expiry, status, version refs. Every optional numeric has explicit status. |
| P3-02 | Plan builder | `trade_planning/planner.py` (`TradePlanner.plan`) | Entry/stop/targets derive from strategy metadata + snapshot (structure level / ATR), never from prose; rounding to instrument `digits`/`point` when available. |
| P3-03 | Validation | `trade_planning/validation.py` | LONG: stop < entry ref, targets > entry ref; SHORT inverse; finite values; non-zero stop distance; tick/lot alignment; expiry in future; duplicate active setup rejection; evidence IDs exist. |
| P3-04 | Risk config + engine | `risk/contracts.py`, `risk/engine.py`, `risk/limits.py` | Max risk per trade, daily loss limit, consecutive-loss guard, max concurrent exposure; defaults `observe` (no actionable plan). Config version persisted. |
| P3-05 | Position sizing | `risk/sizing.py` | Returns `not_calculated` + missing-input list. Explicitly defines the future account-input contract (balance/equity, contract size, tick value, fees) without adding fake data. |
| P3-06 | Envelope assembly + persistence | `intelligence/contracts.py` (`DecisionEnvelope`), `trade_setups`, `risk_assessments` + repositories | Envelope follows `11` §4; immutable rows; risk assessment references plan + config version. |
| P3-07 | API | `api/v1/trade_assistant.py` | `POST /trade-assistant/evaluate`, `GET /trade-assistant/current`, `GET /trade-assistant/plan/{setup_id}`; errors use the new codes. |
| P3-08 | Tests | `tests/test_trade_planning.py`, `tests/test_risk.py` | LONG/SHORT geometry, zero distance, tick rounding, RR math, expiry, cap breach, missing inputs, stale block, disabled/observe mode. |
| P3-09 | Report | `PHASE_3_RESULTS.md` | Include sample plan JSON (from fixtures) and the exact rejection reasons. |

---

## 5. Phase 4 — Qwen trading intelligence (tools, validator, RAG)

**Goal:** Qwen explains and compares only validated data, using read-only tools, and cannot override
risk.
**Depends on:** Phase 3 (there must be authoritative plans to explain). **Exit gate:** schema-valid
JSON on held-out cases; invented numbers rejected; missing data produces a tool request or WAIT;
risk override impossible; measured latency reported.

| ID | Task | Files / symbols | Acceptance |
|---|---|---|---|
| P4-01 | Read-only tools | `kie/tools/{market,forecast,strategies,planning}.py`, registration in `kie/service.py` | Implement `get_market_snapshot`, `get_indicator_snapshot`, `get_structure_snapshot`, `get_patron_forecast`, `list_strategy_candidates`, `get_strategy_definition`, `calculate_trade_plan`, `validate_trade_plan`, `get_open_trade_state` (stub until Phase 6), `get_strategy_performance` (stub until Phase 7). `Access.READ`, JSON-schema args, bounded output, audit rows in `kie_tool_calls`. |
| P4-02 | Bounded tool loop | `kie/planner.py`, `kie/workflow.py`, `kie/core.py` | Max 2 tool rounds, per-call timeout, total deadline; tool failure becomes a typed observation, not a hallucinated answer; no shell/file/network tools. |
| P4-03 | Structured output + validator | `intelligence/prompt.py`, `intelligence/validator.py`, `kie/validation.py` | Enforce `11` §4 envelope; verify every numeric against the plan/snapshot; reject unknown `evidence_refs`, non-monotonic prices, action not in allow-list, expiry in the past. Invalid ⇒ deterministic degraded envelope (`WAIT`/`NO_TRADE`) + warning. |
| P4-04 | Knowledge base + retrieval | `kie/knowledge.py`, `backend/knowledge/*.md` (versioned) | Curated docs (structure, momentum, S/R, liquidity, regimes, strategy rules, risk, invalidation) with IDs/versions; retrieval result IDs included in trace; no unverified claims. |
| P4-05 | Degraded path | `intelligence/service.py` | KIE unavailable/busy/timeout ⇒ deterministic envelope with `QWEN_UNAVAILABLE` warning; `/trade-assistant/current` still works; chat unaffected. |
| P4-06 | Tests + measurement | `tests/test_intelligence.py`, `tests/test_kie_tools.py`, opt-in runtime test | Fake model returns invalid JSON / invented price / override attempt → rejected. Real-runtime test measures tool round latency, TTFT, tok/s, memory; report raw numbers. |
| P4-07 | Report | `PHASE_4_RESULTS.md` | Tool list, schema, validator rules, latency measurements, failure modes, remaining hallucination risk. |

Do not: enable the KIE chat responder by default; add write-capable tools; put numbers in the prompt
that the validator cannot verify.

---

## 6. Phase 5 — AI Trading Assistant UI

**Goal:** one page that answers "what is happening, is there a setup, what next, what invalidates it".
**Depends on:** Phase 3 (envelope) and Phase 4 (explanation), though it must render correctly with
Qwen unavailable. **Exit gate:** all states render; chart layers independent; PATRON layer untouched.

| ID | Task | Files | Acceptance |
|---|---|---|---|
| P5-01 | API client + types | `apps/desktop/src/lib/api.ts`, `lib/types.ts` | Typed calls for context/analysis/candidates/evaluate/current/plan; `ApiError` handling consistent with existing code. |
| P5-02 | Route + navigation | `App.tsx`, `components/layout/Sidebar.tsx` | `/assistant` in the Workspace or Intelligence group; label matches product language. |
| P5-03 | Decision + context cards | `components/assistant/DecisionCard.tsx`, `MarketContextPanel.tsx` | LONG/SHORT/WAIT/NO TRADE as the primary state; regime, structure, momentum, volatility, liquidity, S/R, MTF; strategy id/version, generated/expiry; quality = rule completion, not probability. |
| P5-04 | Plan, next action, evidence | `TradePlanCard.tsx`, `NextActionCard.tsx`, `EvidenceList.tsx` | Entry zone, SL, TP1-3, RR, invalidation, confirmations; "Not available" for missing size; evidence for/against; one clear next step. |
| P5-05 | Chart overlay | `components/market/SetupOverlay.tsx` + optional props on `PriceChart`/`ForecastChart`/`ChartWorkspace` | Entry/SL/TP/invalidation layers toggle independently; PATRON predicted candles unchanged and separately toggleable; horizon + generated-at shown. |
| P5-06 | Data states | assistant components | loading, stale badge, Qwen unavailable, risk rejected, no-trade, expired; old setups never shown as current. |
| P5-07 | Tests + checks | `apps/desktop/src/components/assistant/*.test.tsx` | Card states, evidence rendering, stale/expired; run `npm run typecheck`, `npm run lint`, `npm run test`. |
| P5-08 | Report | `PHASE_5_RESULTS.md` | Screens are described; note that visual review was or was not performed. |

Do not: redesign existing pages, remove forecast visuals, or make the assistant page the default
route.

---

## 7. Phase 6 — Trade journal and monitoring

**Goal:** auditable lifecycle from proposal to close, with paper/manual trades only.
**Depends on:** Phase 5 (or Phase 3 for API-first). **Exit gate:** immutable audit rows; untriggered
setups excluded from losses; monitoring guidance derived from plan vs price.

| ID | Task | Files / symbols | Acceptance |
|---|---|---|---|
| P6-01 | Journal contracts + storage | `trade_journal/contracts.py`, `repository.py`, tables `trades`, `trade_events`, `setup_actions` | Append-only events; no UPDATE of audit rows; timestamps UTC; evidence refs. |
| P6-02 | Setup actions | `trade_journal/service.py` | `accept` / `reject` / `ignore` recorded with actor + note; state transitions per `06` §5. |
| P6-03 | Trade registration + lifecycle | `trade_journal/service.py` | Manual/paper trade creation from an accepted setup; entry/partial/exit events; invalid transitions rejected. |
| P6-04 | Monitoring guidance | `trade_journal/monitoring.py` | Rule-based: confirmation pending, invalidated, TP1 reached (partial rule), stop hit, expiry, re-evaluate; no "move stop further" advice. |
| P6-05 | API | `api/v1/trades.py` | `GET /trades`, `/trades/{id}`, `POST /trades/{id}/event`, `POST /setups/{id}/accept|reject`; no execution endpoint. |
| P6-06 | UI | `pages/JournalPage.tsx`, `components/assistant/ActiveTradeMonitor.tsx`, `SetupTimeline.tsx` | Active setups, open trades, completed, invalidated; PnL/SL distance/TP progress/invalidation warnings. |
| P6-07 | Tests + report | `tests/test_trade_journal.py`, `PHASE_6_RESULTS.md` | Lifecycle matrix, untriggered setup, immutability, API validation. |

---

## 8. Phase 7 — Outcome and failure analysis

**Goal:** evidence-based review of closed/expired setups, separating setup quality from result.
**Depends on:** Phase 6. **Exit gate:** classification matches the taxonomy; confidence labels
required; no speculative cause presented as fact; dataset-eligibility flag set only when criteria met.

| ID | Task | Files / symbols | Acceptance |
|---|---|---|---|
| P7-01 | Outcome metrics | `outcomes/metrics.py` | R multiple, MFE/MAE from recorded candles, fees/slippage, holding time; fixtures with hand-computed values. |
| P7-02 | Outcome classifier | `outcomes/analyzer.py` | `SUCCESS / LOSS / BREAKEVEN / INVALID_SETUP / EXECUTION_ERROR / INSUFFICIENT_DATA` from records, not hindsight narrative. |
| P7-03 | Failure taxonomy | `outcomes/failures.py` | Causes from `08` §4; each finding has evidence refs and `confirmed/probable/possible/unknown`. |
| P7-04 | PATRON alignment | `outcomes/analyzer.py` + `forecast_evaluations` | Use stored per-step direction correctness/band coverage; mark stale/missing forecast as `insufficient_data`, never guess. |
| P7-05 | Review workflow | `outcome_reviews` table, `outcomes/service.py` | `pending / reviewed / approved_for_dataset / excluded`; reviewer + note recorded. |
| P7-06 | API + UI | `api/v1/trades.py` review endpoints, `components/assistant/OutcomeReviewCard.tsx` | Planned vs actual, R, MFE/MAE, costs, versions, timeline, findings with confidence. |
| P7-07 | Tests + report | `tests/test_outcomes.py`, `PHASE_7_RESULTS.md` | Category fixtures, confidence enforcement, no-cause-without-evidence. |

---

## 9. Phase 8 — Dataset, evaluation and backtesting

**Goal:** leakage-safe, versioned dataset and a cost-aware, walk-forward evaluation before any
training.
**Depends on:** Phase 7. **Exit gate:** dataset audit blocks invalid data; final test sealed;
reproducible report; no fabricated metrics.

| ID | Task | Files / symbols | Acceptance |
|---|---|---|---|
| P8-01 | Repair evaluation package | `backend/app/evaluation/metrics.py`, `regimes.py` (missing today), `tests/test_evaluation_import.py` | `import app.evaluation` succeeds; metrics tested; no change to existing endpoints. |
| P8-02 | Point-in-time replay | `api/v1/replay.py` (additive) + stored snapshots | Replay a snapshot as of a past timestamp without future candles; verified by a lookahead test. |
| P8-03 | Dataset builder + audit | `learning/dataset.py`, `learning/audit.py`, `learning/manifests.py`, tables `dataset_versions`, `dataset_cases` | Provenance, split, synthetic flag, duplicate/near-duplicate detection, leakage audit, manifest hash. |
| P8-04 | Walk-forward harness | `evaluation/walk_forward.py` | Chronological windows, purge/embargo, frozen rules, untouched final test. |
| P8-05 | Metrics + baselines | `evaluation/metrics.py` | Win rate, expectancy, profit factor, drawdown, MAE/MFE, costs, per-regime; no-trade and simple baselines; sample-size caveats. |
| P8-06 | Paper-trading gate | `learning/service.py` + journal | Minimum duration/sample configurable; paper results stored separately from backtest. |
| P8-07 | API | `api/v1/learning.py` | `GET /learning/status`, `POST /learning/datasets/prepare`; no training in this phase. |
| P8-08 | Tests + report | `tests/test_learning_dataset.py`, `PHASE_8_RESULTS.md` | Leakage test intentionally fails a bad dataset; reproducible manifest; gate pass/fail documented. |

Do not: report a strategy as validated on a sample too small to support it; compare against a
different cost model; optimize win rate alone.

---

## 10. Phase 9 — LoRA feasibility, evaluation and controlled promotion

**Goal:** decide with evidence whether a local adapter is viable, and make promotion reversible.
**Depends on:** Phase 8 pass. **Exit gate:** feasibility report with hardware facts; candidate vs
champion comparison on held-out cases; explicit approval; rollback drill performed.

| ID | Task | Files / symbols | Acceptance |
|---|---|---|---|
| P9-01 | Feasibility assessment | `docs/AI_TRADING_UPGRADE/LORA_FEASIBILITY.md` | Framework, memory, batch/seq length, quantization, adapter export/load compatibility with the pinned llama.cpp runtime; CPU fallback measured or rejected. No assumption from Vulkan inference support. |
| P9-02 | Isolated training environment | `training/` (outside backend runtime) + manifest | Reproducible config (base hash, dataset hash, seed, hyperparameters, code revision); must not alter `backend/requirements.txt`. |
| P9-03 | Job orchestration | `learning/training.py`, `training_jobs` table, `POST /learning/jobs` (flag + approval) | Candidate jobs only; never overwrite production weights; runs offline; inference stays available. |
| P9-04 | Candidate evaluation | `learning/evaluation.py`, `model_evaluations` | Base+RAG+tools vs candidate+same, on held-out structured tasks; regression checks (no-trade, tool use, risk explanations); measured latency/memory. |
| P9-05 | Registry, promotion, rollback | `learning/models.py`, `model_versions`, `GET /models`, `POST /models/{id}/promote|rollback` | Explicit operator approval; previous champion preserved; one-step rollback; audit fields. |
| P9-06 | UI | `pages/LearningPage.tsx` + model status panel | Dataset versions, job status, candidate metrics, active model, rollback target. |
| P9-07 | Tests + report | `tests/test_model_registry.py`, rollback drill, `PHASE_9_RESULTS.md` | Promotion blocked without approval; rollback restores previous; no production overwrite. |

Do not: auto-promote on a single good backtest; train on unreviewed outcomes; use chain-of-thought
as supervision.

---

## 11. Dependency graph and gate summary

```text
C0 ─► P1 ─► P2 ─► P3 ─┬─► P4 ─┐
                      └─► P5 ─┴─► P6 ─► P7 ─► P8 ─► P9
```

| Gate | Question answered | Blocking evidence |
|---|---|---|
| G0 | Is the baseline understood and preserved? | these four Phase 0 documents + 152-test baseline |
| G1 | Is market context correct and reproducible? | frozen fixtures, stale/invalid rejection, snapshot timing |
| G2 | Are strategies explicit and honestly rejectable? | 60-case matrix, WAIT/NO_TRADE, conflict handling |
| G3 | Are plans and risk numerically safe? | invariant tests, observe default, `not_calculated` sizing |
| G4 | Does Qwen explain without inventing or overriding? | validator tests, tool audit, measured latency |
| G5 | Can a user understand the next action? | state coverage, independent chart layers, PATRON preserved |
| G6 | Is the lifecycle auditable? | immutable journal, untriggered-setup handling |
| G7 | Are outcomes explained from evidence? | taxonomy + confidence + PATRON alignment |
| G8 | Is there a leakage-safe, cost-aware dataset and evaluation? | audit blocking bad data, sealed test, reproducible report |
| G9 | Is a model change justified and reversible? | feasibility report, champion comparison, approval + rollback drill |

---

## 12. Deferred backlog (not scheduled, kept visible)

| Item | Why deferred |
|---|---|
| Multi-symbol / multi-timeframe PATRON forecasts | Requires a PATRON change, which is forbidden here |
| `/ws/kie` load-progress push | SSE and request/response cover current needs |
| KIE badge/mode switch on every page | Assistant page covers the need; a global badge can follow Phase 5 |
| Vector database for RAG | Deterministic retrieval is sufficient at current corpus size; revisit with measurement |
| Live execution / exchange integration | Permanently out of scope for this project |
| Autonomous mode | Requires a separate security and compliance project |
| Strategy optimization / parameter sweeps | Only after Phase 8 gates and with predeclared methodology |
