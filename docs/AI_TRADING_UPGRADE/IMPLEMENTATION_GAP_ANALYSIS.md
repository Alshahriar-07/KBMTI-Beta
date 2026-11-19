# KBMTI AI Trading Upgrade — Implementation Gap Analysis

**Date:** 2026-11-19
**Basis:** `REPOSITORY_AUDIT.md` and `EXISTING_ARCHITECTURE.md` (both verified against the repository),
plus the `NEW_AI_UPDATE/` specification pack (`01`–`14`).
**Purpose:** map every target capability to what exists, decide reuse vs extension vs new code, and
list the database, API, UI, runtime, testing, risk and sequencing consequences. No code has been
written for this upgrade yet.

Status vocabulary used below:

- **Reuse** — the component exists and only needs a read-only adapter or wiring.
- **Extend** — an existing module is the right home, but it must gain contracts, fields or endpoints.
- **New** — no equivalent exists; a module must be created.
- **Defer** — intentionally not in the near phases (kept visible so it is not silently dropped).

---

## 1. Verdict in one page

KBMTI today is a **market-data + indicator + rule-bias + PATRON-forecast + deterministic-chat**
workstation. It has no strategy engine, no risk engine, no trade plan, no journal, no outcome
analysis, no dataset or model-version pipeline, and no LLM tools. The KIE inference foundation
(Phase A/B) is complete and measured, but the model cannot yet fetch KBMTI data, and nothing in the
desktop client calls `/api/v1/kie`.

Therefore the upgrade is roughly:

| Category | Count |
|---|---|
| Existing data sources **reused behind an adapter** | 3 (PATRON forecast + evaluation, indicator bundle, market feed/freshness) |
| Target components that **extend** existing modules | 2 (Qwen trading intelligence extends `app/kie`; Market Intelligence extends the indicator stack) |
| Target components that are **entirely new modules** | 18 of the 20 mapped rows in §2 |
| **Out of scope permanently** | live order execution (not "deferred") |

Two blocking facts shape the order of work:

1. **No account or instrument economics exist.** MT5 account balance/equity and contract size are
   deliberately stripped in `backend/app/market_data/mt5_gateway.py` (`_account_info_to_dict`,
   `_symbol_info_to_dict`). Position sizing and "risk amount" cannot be produced until explicit,
   validated account inputs are added — the plan forbids inventing them (`06` §2, §4; `13` §3).
2. **Only BTCUSDT M15 has a forecast.** `PatronForecastProvider.run()` rejects every other
   symbol/timeframe, and forecast automation is hard-coded to `BTCUSDT` + `M15` in
   `backend/app/container.py`. Multi-symbol or multi-timeframe claims would be false until that
   changes through a separately approved PATRON change (which this upgrade forbids). Phase 1 must
   therefore be scoped to **BTCUSDT M15**, with explicit `unsupported` states elsewhere.

A third, smaller blocker: `backend/app/evaluation/__init__.py` imports `app.evaluation.metrics` and
`app.evaluation.regimes`, which do not exist; the package raises `ModuleNotFoundError` when imported.
The evaluation/backtest work in Phase 8 needs that package, so it must be repaired (implement the
modules or replace the `__init__`) before it is used.

---

## 2. Component-by-component gap map

Target list from the brief §4 / plan §2. "Planned home" paths follow the existing `app/<domain>/`
convention and the seam list in `EXISTING_ARCHITECTURE.md` §9.

| # | Target component | Today | Disposition | Planned home |
|---|---|---|---|---|
| 1 | Market Intelligence Engine (regime, trend, structure, momentum, volatility, volume, zones) | Absent. Only `IndicatorBundle` values and a weighted bias (`signals/engine.py`) exist | **Extend + new** | `backend/app/analysis/` (context builder, trend, structure, momentum, volatility, liquidity, regime) |
| 2 | Market Structure Engine (swings, HH/HL/LH/LL, BOS, CHoCH) | Absent. Chat prints max/min of the last 60 candles only (`chat/service.py:292`) | **New** | `backend/app/analysis/structure.py` |
| 3 | Momentum Analysis Engine | Absent as a module (RSI/MACD readings only) | **New** | `backend/app/analysis/momentum.py` |
| 4 | Volatility Analysis Engine | Absent as a module (ATR value only) | **New** | `backend/app/analysis/volatility.py` |
| 5 | Liquidity Analysis Engine (equal highs/lows, sweep candidates) | Absent | **New** | `backend/app/analysis/liquidity.py` |
| 6 | Multi-Timeframe Analysis Engine | Absent by design (`chat/service.py:315` says cross-timeframe is not calculated) | **New, deferred to Phase 1b** | `backend/app/analysis/multi_timeframe.py`; requires fetching a second series per timeframe — API cost and latency must be measured |
| 7 | Strategy Knowledge Base | Absent | **New** | `backend/app/strategies/` (versioned Python definitions + `catalog.py`), plus `docs/knowledge/` or `backend/knowledge/` for curated documents |
| 8 | Strategy Evaluation Engine | Absent | **New** | `backend/app/strategies/engine.py` (`StrategyEngine.evaluate(snapshot) -> list[Candidate]`) |
| 9 | Qwen Trading Intelligence | Runtime exists (`kie/`), tools empty, no RAG, no validator | **Extend** | `backend/app/kie/tools/*` adapters, `kie/validation.py`, `kie/knowledge.py` |
| 10 | Trade Setup Engine | Absent | **New** | `backend/app/trade_planning/planner.py` (`TradePlanner.plan(candidate, snapshot)`) |
| 11 | Signal Validation Engine | Absent | **New** | `backend/app/trade_planning/validation.py` (schema, price ordering, evidence refs, expiry, action allow-list) |
| 12 | Risk Management Engine (position risk, caps, daily limits) | Absent; account data absent | **New, partially blocked** | `backend/app/risk/engine.py` + `backend/app/risk/limits.py`; sizing returns `not_calculated` until account/instrument inputs exist |
| 13 | Trade Management Engine (lifecycle, monitoring guidance) | Absent | **New (Phase 6)** | `backend/app/trade_journal/lifecycle.py` + `monitoring.py` |
| 14 | AI Trading Assistant UI | Absent. Existing pages/panels only cover market/forecast/chat | **New (Phase 5)** | `apps/desktop/src/pages/AssistantPage.tsx` + `components/assistant/*` |
| 15 | Trade Journal | Absent | **New (Phase 6)** | `backend/app/trade_journal/service.py`, new tables |
| 16 | Trade Outcome Analyzer | Absent. Only PATRON forecast scoring exists (`ForecastService.evaluate`) | **New (Phase 6/7)** | `backend/app/outcomes/analyzer.py`; reuse `forecast_evaluations` for forecast-alignment evidence |
| 17 | Failure Analysis Engine | Absent | **New (Phase 7)** | `backend/app/outcomes/failures.py` (taxonomy from `08` §4, confidence labels) |
| 18 | Dataset Builder | Absent | **New (Phase 7)** | `backend/app/learning/dataset.py`, `backend/app/learning/audit.py` |
| 19 | Qwen LoRA Training Pipeline | Absent. Runtime is inference-only; no training deps installed | **New, gated (Phase 7)** | `backend/app/learning/training.py` (job orchestration only) + a separate offline training environment; no training code in the inference process |
| 20 | Model Evaluation and Version Management | Absent. `KieService` reports which model is loaded; no registry/promotion/rollback | **New (Phase 8/9)** | `backend/app/learning/models.py`, `backend/app/learning/evaluation.py`, new tables |
| — | PATRON forecasting | Implemented and frozen | **Reuse read-only** | Adapter `backend/app/forecasting/readonly.py` (thin wrapper over `ForecastService.latest/get_run/evaluate`) |
| — | Market data, candles, freshness, WS | Implemented | **Reuse** | `market_data/*` unchanged; snapshot points at existing series |
| — | Indicators / snapshots | Implemented | **Reuse** | `indicators/engine.py` unchanged; analysis consumes `IndicatorBundle` |
| — | Rule-based bias | Implemented | **Reuse as one input**, not as the trade decision | `signals/engine.py` unchanged |
| — | Deterministic chat / KIE responder | Implemented, KIE dark | **Extend behind flags** | `chat/service.py` untouched; assistant answers through new endpoints and later a grounded responder |
| — | Replay (candles only) | Partial | **Extend in Phase 8** | `api/v1/replay.py`; point-in-time replay requires stored snapshots |

### 2.1 What must explicitly *not* be duplicated

- Do not create a second indicator library. `app/indicators/engine.py` already covers EMA/RSI/MACD/
  Bollinger/ATR; new features (VWAP, ATR percentile, swing detection) go into
  `app/analysis/` and may call `indicators.engine` helpers.
- Do not create a second forecast or PATRON adapter. `ForecastService` + `forecast_runs` +
  `forecast_evaluations` are the source of truth.
- Do not create a second LLM runtime, prompt stack or queue. Everything goes through
  `KieService`/`KieCore`/`ModelManager`.
- Do not create a second HTTP client or chart implementation in the desktop app. Extend
  `lib/api.ts`, `PriceChart`/`ForecastChart`.
- Do not create a parallel chat system. The assistant page reads new endpoints; chat remains
  `/api/v1/chat/*`.

---

## 3. Proposed package layout (new code, existing conventions)

```text
backend/app/
  analysis/                  # Phase 1
    contracts.py             MarketSnapshot, Feature, AnalysisBundle, freshness/provenance
    context.py               MarketContextBuilder.build(symbol, timeframe) -> MarketSnapshot
    trend.py                 EMA stack, slope, trend score
    structure.py             SwingPoint, structure events (HH/HL/LH/LL, BOS, CHoCH)
    momentum.py              RSI/MACD change, ROC, divergence candidates
    volatility.py            ATR, ATR percentile, band width, volatility state
    liquidity.py             equal highs/lows, sweep candidates, stop-run proxies
    regime.py                rule-based regime classification (trending/ranging/volatile/uncertain)
    service.py               AnalysisService: cache, staleness, persistence, status
  strategies/                # Phase 2
    contracts.py             StrategyDefinition, CandidateSetup, RejectionReason
    catalog.py               versioned registry of concrete strategies
    base.py                  protocol + shared condition helpers
    trend_pullback.py        first strategy (M15 BTCUSDT)
    breakout_retest.py       second strategy (only after the first passes gates)
    engine.py                StrategyEngine.evaluate(snapshot) -> candidates + rejections
    service.py               reads snapshots/catalog, persists strategy_evaluations
  trade_planning/            # Phase 3
    contracts.py             TradePlan, EntryZone, Target, Invalidation, Expiry
    planner.py               deterministic entry/SL/TP construction from a candidate
    validation.py            ordering, tick alignment, RR, expiry, evidence refs
    service.py               TradePlanService: plan + validate + persist trade_setups
  risk/                      # Phase 3
    contracts.py             RiskConfig, RiskAssessment, PositionSizing
    engine.py                caps, daily loss, consecutive losses, exposure
    sizing.py                instrument-aware sizing (returns not_calculated until inputs exist)
  intelligence/              # Phase 4 (thin, KIE-facing)
    contracts.py             DecisionEnvelope (action, evidence refs, uncertainty)
    prompt.py                system/instruction template for structured JSON output
    validator.py             schema + cross-check against deterministic values
    service.py               orchestrates tools -> Qwen -> validator -> envelope
  kie/validation.py          # Phase 3/4: validate model JSON against contracts
  kie/knowledge.py           # Phase 4: RAG retrieval (versioned docs, IDs in trace)
  kie/tools/market.py        # Phase 4: get_market_snapshot, get_indicator_snapshot, ...
  kie/tools/forecast.py      # Phase 4: get_patron_forecast (read-only)
  kie/tools/strategies.py    # Phase 4: list_strategy_candidates, get_strategy_definition
  kie/tools/planning.py      # Phase 4: calculate_trade_plan, validate_trade_plan
  trade_journal/             # Phase 6
    contracts.py             SetupRecord, TradeRecord, TradeEvent, MonitoringState
    repository.py            append-only event persistence
    service.py               lifecycle transitions, accept/reject, monitoring
    monitoring.py            rule-based guidance from prices vs plan
  outcomes/                  # Phase 6/7
    contracts.py             OutcomeReport, FailureFinding, ReviewStatus
    metrics.py               R, MFE/MAE, fees, holding time
    analyzer.py              outcome classification from recorded evidence
    failures.py              failure taxonomy with confirmed/probable/possible/unknown
  learning/                  # Phase 7/8/9
    dataset.py               dataset candidate builder
    audit.py                 leakage/duplicate/provenance gates
    manifests.py             dataset + model manifests and hashes
    training.py              offline job orchestration (no inference-process training)
    evaluation.py            structured-task + regression comparison
    models.py                model registry, promotion, rollback
    service.py               status/report facade
  evaluation/                # Phase 8 repair + extension
    metrics.py               (missing today; implement)
    regimes.py               (missing today; implement)
    walk_forward.py          chronological windows, purge/embargo
```

Frontend:

```text
apps/desktop/src/pages/AssistantPage.tsx
apps/desktop/src/pages/JournalPage.tsx            # Phase 6
apps/desktop/src/pages/LearningPage.tsx           # Phase 8/9 (status, versions)
apps/desktop/src/components/assistant/
  DecisionCard.tsx  MarketContextPanel.tsx  TradePlanCard.tsx  NextActionCard.tsx
  EvidenceList.tsx  SetupTimeline.tsx  ActiveTradeMonitor.tsx  OutcomeReviewCard.tsx
apps/desktop/src/components/market/
  SetupOverlay.tsx            # chart layer: entry zone, SL, TP1-3, invalidation
```

---

## 4. Contract additions (typed, versioned)

All new request/response bodies use Pydantic v2 models in the owning package (existing
`schemas/models.py` is for the older domains; KIE already keeps its contracts in
`app/kie/contracts.py`). Every analysis/setup response carries the common metadata required by
`11` §3:

`request_id`, `generated_at`, `data_as_of`, `is_stale`, `symbol`, `timeframe`,
`strategy_version`, `patron_model_version`, `qwen_model_version`, `risk_engine_version`,
`evidence_refs[]`, `warnings[]`.

Core contracts to introduce, in dependency order:

1. `MarketSnapshot` / `FeatureValue` (`analysis/contracts.py`) — immutable, `snapshot_id`,
   `feature_version`, per-feature `value`, `unit`, `valid`, `unavailable_reason`, `source`,
   `calculated_at`.
2. `StructureState`, `MomentumState`, `VolatilityState`, `LiquidityState`, `RegimeState` — each
   with `version` and evidence IDs.
3. `StrategyDefinition` / `CandidateSetup` (`strategies/contracts.py`) — mirrors `05` §5, adds
   `expires_at`, `conditions_met`, `conditions_missing`, `rejection_reasons`.
4. `TradePlan` / `RiskAssessment` (`trade_planning`, `risk`) — mirrors `06` §2; every numeric field
   is `float | None` with `not_calculated` semantics; no fabricated size.
5. `DecisionEnvelope` (`intelligence/contracts.py`) — mirrors `11` §4 exactly; this is what the UI
   renders and what the validator signs off.
6. `SetupRecord`, `TradeEvent`, `TradeRecord`, `OutcomeReport`, `FailureFinding` — immutable
   journal contracts; `08` §2/§4.
7. `DatasetManifest`, `TrainingJob`, `ModelVersion`, `EvaluationReport` — `04` §7, `09` §5/§8.

Rules for these contracts:

- No contract may make a field optional just to avoid deciding. Unavailable data is an explicit
  state, not `null` without meaning.
- Version strings live next to the code (`STRATEGY_VERSION`, `FEATURE_VERSION`, `RISK_ENGINE_VERSION`),
  and are copied into every persisted row.
- Contracts are validated at the boundary (API and LLM output) and again before persistence.

---

## 5. Database changes (additive only)

Convention: `backend/app/persistence/db.py` schema tuple of `CREATE TABLE/INDEX IF NOT EXISTS`,
followed by idempotent `_ensure_*` migration helpers (the existing database uses this pattern for
`output_json`, the evaluation columns and the `market_candles` provider key). There is no Alembic and
no schema-version table. Each phase adds its own new tables; any change to an existing table must be
a guarded, idempotent `_ensure_*` step and must not rewrite audit-critical data.

| Phase | New tables | Key columns |
|---|---|---|
| 1 | `market_snapshots` | `id TEXT PK`, `symbol`, `timeframe`, `as_of TEXT`, `data_state`, `feature_version`, `source`, `payload_json`, `created_at`; index `(symbol, timeframe, as_of DESC)` |
| 2 | `strategy_evaluations` | `id TEXT PK`, `snapshot_id`, `strategy_id`, `strategy_version`, `action`, `conditions_met_json`, `conditions_missing_json`, `rejection_json`, `expires_at`, `created_at` |
| 3 | `trade_setups` | `id TEXT PK`, `snapshot_id`, `candidate_id`, `strategy_id/version`, `side`, `status`, `entry_low`, `entry_high`, `stop`, `tp1`, `tp2`, `tp3`, `risk_reward`, `risk_assessment_json`, `evidence_json`, `confirmation_json`, `invalidation_json`, `expires_at`, `created_at`; immutable rows |
| 3 | `risk_assessments` | `id`, `setup_id`, `config_version`, `approved INTEGER`, `violations_json`, `position_size`, `position_size_status`, `created_at` |
| 6 | `trades` | `id`, `setup_id`, `mode ('paper'|'manual')`, `side`, `status`, `quantity`, `entry_price`, `exit_price`, `fees`, `slippage`, `realized_pnl`, `r_multiple`, `mfe`, `mae`, `opened_at`, `closed_at`, `exit_reason` |
| 6 | `trade_events` | `id`, `trade_id`, `type`, `at`, `actor`, `reason`, `evidence_json`; append-only |
| 6 | `setup_actions` | `id`, `setup_id`, `action ('accepted'|'rejected'|'ignored'|'edited')`, `at`, `note`; append-only |
| 7 | `outcome_reviews` | `id`, `trade_id`, `outcome_class`, `findings_json`, `confidence`, `review_status`, `reviewer`, `created_at` |
| 7 | `dataset_versions` | `id`, `version`, `manifest_json`, `manifest_hash`, `status`, `approved_by`, `created_at` |
| 7 | `dataset_cases` | `id`, `dataset_version`, `case_json`, `split`, `label_source`, `is_synthetic`, `quality_flags_json` |
| 8/9 | `training_jobs` | `id`, `dataset_version`, `status`, `config_json`, `started_at`, `finished_at`, `report_json` |
| 8/9 | `model_versions` | `id`, `base_model`, `adapter_hash`, `dataset_version`, `evaluation_id`, `status ('candidate'|'champion'|'rejected'|'rolled_back')`, `created_at` |
| 8/9 | `model_evaluations` | `id`, `model_version`, `suite_version`, `metrics_json`, `regressions_json`, `pass INTEGER`, `created_at` |

Notes:

- `kie_runs` / `kie_tool_calls` already exist; Phase 4 populates `kie_tool_calls` by registering
  tools (columns are sufficient: `name`, `arguments_json`, `ok`, `error`, `duration_ms`,
  `truncated`, `confirmed_by`).
- JSON blobs stay TEXT, matching existing style. Timestamps stay ISO-8601 UTC strings.
- Immutability is enforced in repositories (no UPDATE of audit-critical rows), not by triggers.

---

## 6. API changes

### 6.1 New endpoints (additive; all read/compute, none execute)

| Phase | Endpoint | Purpose |
|---|---|---|
| 1 | `GET /api/v1/market/context` | current immutable snapshot + freshness/provenance |
| 1 | `GET /api/v1/market/analysis` | structure/momentum/volatility/regime bundle |
| 1 | `POST /api/v1/market/context/refresh` | rebuild snapshot on demand (rate-limited) |
| 2 | `GET /api/v1/strategies` | catalog with versions + status |
| 2 | `GET /api/v1/strategies/{id}` | definition, rules, known failure modes |
| 2 | `GET /api/v1/strategies/candidates` | latest candidates + rejection reasons |
| 3 | `POST /api/v1/trade-assistant/evaluate` | run snapshot → candidates → plan → risk → envelope |
| 3 | `GET /api/v1/trade-assistant/current` | latest decision envelope (stale-flagged) |
| 3 | `GET /api/v1/trade-assistant/plan/{setup_id}` | plan + risk assessment |
| 4 | `GET /api/v1/kie/tools` (existing) | now returns real read-only tools |
| 6 | `GET /api/v1/trades`, `GET /api/v1/trades/{id}` | journal |
| 6 | `POST /api/v1/trades/{id}/event` | record lifecycle event (manual/paper only) |
| 6 | `POST /api/v1/trades/{id}/review` | create/update outcome review |
| 7 | `GET /api/v1/learning/status` | dataset/case counters, job state |
| 7 | `POST /api/v1/learning/datasets/prepare` | build candidate dataset (no training) |
| 8 | `POST /api/v1/learning/jobs` | create offline training job (flag-gated, approval required) |
| 9 | `GET /api/v1/models/active`, `GET /api/v1/models` | model registry |
| 9 | `POST /api/v1/models/{id}/promote`, `POST /api/v1/models/{id}/rollback` | explicit operator promotion with audit |

`GET /api/v1/patron/forecast` from the pack is covered by the existing
`GET /api/v1/forecast/latest` + `/forecast/{run_id}`; adding an alias is unnecessary duplication.
Document the mapping instead.

### 6.2 Existing endpoints

- No path, payload key or status code of an existing endpoint changes.
- `/api/v1/chat/*` keeps `RuleBasedResponder` as the default engine. The KIE responder remains
  opt-in and must fall back on every failure.
- `/api/v1/kie/status` stays compatible; new fields may be added, none removed.
- `/api/v1/settings` gains an additive settings group (`assistant`, `risk`) only when Phase 3
  defines its schema; missing keys mean defaults, and defaults mean "not configured → no plan".

### 6.3 Error codes (new, machine-readable)

`MARKET_DATA_STALE`, `PATRON_UNAVAILABLE`, `QWEN_UNAVAILABLE`, `RISK_VALIDATION_FAILED`,
`NO_ELIGIBLE_STRATEGY`, `SETUP_EXPIRED`, `INSUFFICIENT_ACCOUNT_INPUTS`,
`LEARNING_JOB_NOT_APPROVED`, plus existing `KIE_*` codes. Implemented as `ApiError` subclasses in
`backend/app/core/errors.py` (or the owning package) so the existing handler renders them.

---

## 7. UI changes

| Phase | Surface | Details |
|---|---|---|
| 5 | New route `/assistant` (Workspace or Intelligence group in `Sidebar.tsx` `GROUPS`) | `DecisionCard` (LONG/SHORT/WAIT/NO TRADE + strategy/version/expiry/quality), `MarketContextPanel`, `TradePlanCard`, `NextActionCard`, `EvidenceList` |
| 5 | Chart integration | add optional overlay props to `PriceChart`/`ForecastChart`: entry zone, SL, TP1-3, invalidation; independently toggleable; never merged with predicted candles |
| 5 | States | loading, `stale`, `model unavailable`, `risk-rejected`, `no-trade`, `expired`; stale badge mandatory; no "current" styling for old setups |
| 6 | `/journal` page | active setups, open (paper/manual) trades, completed trades, failed/invalidated setups, review cards |
| 6 | `ActiveTradeMonitor` panel | entry/current price, unrealized PnL, SL distance, TP progress, invalidation warnings |
| 7 | `/learning` page | dataset versions, case counts, job status, evaluation results, active model, rollback target |
| 9 | model status | active model version, adapter hash, evaluation date, promotion state (read-only unless operator action is approved) |

Design constraints: reuse `Panel`, `Badge`, `DataRow`, `EmptyState`, `Meter`, `Toggle`, tokens and
type scale; do not restyle existing pages; do not remove or visually merge the PATRON predicted
candles; show `Not available` rather than a guessed number.

`lib/api.ts` and `lib/types.ts` gain the matching typed calls. There is no frontend dependency to
add for these surfaces.

---

## 8. Qwen / KIE changes

| Work | Phase | Details |
|---|---|---|
| Read-only tool adapters | 4 | `get_market_snapshot`, `get_indicator_snapshot`, `get_structure_snapshot`, `get_patron_forecast`, `list_strategy_candidates`, `get_strategy_definition`, `calculate_trade_plan`, `validate_trade_plan`, `get_open_trade_state`, `get_trade_outcome`, `get_strategy_performance`. All `Access.READ`; JSON-schema args; bounded output (existing truncation in `kie/tools/engine.py`); audit rows in `kie_tool_calls` |
| Tool-call loop | 4 | Phase B `Planner` emits one `answer` step; add a bounded tool step (max 2 rounds, per-call timeout) with a strict "no numeric claims" instruction |
| Structured output + validator | 3/4 | JSON envelope per `11` §4; validator recomputes/verifies every number against the snapshot/plan, rejects unknown evidence IDs and out-of-order prices, returns a typed error |
| RAG knowledge base | 4 | versioned documents with IDs, retrieval before prompt; document IDs echoed in traces; no unverifiable "facts" |
| Chat responder | 5/6 | keep dark until the UI can show which engine answered; then measure fallback rate under load before enabling |

Measured constraints (Phase A/B, not re-measured in Phase 0): 4096 context default, ~19.4 tok/s
decode, ~1.1 s TTFT at a 192-token prompt, single active generation, queue 3/30 s. A 2-round tool
loop therefore costs roughly one prefill per round plus generation; Phase 4 must publish measured
end-to-end latency before the UI depends on it.

---

## 9. Dependencies

| Need | Decision |
|---|---|
| Deterministic analysis | No new dependency. `numpy` and `pandas` are already required and used by `indicators/engine.py` |
| API/contracts | No new dependency. Pydantic v2 already used |
| Storage | No new dependency. SQLite via stdlib `sqlite3` |
| RAG | No vector database dependency for Phase 4. Start with a small, versioned in-repo document corpus and deterministic keyword/section retrieval, or an embedded index built at startup. A vector store is a separate decision with a measured need |
| LoRA training | `peft`/`transformers`/`datasets` are **not** installed and are not in any requirements file. Training must be a separate, explicitly approved environment; adding them to `backend/requirements.txt` would change the inference environment and is not approved |
| Frontend | No new dependency for the assistant UI; charts and primitives already exist |

---

## 10. Runtime and hardware limitations

Verified facts from the existing Phase A/B documents (not new measurements):

- Backend runs on Windows with Python 3.12; the RX 580 8 GB is used through Vulkan **inference**
  only. The llama.cpp DLL shim binds no training API.
- KIE: 4096 ctx default; measured ≈3.3 GB of llama.cpp buffers (model 2 375.91 + KV 576 + compute
  ~325 MiB); load 2.17 s; decode 19.4 tok/s; prefill ~1.1 s for a 192-token prompt; single active
  generation; CPU fallback is slower (Phase A: 10.96 tok/s decode; TTFT 8.9 s at a 525-token
  prompt and 42.2 s at 2 064 tokens, versus 3.0 s / 12.4 s on Vulkan for the same prompts).
- PATRON is CPU-only PyTorch, fixed 96-candle window + 384 warm-up bars, BTCUSDT M15, 6 candles.
- No MSVC/CMake/Vulkan SDK on the machine, so runtime replacement or source builds are out;
  no GPU training assumption is justified.
- Tool loops, multi-timeframe analysis and RAG retrieval all compete for the same CPU and the
  single inference slot. One analysis snapshot per request should be cached and shared.

Design limits to enforce in code:

- Analysis snapshot build target ≤ 250 ms for cached candles, ≤ 2 s with a provider refresh.
- Decision envelope target ≤ 10 s with Qwen (single generation, no tool round) and ≤ 20 s with one
  tool round; if exceeded, return `QWEN_UNAVAILABLE`/degraded deterministic envelope
  (`WAIT`/`NO_TRADE`) rather than a partial actionable plan.
- KIE must never be required for `/market/*`, `/signals/*`, `/forecast/*`, `/chat/*` or app startup.

These are **targets**, not measurements; Phase 4 must measure and report actual latency.

---

## 11. Data-quality and leakage requirements

1. **Single source of truth per snapshot.** Every feature records `data_as_of`, source provider and
   `feature_version`; a snapshot is rebuilt when the last closed candle changes.
2. **No lookahead.** Structure/momentum/volatility features may read only candles with
   `open_time + timeframe_seconds <= snapshot.as_of`. Swing confirmation must use closed bars only.
   The last (forming) candle is excluded from structure calculations.
3. **Outcome labels are separate.** Future candles and realised outcomes never appear in model
   input; they live only in `outcomes`/`dataset_cases` metadata.
4. **Chronological splits with purge/embargo** for any supervised dataset (`04` §4).
5. **No fabricated history.** PATRON covers BTCUSDT M15 only; do not synthesize other symbols.
6. **Providers differ.** Binance `BTCUSDT` and MT5 broker symbols (suffixes, spreads, session
   hours) are not interchangeable. A snapshot must name its provider; strategy evaluation must not
   mix providers silently.
7. **Duplicate prevention.** One active setup per strategy/side per symbol/timeframe unless a
   strategy explicitly allows stacking; near-duplicate dataset cases are rejected.

---

## 12. Testing requirements (mapped to `14_ACCEPTANCE_TESTS.md`)

| Area | New tests required | Existing coverage to protect |
|---|---|---|
| Market context | frozen OHLCV fixtures → trend/structure/momentum/volatility/regime; invalid OHLCV rejected; stale detection; feature-version presence | `test_indicators.py`, `test_signals.py` |
| Strategy engine | each condition true/false; WAIT when confirmation missing; NO_TRADE when nothing eligible; conflicting strategies; version + expiry + evidence present | `test_signals.py` |
| Trade planner | LONG stop below entry / targets above; SHORT inverse; zero stop distance rejected; tick alignment; RR math; expiry | none |
| Risk | cap enforcement; daily loss; consecutive losses; missing account inputs → `not_calculated`; stale data blocks plan | none |
| Qwen | JSON schema validation; numeric cross-check rejects invented values; tool request on missing context; cannot override risk; no-trade behavior | `test_kie_core.py`, `test_kie_api.py` |
| Journal | immutable rows; setup actions recorded; untriggered setup ≠ losing trade; R/MFE/MAE fixtures; fees/slippage | none |
| Outcomes | classification per category; confidence labels; evidence refs required | none |
| Learning | provenance/split metadata; leakage audit blocks bad datasets; promotion requires approval; rollback restores previous | none |
| API | additive contracts; error codes; existing endpoints unchanged | `test_api.py`, `test_chat.py`, `test_forecast_contract.py` |
| Regression | PATRON outputs unchanged; forecast chart data contract unchanged; chat byte-compatible; KIE unavailable → degraded | `test_patron.py`, `test_chat.py`, `test_kie_*` |
| UI | decision card states; chart layers independent; stale/unavailable/expired rendering | 4 vitest files today |

Policy: deterministic fixtures only; no fabricated backtest metrics; a test may not be weakened to
make a phase pass. Real-model/training tests stay in separate opt-in markers.

---

## 13. Risks and migration

| Risk | Consequence | Mitigation |
|---|---|---|
| Scope is 19 subsystems | Months of work collapsed into one change, half-finished surfaces | Phase gates from `12`; one strategy and one UI page at a time; no phase starts before the previous exit report |
| LLM invents levels/numbers | Unsafe, misleading trade plans | Deterministic planner owns numbers; validator rejects unsupported values; UI renders only validated fields |
| Missing account data | Fabricated position size or missing risk control | `not_calculated` + `INSUFFICIENT_ACCOUNT_INPUTS`; add explicit account inputs only with approval |
| PATRON scope creep | Breaks the forecasting model or its chart | Read-only adapter; no edits under `PATRON/` or `app/patron/`; contract tests unchanged |
| Broken `app/evaluation` package | Phase 8 cannot import evaluation code | Repair/replace in Phase 8 (or earlier, with approval); add an import smoke test |
| Lookahead / duplicate cases | Model learns hindsight | Snapshot `as_of` enforcement, closed-bar-only features, purge/embargo, dataset audit gate |
| Overfitting a strategy on a small sample | Confident but fragile signals | Predeclared gates, walk-forward, untouched test, cost-aware metrics, no win-rate-only optimization |
| KIE latency/queue saturation | UI stalls, 429s | Cache snapshots/plans; no LLM in the numeric path; bounded tool rounds; timeouts; deterministic fallback |
| VRAM/RAM pressure | Model load failure or host instability | Keep 4096 ctx / 4096 MB budget; single-flight; unload path; no training during inference |
| No git history | Cannot diff/revert a phase | Every phase report lists exact changed files; recommend initializing git before Phase 1 (needs approval) |
| Duplicate abstractions | Two sources of truth for forecasts, indicators or chat | Follow §2.1; extend existing modules |
| Timestamp/timezone mismatch | Wrong `data_as_of`, stale badges | All internal times UTC ISO-8601; candle times epoch seconds; tests freeze the clock |
| Silent provider switch (Binance ↔ MT5) | Inconsistent analysis | Snapshot records provider; strategy/plan reject provider mismatch |

Migration notes:

- No table is altered; old databases keep working, new tables are created on startup.
- No existing endpoint changes shape; the desktop client can be upgraded independently.
- New settings default to **disabled/observe**, so an unconfigured install shows no trade plans.
- The upgrade must remain functional when Qwen is unavailable: analysis, strategies, plans and risk
  are deterministic; only explanation/degraded prose depends on the model.

---

## 14. Recommended implementation sequence

Order is dictated by data correctness first and by the plan's explicit warning not to start with
fine-tuning (`12` "Critical implementation instruction").

| Order | Phase | Scope | Size | Exit gate |
|---|---|---|---|---|
| 0 | Audit | this document set | done | approved |
| 1a | Market snapshot + analysis | contracts, BTCUSDT M15 snapshot builder, trend/structure/momentum/volatility/regime, freshness, persistence, `GET /market/context`, `/market/analysis` | L | frozen fixtures pass; snapshots reproducible; invalid/stale data rejected |
| 1b | Liquidity + multi-timeframe (optional within 1) | equal highs/lows, sweep candidates; M15+H1 alignment | M | explicit `unavailable` when the second series cannot be fetched |
| 2 | Strategy engine | catalog + `trend_pullback` first; WAIT/NO_TRADE/rejections; versioning; historical harness | L | candidates explainable and rejectable; 60-case selection benchmark from the KIE plan repurposed as a rule-selection fixture |
| 3 | Trade planner + risk | entry/SL/TP, RR, tick alignment, expiry, caps, `not_calculated` sizing | L | all invariants tested; no plan without risk approval |
| 4 | Qwen intelligence | tools, validator, RAG, structured envelope, measured latency | L | model explains only validated values; cannot override risk; degrades safely |
| 5 | Assistant UI | `/assistant`, cards, chart overlays, states | L | user can see why/what invalidates; stale/unavailable states visible |
| 6 | Journal + monitoring | setups, actions, paper/manual trades, lifecycle events, review cards | L | full auditable lifecycle; untriggered setups excluded from losses |
| 7 | Outcome + failure analysis | R/MFE/MAE, taxonomy, review status, dataset eligibility | M | evidence-based findings with confidence labels |
| 8 | Dataset + evaluation + backtest | leakage audit, dataset versions, walk-forward, repair `app/evaluation` | L | reproducible dataset manifest + cost-aware report |
| 9 | LoRA feasibility + promotion | separate training environment, candidate vs champion, approval, rollback | XL (gated) | no promotion without held-out improvement and approval; rollback tested |

Dependency chain: 1 → 2 → 3 → (4, 5 can overlap after 3) → 6 → 7 → 8 → 9.
Phase 4 must not start before Phase 3, otherwise Qwen has no authoritative plan to explain.
Phase 8 must not start before Phase 6, otherwise there are no outcomes to evaluate.
Phase 9 must not start before Phase 8 passes; training on unvalidated labels is explicitly rejected
by `03` §2 and `09` §2.

### Explicitly out of scope, now and later in this project

- Replacing PATRON or changing its objective/training.
- Automatic live order placement or exchange credentials.
- Cloud/Ollama/llama-server inference.
- Autonomous execution mode.
- Promising profitability or calibrated probabilities without measurement.
