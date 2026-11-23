# KBMTI AI Trading Upgrade — documentation index

**Plan version:** 1.0 (from `NEW_AI_UPDATE/`)
**Last updated:** 2026-11-23
**Scope:** AI market intelligence, strategy evaluation, trade planning, risk, journal,
outcome review and controlled learning — while preserving PATRON, the existing chat and
the existing API/UI contracts. No automatic order execution exists or will be added here.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture map, gap analysis, task plan | **Complete** — approved as the baseline |
| 1 | Market intelligence foundation: BTCUSDT M15 snapshot, trend, structure, momentum, volatility, regime, liquidity, persistence, two read-only endpoints | **Complete, pending gate review** |
| 2 | Strategy registry and candidate engine (`trend_pullback` first) | **Implementation complete** — automated 60/60 review done; acceptance PENDING human sign-off; case packets and proposed policy in `PHASE_2_GATE_CLOSURE.md` |
| 3 | Trade planner, validation and risk engine | **Complete, acceptance recommended** — strategy gate PENDING |
| 4 | Qwen trading intelligence: read-only tools, validator, deterministic retrieval | **Complete** — 10 read-only tools; live unified run validated |
| 5 | AI trading assistant UI and chart overlays | **Complete** — chart-first visual assistant, journal, learning pages + unified AI rail |
| 6 | Trade journal, lifecycle and monitoring | **Complete** — paper/manual records only |
| 7 | Outcome and failure analysis | **Complete** — review-gated dataset evidence |
| 8 | Dataset builder, walk-forward evaluation, backtesting | **Complete** — real 20k-bar run; no executable signals |
| 9 | LoRA feasibility, evaluation, promotion and rollback | **Complete** — training infeasible on this hardware; registry/rollback implemented |

Additional work completed after the original roadmap:

| Item | Status |
|---|---|
| Qwen-centric unified frontend pipeline | **Complete** — `/assistant/market-intelligence`; frontend migrated |
| PATRON accuracy audit and candidate retrain | **Complete** — numerical-sanity fix promoted; no alpha claim |
| PATRON champion/candidate evaluation | **Complete** — 2,517 held-out windows, baselines, calibration |
| PATRON predictive-edge research | **Complete — NO_DEMONSTRATED_EDGE** — four leakage-safe walk-forward folds; production unchanged |
| Real embedded Qwen unified run | **Complete** — 42.3 s, schema valid, all numbers verified |
| Qwen HTTP 502 investigation/fix | **Resolved for the reproduced failure** — OpenMP coexistence guard, correlation IDs, real Vulkan verification |
| Visual Trading Assistant | **Complete** — verified entry/SL/TP, structure, PATRON median, conditional scenarios |

## Documents

| Document | Purpose |
|---|---|
| [`REPOSITORY_AUDIT.md`](REPOSITORY_AUDIT.md) | Verified capability inventory, defects, constraints, preservation rules |
| [`EXISTING_ARCHITECTURE.md`](EXISTING_ARCHITECTURE.md) | Runtime topology, DI, data flows, schema/migration conventions, extension seams |
| [`IMPLEMENTATION_GAP_ANALYSIS.md`](IMPLEMENTATION_GAP_ANALYSIS.md) | Target-vs-actual mapping, contracts, DB/API/UI changes, risks, sequence |
| [`IMPLEMENTATION_TASKS.md`](IMPLEMENTATION_TASKS.md) | Phase task list, gates, test matrices, deferred backlog |
| [`PHASE_0_RESULTS.md`](PHASE_0_RESULTS.md) | Audit completion report and approved decisions |
| [`PHASE_1_RESULTS.md`](PHASE_1_RESULTS.md) | Market intelligence implementation, tests, measurements, limitations |
| [`PHASE_2_RESULTS.md`](PHASE_2_RESULTS.md) | Strategy engine implementation, rules, tests, provisional evaluation, PENDING gate |
| [`PHASE_2_EVALUATION.md`](PHASE_2_EVALUATION.md) | Evidence-based review of all 60 cases, aggregate validation, manual flags and gate decision |
| [`PHASE_2_EVALUATION.json`](PHASE_2_EVALUATION.json) | Provisional metrics, 60 cases with automated review fields and gate status |
| [`PHASE_2_REVIEW_EVIDENCE.json`](PHASE_2_REVIEW_EVIDENCE.json) | Reconstructed rule inputs and checks for all 60 cases |
| [`PHASE_2_REVIEW_RESULTS.json`](PHASE_2_REVIEW_RESULTS.json) | Per-case reviewed decisions, results, notes and review provenance |
| [`PHASE_2_GATE_CLOSURE.md`](PHASE_2_GATE_CLOSURE.md) | Human-review packets for cases 40/53, proposed aggregate acceptance policy and versioned rule-gap proposals |
| [`HUMAN_APPROVAL_WORKSPACE.md`](HUMAN_APPROVAL_WORKSPACE.md) | Blank human-decision records for cases 40/53, the aggregate policy and R-001/R-002 |
| [`PHASE_2_ACCEPTANCE_POLICY.md`](PHASE_2_ACCEPTANCE_POLICY.md) | `PROPOSED_NOT_APPLIED` policy, 60/60 human review and two-key closure rules |
| [`R-001_NO_SUPPORT_REFERENCE_SPEC.md`](R-001_NO_SUPPORT_REFERENCE_SPEC.md) | Implementation specification for missing support/resistance references, not applied |
| [`R-002_ADVERSE_CHOCH_SPEC.md`](R-002_ADVERSE_CHOCH_SPEC.md) | Implementation specification for adverse CHoCH expiry/invalidation, not applied |
| [`PHASE_3_RESULTS.md`](PHASE_3_RESULTS.md) | Trade geometry, risk policy, lifecycle, API, persistence, tests, measurements, acceptance |
| [`QWEN_FRONTEND_PIPELINE.md`](QWEN_FRONTEND_PIPELINE.md) | Unified market/PATRON/Qwen pipeline, API contract, live evidence, limits |
| [`QWEN_502_ROOT_CAUSE_AND_FIX.md`](QWEN_502_ROOT_CAUSE_AND_FIX.md) | HTTP 502 root cause, OpenMP coexistence fix, correlation IDs, tests and GPU evidence |
| [`QWEN_AMD_GPU_FIX_RESULTS.md`](QWEN_AMD_GPU_FIX_RESULTS.md) | Qwen availability root cause, Vulkan readiness gate, AMD GPU evidence, retest results |
| [`TRADING_INTELLIGENCE_READINESS_FIX.md`](TRADING_INTELLIGENCE_READINESS_FIX.md) | Bounded Qwen readiness wait, per-component readiness contract, PATRON conflict materiality, plan/size reasons, tests |
| [`VISUAL_TRADING_ASSISTANT_RESULTS.md`](VISUAL_TRADING_ASSISTANT_RESULTS.md) | Chart-first assistant UI, overlays, scenarios, data flow, tests, limitations |
| [`LIVE_QWEN_FRONTEND_EVIDENCE.json`](LIVE_QWEN_FRONTEND_EVIDENCE.json) | One real embedded-Qwen run through the unified path |
| [`PATRON_AUDIT_REPORT.md`](PATRON_AUDIT_REPORT.md) | Evidence-based PATRON root-cause audit and dataset quality |
| [`PATRON_IMPROVEMENT_RESULTS.md`](PATRON_IMPROVEMENT_RESULTS.md) | Candidate training, champion comparison, calibration, promotion and rollback |
| [`PATRON_AUDIT_METRICS.json`](PATRON_AUDIT_METRICS.json) | Champion held-out metrics and baselines |
| [`PATRON_CANDIDATE_METRICS.json`](PATRON_CANDIDATE_METRICS.json) | Promoted candidate held-out metrics |
| [`PATRON_ROLLING_STABILITY.json`](PATRON_ROLLING_STABILITY.json) | Four-block out-of-sample stability, champion/candidate/baselines and regimes |
| [`PATRON_PREDICTIVE_EDGE_PROTOCOL.md`](PATRON_PREDICTIVE_EDGE_PROTOCOL.md) | Pre-registered fold, metric and promotion protocol |
| [`PATRON_PREDICTIVE_EDGE_RESEARCH.md`](PATRON_PREDICTIVE_EDGE_RESEARCH.md) | Four-fold retraining/residual results, regimes, bootstrap inference and no-edge decision |
| [`PATRON_RESEARCH_DECISION.md`](PATRON_RESEARCH_DECISION.md) | Persistence benchmark rationale, no-edge decision and accuracy-vs-profitability boundary |
| [`NEXT_RESEARCH_PRIORITIES.md`](NEXT_RESEARCH_PRIORITIES.md) | Falsifiable follow-up research priorities; no production change |
| [`PATRON_PREDICTIVE_EDGE_RESULTS.json`](PATRON_PREDICTIVE_EDGE_RESULTS.json) | Machine-readable fold metrics, bootstrap intervals and promotion checks |
| [`PATRON_DATASET_QUALITY.json`](PATRON_DATASET_QUALITY.json) | Raw-data, target-alignment, causality and split evidence |
| [`LORA_FEASIBILITY.md`](LORA_FEASIBILITY.md) | Measured hardware constraints and no-training decision |
| [`BACKTEST_RESULTS.json`](BACKTEST_RESULTS.json) | Real 20,000-bar zero-trade backtest |

## Approved decisions (locked)

1. Market scope is **BTCUSDT M15 only**; other scopes return an explicit unsupported state.
2. Package layout: `app/analysis`, `app/strategies`, `app/trade_planning`, `app/risk`,
   `app/intelligence`, `app/trade_journal`, `app/outcomes`, `app/learning`.
3. Position sizing stays `not_calculated`; account balance/equity/contract size are never invented.
4. First strategy is `trend_pullback`; `breakout_retest` waits for its 60-case gate.
5. Git was initialized and a baseline commit was created before implementation.
6. Retrieval is versioned in-repository text with deterministic matching; no vector database.
7. `app/evaluation` repair is deferred to Phase 8 unless an earlier phase needs it.
8. LoRA training must use a separate environment; no training dependency is added to backend requirements.

## Running the checks

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check app tests scripts
```

The real-model KIE test remains opt-in (`-m kie_runtime`).
The latest full backend run is **298 passed, 1 deselected, 1 warning**; frontend is
**33 tests passed**, with clean TypeScript, ESLint and production build.
The provisional strategy evaluation is separate and read-only:

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe scripts/evaluate_trend_pullback.py
```

## Non-negotiable boundaries

- PATRON's inference contract and training data are preserved; the approved accuracy work changed only quantile-head initialisation and candidate training, documented in `PATRON_IMPROVEMENT_RESULTS.md`.
- The predictive-edge research found no candidate that beats persistence; production remains unchanged and no alpha claim is made.
- `/api/v1/chat/*` and all pre-existing endpoints keep their current contracts.
- No Ollama, llama-server, cloud inference, shell execution, broker orders or account fabrication.
- `WAIT`/`NO_TRADE` are valid outcomes; stale, invalid or insufficient data never produces a fabricated analysis.
