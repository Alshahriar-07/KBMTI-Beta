# KBMTI AI Trading Upgrade — Phase 0 Results

**Phase:** 0 — repository audit and design lock
**Date:** 2026-11-19
**Status:** **complete, pending review/approval.** Phase 1 has not started.
**Scope executed:** read-only inspection, gap analysis, task planning, documentation. No application
code, configuration, PATRON artifact or UI was modified.

---

## 1. What was done

1. Read all 16 files in `NEW_AI_UPDATE/`: `readme.md`, `README_main.md`, `PLAN_MANIFEST.json`,
   `01_MASTER_UPDATE_PLAN.md` … `14_ACCEPTANCE_TESTS.md`.
2. Read the existing KIE plan and results: `docs/KIE_INTEGRATION_PLAN.md`,
   `docs/KIE_PHASE_A_RESULTS.md`, `docs/KIE_PHASE_B_RESULTS.md`.
3. Inspected the complete backend (`backend/app/`, 81 Python modules, ~15.7k lines): app factory,
   composition root, all 13 routers (66 route decorators), market data and both providers, MT5
   gateway, indicators, signals, forecasting + PATRON adapter + automation, chat, KIE (contracts,
   config, model manager, core, planner, workflow, tools, runtime, repository, responder),
   persistence schema and repositories, system monitor.
4. Inspected the desktop client (`apps/desktop/src/`, ~8.3k lines TS/TSX): routes, sidebar, state
   providers, polling/stream hooks, API client, chart components, UI primitives, tests.
5. Inspected PATRON as a dependency: package/wheel, model card, configs, checkpoints layout,
   training scripts and experiment folders (not executed, not modified).
6. Ran repository-wide searches to confirm absent capabilities (strategy, risk, trade planning,
   journal, backtest, drawdown, position sizing, swings/BOS/CHoCH, regime, liquidity, VWAP).
7. Ran the existing backend test suite and ruff once to establish the baseline.
8. Produced the four planning documents listed in §2 plus this report.

---

## 2. Deliverables created

| Document | Content |
|---|---|
| `docs/AI_TRADING_UPGRADE/REPOSITORY_AUDIT.md` | Method, snapshot, capability inventory by domain, API/persistence/frontend inventory, defects (A1–A10), unverified items, preservation constraints |
| `docs/AI_TRADING_UPGRADE/EXISTING_ARCHITECTURE.md` | Runtime topology, package map, DI/composition, request/data flows (market→indicators→signals, PATRON→forecast→evaluation, chat, KIE), schema and migration conventions, API conventions, frontend architecture, extension seams, testing architecture, constraining facts |
| `docs/AI_TRADING_UPGRADE/IMPLEMENTATION_GAP_ANALYSIS.md` | Component-by-component reuse/extend/new map, non-duplication rules, proposed package layout, contract additions, DB/API/UI/KIE changes, dependencies, runtime limits, data-quality rules, test matrix, risks, recommended sequence |
| `docs/AI_TRADING_UPGRADE/IMPLEMENTATION_TASKS.md` | Cross-cutting tasks (C0-1…C0-6), phased tasks with files/symbols/acceptance, test matrices, dependency graph, gates G0–G9, deferred backlog |
| `docs/AI_TRADING_UPGRADE/PHASE_0_RESULTS.md` | This report |

### 2.1 Mapping to the specification pack's requested documents

`NEW_AI_UPDATE/readme.md` asks for four `docs/KBMTI_*.md` documents; the Phase 0 brief asks for the
five documents above. The content is consolidated rather than duplicated:

| Pack document | Covered by |
|---|---|
| `KBMTI_AI_TRADING_UPGRADE_MASTER_PLAN.md` | `IMPLEMENTATION_GAP_ANALYSIS.md` §1, §14 + `IMPLEMENTATION_TASKS.md` §11 |
| `KBMTI_AI_TRADING_DATA_ARCHITECTURE.md` | `EXISTING_ARCHITECTURE.md` §4–§5 + `IMPLEMENTATION_GAP_ANALYSIS.md` §4–§5, §11 |
| `KBMTI_AI_TRADING_UI_SPECIFICATION.md` | `EXISTING_ARCHITECTURE.md` §7 + `IMPLEMENTATION_GAP_ANALYSIS.md` §7 + `IMPLEMENTATION_TASKS.md` Phase 5 |
| `KBMTI_QWEN_TRAINING_STRATEGY.md` | `IMPLEMENTATION_GAP_ANALYSIS.md` §8–§9, §12 + `IMPLEMENTATION_TASKS.md` Phase 4 and Phase 9 |
| `KBMTI_TRADE_OUTCOME_LEARNING_PLAN.md` | `IMPLEMENTATION_GAP_ANALYSIS.md` §11–§12 + `IMPLEMENTATION_TASKS.md` Phases 6–8 |

If separately named files are required for a release packet, they can be generated from these
sections without new analysis.

---

## 3. Checks actually run (raw results)

| Check | Command | Result |
|---|---|---|
| Backend test baseline | `cd backend && PYTHONPATH=. .venv/Scripts/python.exe -m pytest` | **152 passed, 1 deselected, 1 warning in 35.86 s** |
| Backend lint baseline | `cd backend && .venv/Scripts/python.exe -m ruff check app tests scripts` | **All checks passed!** |
| `app.evaluation` import | `PYTHONPATH=. .venv/Scripts/python.exe -c "import app.evaluation"` | **Failed:** `ModuleNotFoundError: No module named 'app.evaluation.metrics'` (defect A1 confirmed) |
| Absent-capability search | ripgrep over `backend/app` + `apps/desktop/src` for strategy/risk/journal/backtest terms | Only match outside KIE: `PRAGMA journal_mode=WAL` |
| Route inventory | `grep -rhoE "@router\.(get\|post\|delete\|put\|patch)\(" backend/app/api/v1` | **66** endpoints (plus `/ws/market`) |
| Schema inventory | `grep -c "CREATE TABLE" backend/app/persistence/db.py`; manual read | **12 tables** (+3 bespoke idempotent migrations; no schema-version table) |
| Test inventory | file listing + test-name counts | **15** backend test modules; **4** frontend vitest files |

The deselected test is `tests/test_kie_runtime_smoke.py` (`kie_runtime` marker). It was not run in
this audit, so no real-model numbers are re-claimed here.

### 3.1 Not run (and why)

| Check | Reason |
|---|---|
| Frontend `npm run typecheck`, `lint`, `test` | No UI code was changed; not required to establish the backend/UI inventory. Their current pass state is therefore **not** claimed. |
| Real KIE model load / inference | Opt-in slow test; no Phase 0 claim depends on it. Phase B's measured numbers are cited as prior evidence only. |
| MT5 terminal / broker session | Requires the user's terminal; only code paths were inspected. |
| Live forecast/PATRON checkpoint verification | Not re-hashed; the runtime computes checkpoint SHA-256 in `PatronInferenceService.status()`. |
| Any LoRA training | Explicitly out of scope for Phase 0 and unproven on this hardware. |

---

## 4. Findings that change the plan

| # | Finding | Consequence for the plan |
|---|---|---|
| F1 | PATRON is fixed to BTCUSDT M15 (provider rejects other symbols/timeframes; automation hard-coded). | Phase 1 must be scoped to BTCUSDT M15. Multi-symbol is not a config change; it requires a forbidden PATRON change. |
| F2 | MT5 account balance/equity and instrument contract size are deliberately not exposed (`mt5_gateway.py`), only masked login, leverage, currency, digits/point, volume min/step, bid/ask. | Position sizing cannot be computed. Phase 3 must return `not_calculated` + `INSUFFICIENT_ACCOUNT_INPUTS` until explicit account inputs are approved. Risk caps still apply. |
| F3 | `backend/app/evaluation/__init__.py` imports `metrics` and `regimes`, which do not exist; importing the package fails. Nothing imports it today. | Phase 8 must repair it; any earlier reuse requires a small, explicit repair task. Add an import smoke test. |
| F4 | No strategy/risk/journal/backtest code exists at all (single grep match is WAL journal mode). | 18 of the 20 mapped target components need new modules; the phasing in `IMPLEMENTATION_TASKS.md` is not optional. |
| F5 | KIE tools registry is empty and the model cannot fetch KBMTI data. | Phase 4 must add read-only tools before Qwen can explain a plan; until then it only sees the prompt context block. |
| F6 | The desktop client has no `/kie` calls and no assistant surface. | Phase 5 is a genuinely new page, not a panel tweak. KIE load state is invisible to users today. |
| F7 | Database migrations are bespoke idempotent `_ensure_*` helpers (ALTER + one table rebuild), no Alembic/version table. | New phases add tables to `SCHEMA_STATEMENTS`; any column change must follow the guarded pattern and be restart-safe. |
| F8 | The project root is not a git repository. | A multi-phase upgrade has no diff/revert safety net. C0-1 recommends `git init` before Phase 1 (needs approval). |
| F9 | Existing test baseline is 152 passed / 1 deselected; ruff clean. | Phase gates can use this as the regression baseline without guessing. |

Other confirmed facts carried into the plan: single-flight KIE with 4096 context; ~19.4 tok/s decode,
~1.1 s TTFT at a 192-token prompt, ≈3.3 GB buffers at 4096 ctx (Phase B evidence); PATRON is CPU-only;
no execution path exists anywhere; `WAIT`/`NO_TRADE` are already first-class in the signal engine.

---

## 5. Phase 0 acceptance criteria

Per `12_IMPLEMENTATION_ROADMAP.md` Phase 0: *architecture map, compatibility plan and test plan
approved.*

| Criterion | Status | Evidence |
|---|---|---|
| Actual KBMTI backend, UI, DI, API, chart and PATRON adapter inspected | **Pass** | `REPOSITORY_AUDIT.md` §3–§6; `EXISTING_ARCHITECTURE.md` §2–§8 |
| Existing KIE plan and Phase A/B reports read; Phase B scope confirmed | **Pass** | `EXISTING_ARCHITECTURE.md` §2, §9; KIE modules read; 49 KIE tests counted in the 152-test baseline |
| Existing modules mapped to the plan without duplicate abstractions | **Pass** | `IMPLEMENTATION_GAP_ANALYSIS.md` §2, §2.1 |
| Gap report and implementation task list produced | **Pass** | `IMPLEMENTATION_GAP_ANALYSIS.md`, `IMPLEMENTATION_TASKS.md` |
| Compatibility plan (existing APIs, chat, PATRON, chart, config) | **Pass** | `IMPLEMENTATION_GAP_ANALYSIS.md` §6, §13; `REPOSITORY_AUDIT.md` §10 |
| Test plan per phase | **Pass** | `IMPLEMENTATION_GAP_ANALYSIS.md` §12; `IMPLEMENTATION_TASKS.md` phase test matrices |
| No code changes before approval | **Pass** | Only the five Markdown files in §2 were created |
| No PATRON change, no training, no UI redesign, no production config change | **Pass** | No file under `PATRON/`, `backend/app/patron/`, `apps/desktop/` or runtime config was edited |
| Approval of the plan | **Pending** | Requires the user's review; therefore Phase 0 is *complete but not accepted* |

**Honest limitations of this phase:** the audit is a static/read-through of the repository plus one
test-suite run. It does not prove runtime behaviour of the assistant (it does not exist yet), does
not validate the frontend toolchain's current state, and does not re-measure model performance.
Severity judgements (e.g. A1 "High, latent") are engineering judgements, not production incidents.

---

## 6. Decisions requested before Phase 1

1. **Scope lock:** approve Phase 1 as **BTCUSDT M15 only**, with explicit `unsupported` states for
   everything else until a separately approved PATRON change exists. (Recommended.)
2. **Package layout:** approve the `app/analysis`, `app/strategies`, `app/trade_planning`,
   `app/risk`, `app/intelligence`, `app/trade_journal`, `app/outcomes`, `app/learning` layout in
   `IMPLEMENTATION_GAP_ANALYSIS.md` §3, or supply preferred names before code is written.
3. **Account inputs:** confirm that position sizing stays `not_calculated` in Phase 3, and that no
   balance/equity is to be read from MT5 or invented. If account inputs are required, a separate
   approved change must define their source, storage and privacy handling.
4. **Strategy order:** confirm `trend_pullback` as the first strategy (Phase 2), with
   `breakout_retest` only after the first passes its 60-case gate. (Recommended; both are research
   candidates in `05` §3.)
5. **Version control:** approve `git init` (and an initial baseline commit) before Phase 1, or accept
   file-list-only change tracking in every phase report.
6. **RAG approach:** approve deterministic, versioned in-repo retrieval for Phase 4, deferring any
   vector database until a measured need exists. (Recommended.)
7. **Evaluation repair:** approve fixing `app/evaluation` (implement `metrics.py` + `regimes.py` and
   an import test) either as a small task in Phase 1 or as the first task of Phase 8. (Recommended:
   Phase 8, unless earlier phases need the metrics.)
8. **Training environment:** confirm that Phase 9's LoRA work is expected to run in a **separate
   environment** and that no training dependency will be added to `backend/requirements.txt`.
   (Recommended; local training viability on the RX 580 is currently unproven.)

---

## 7. Recommended next step

On approval, execute **C0 (cross-cutting) then Phase 1 — Market context and deterministic analysis**:
snapshot contracts with `as_of` enforcement, BTCUSDT M15 trend/structure/momentum/volatility/regime
(and liquidity if time-budget allows), persistence in `market_snapshots`, `GET /api/v1/market/context`
+ `/market/analysis`, frozen-fixture tests, and `PHASE_1_RESULTS.md` with measured snapshot timing.

Do not start Phase 2 until the Phase 1 gate is accepted; do not start fine-tuning or training at any
point in Phases 1–8.
