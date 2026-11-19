# KBMTI AI Trading Upgrade — Phase 0 Repository Audit

**Audit date:** 2026-11-19
**Auditor:** implementation agent (Buffy), Phase 0 only
**Scope:** read-only inspection of the repository, the `NEW_AI_UPDATE/` specification pack, the
existing KIE Phase A/B work, the PATRON integration, the FastAPI backend, the SQLite schema, and
the React/Tauri desktop client. **No application code was modified.**

This document records only what was verified in the repository at the paths quoted. Where a
capability is absent, that is stated explicitly. Where something was not exercised during the
audit, it is listed under *Not verified*.

---

## 1. Method

1. Read every Markdown file in `NEW_AI_UPDATE/` plus `PLAN_MANIFEST.json`:
   `readme.md`, `README_main.md`, `01_MASTER_UPDATE_PLAN.md` … `14_ACCEPTANCE_TESTS.md`.
2. Read the existing KIE documents: `docs/KIE_INTEGRATION_PLAN.md`,
   `docs/KIE_PHASE_A_RESULTS.md`, `docs/KIE_PHASE_B_RESULTS.md`.
3. Enumerated and read the backend modules under `backend/app/` (81 Python modules,
   ~15.7k lines), including `container.py`, `main.py`, `api/v1/*`, `chat/`, `indicators/`,
   `signals/`, `forecasting/`, `patron/`, `persistence/`, `kie/`, `market_data/`, `system/`.
4. Enumerated the desktop client under `apps/desktop/src/` (~8.3k lines TS/TSX), its routes,
   state providers, chart components and API client.
5. Inspected the PATRON package layout (`PATRON/`), its model card, configs, training scripts and
   the integration point in `backend/app/patron/service.py` and
   `backend/app/forecasting/patron_provider.py`.
6. Searched the whole codebase for strategy, risk, journal, backtest, position-sizing, structure,
   regime and liquidity code to confirm what does **not** exist.
7. Ran the existing backend test suite once to establish the baseline
   (`PYTHONPATH=. .venv/Scripts/python.exe -m pytest`).

---

## 2. Repository snapshot

| Item | Verified value |
|---|---|
| Project version | `kbmti` **1.2.0** (`pyproject.toml`, `apps/desktop/package.json`) |
| Backend Python | 3.12.10, `backend/.venv` (per `docs/KIE_INTEGRATION_PLAN.md` §3.1 and the venv in use) |
| Backend framework | FastAPI + Uvicorn + Pydantic v2 + psutil (`backend/requirements.txt`) |
| Analysis libraries present | `numpy`, `pandas` (already required) |
| PATRON runtime | `torch==2.4.1` CPU + `pyarrow`, `jsonschema`, `PyYAML`, `scikit-learn` (`backend/requirements-patron.txt`) |
| PATRON package | `PATRON/patron-1.0.0b1-py3-none-any.whl`, model `patron-1.0.0`, release `1.0.0-beta.1` |
| LLM runtime | in-process llama.cpp Vulkan/CPU DLLs via `ctypes` (KIE Phase A), pinned build b12503 |
| LLM weights | `Qwen3-4B-Q4_K_M.gguf` (git-ignored, downloaded by script; manifest + SHA-256 in repo) |
| Database | SQLite, 12 tables, additive `CREATE TABLE IF NOT EXISTS` migration style (`backend/app/persistence/db.py`) |
| Frontend | React 19 + TypeScript 6 + Vite 8 + Tailwind 4 + `lightweight-charts` 5 + Tauri 2 |
| Repo VCS state | **The project root is not a git repository** (`git rev-parse` → *not a git repository*). Change tracking is manual. |
| OS / hardware | Windows, AMD RX 580 8 GB, 16 GB RAM class machine (documented in `docs/KIE_INTEGRATION_PLAN.md` §9) |

### Backend test baseline (run during this audit)

```
PYTHONPATH=. .venv/Scripts/python.exe -m pytest
→ 152 passed, 1 deselected, 1 warning in 35.86s
```

The deselected test is `tests/test_kie_runtime_smoke.py` (marker `kie_runtime`, opt-in because it
loads the 2.4 GB GGUF and touches the GPU). This matches the claim in
`docs/KIE_PHASE_B_RESULTS.md`.

Backend test files and sizes: `test_api.py` (20), `test_candles.py` (7), `test_chat.py` (7),
`test_desktop_launcher.py` (6), `test_forecast_automation.py` (9), `test_forecast_contract.py` (11),
`test_indicators.py` (9), `test_kie_api.py` (12), `test_kie_core.py` (37), `test_kie_runtime.py` (7),
`test_kie_runtime_smoke.py` (1), `test_patron.py` (5), `test_persistence.py` (7),
`test_signals.py` (7), `test_symbols.py` (6).

Frontend tests exist but were **not** executed in this audit:
`apps/desktop/src/components/market/SignalDistribution.test.tsx`,
`apps/desktop/src/components/ui/AiNotice.test.tsx`,
`apps/desktop/src/lib/forecast.test.ts`, `apps/desktop/src/lib/format.test.ts`.

---

## 3. Capability inventory (verified)

Status legend: **Implemented** = working code with tests; **Partial** = some of the target
capability exists but important parts are missing; **Absent** = no implementation found.

### 3.1 Market data and market context

| Capability | Status | Evidence |
|---|---|---|
| Live market data, two providers | Implemented | `backend/app/market_data/manager.py` (`MarketDataService`), `providers/binance.py` (`BinanceMarketDataProvider`), `service.py` (`MT5MarketDataProvider`), `mt5_gateway.py` (`MT5Gateway`) |
| Symbol selection / listing | Implemented | `api/v1/market.py` `/market/symbol`, `/market/symbols`; `market_data/symbols.py` |
| Timeframe selection | Implemented | `core/timeframes.py` (`Timeframe`: M1, M5, M15, M30, H1, H4, D1), `/market/timeframe`, `/settings/timeframes` |
| Candles + forming candle API | Implemented | `api/v1/market.py` `/market/candles`, `market_data/candles.py`, `market_data/state.py` |
| WebSocket live stream | Implemented | `app/main.py` `/ws/market`, `market_data/broadcaster.py`, `hooks/useMarketStream.ts` |
| Staleness / freshness tracking | Implemented | `Settings.stale_after_seconds` (`core/config.py`), snapshot `data_state`, signal `freshness` |
| Tick persistence | Implemented | `market_ticks` table, `TickRepository` |
| Candle persistence | Implemented | `market_candles` table, `CandleRepository` |
| Immutable timestamped analysis snapshot contract | **Absent** | No `snapshot_id`, no feature-version envelope, no provenance object beyond live payload fields |
| Market regime classification | **Absent** | No regime code anywhere (grep for `regime` only finds the broken `app/evaluation` docstring) |
| Multi-timeframe analysis | **Absent** | `ChatService._timeframes` explicitly states cross-timeframe comparison is not calculated (`backend/app/chat/service.py:315`) |

### 3.2 Indicators and deterministic technical analysis

| Capability | Status | Evidence |
|---|---|---|
| EMA 9/21/50, RSI 14, MACD, Bollinger, ATR 14 | Implemented | `backend/app/indicators/engine.py` (`compute_indicators`, `IndicatorBundle`) |
| Indicator API payload (series + latest) | Implemented | `api/v1/indicators.py`, `IndicatorBundle.to_payload()` |
| Indicator snapshots persisted | Implemented | `indicator_snapshots` table |
| Rule-based bias engine with evidence / conflicts / invalidation | Implemented | `backend/app/signals/engine.py` (`evaluate_signal`, `SignalResult`, `Factor`, `BUY_BIAS`/`SELL_BIAS`/`WAIT`/`NO_CLEAR_SETUP`) |
| Signal persistence + history API | Implemented | `signals/service.py` (`SignalService`), `signal_snapshots` table, `/signals/history` |
| Swing high/low structure (HH/HL/LH/LL) | **Absent** | No swing detection module; chat’s `_levels` only reports max/min over the last 60 candles (`chat/service.py:292`) |
| BOS / CHoCH | **Absent** | — |
| Support / resistance zones, supply/demand | **Absent** | — |
| Liquidity pools / sweeps / stop runs | **Absent** | — |
| VWAP | **Absent** | Not in `indicators/engine.py` |
| Volume analysis beyond plain tick volume display | Partial | Volume is persisted and charted; no volume-feature calculation or confirmation logic |
| Momentum change / divergence detection | **Absent** | RSI/MACD levels are read; no divergence or rate-of-change feature |

### 3.3 PATRON (candle forecasting — must remain untouched)

| Capability | Status | Evidence |
|---|---|---|
| CPU PATRON inference, single model instance, lazy/single-flight load | Implemented | `backend/app/patron/service.py` (`PatronInferenceService`, `ensure_loaded`, `forecast_from_candles`, `infer_with`, `status`, `health`, `readiness`) |
| Fixed contract: BTC/USDT, 15m, 96-candle window, 384 warm-up bars, 6 future candles | Implemented | `patron/service.py` constants `WARMUP_BARS`, `SEQUENCE_LENGTH`, `MODEL_ID`; enforced in `forecasting/patron_provider.py` |
| Quantile forecast output (q10/q50/q90 per step, high/low/close) | Implemented | `PatronForecastProvider.run()` → `metadata["patron"]["range_quantiles"]`; derived candle geometry in `_to_candles` |
| Forecast run persistence | Implemented | `forecast_runs`, `forecast_candles` tables; `ForecastRepository` |
| Automatic forecast scheduling on closed M15 BTCUSDT bar | Implemented | `forecasting/automation.py` (`ForecastAutomation`), wired in `container.py` `route_binance_event` |
| Forecast evaluation against realised candles (error, direction correctness, q10–q90 band) | Implemented | `ForecastService.evaluate()` (`forecasting/service.py:293`), `forecast_evaluations` table, `ForecastRepository.evaluation_summary()` |
| Predicted-candle chart | Implemented | `apps/desktop/src/components/market/ForecastChart.tsx` (hatched, labelled `P1..Pn`, explicit legend) |
| Read-only forecast adapter for a new intelligence layer | **Absent** | No adapter module; `ForecastService.latest()/get_run()` exist but are shaped for the existing UI |
| PATRON training pipeline | Present but **out of scope** | `PATRON/scripts/train.py`, `train_multiseed.py`, `run_training.ps1|sh`, `PATRON/experiments/*`. Must not be modified or triggered. |

### 3.4 KIE (Qwen3-4B intelligence engine)

| Capability | Status | Evidence |
|---|---|---|
| Vulkan/CPU backend selection, explicit fallback, buffer-based VRAM budget | Implemented | `backend/app/kie/model_manager.py` (`ModelManager`, `parse_buffers`, `parse_offloaded_layers`, `SingleFlight`) |
| Context 4096 default, single active inference, bounded queue | Implemented | `kie/config.py` (`KieConfig`), `KieBusyError` (429) |
| Run lifecycle, cancellation, timeout, persistence | Implemented | `kie/core.py` (`KieCore.run/cancel/status`), `kie/repository.py`, `kie_runs` table |
| Reasoning policy + CONTEXT block | Implemented | `kie/reasoning.py`, `kie/responder.py` (`context_payload`) |
| Planner / workflow controller / tool engine foundation | Implemented (foundation only) | `kie/planner.py`, `kie/workflow.py`, `kie/tools/{registry,engine}.py` |
| Registered KBMTI tools | **Absent** | `KieService.__init__` creates `ToolRegistry()` (`kie/service.py:123`) and registers nothing; `GET /kie/tools` returns an empty list |
| `/api/v1/kie` API (status/models/tools/load/unload/chat/chat-stream/cancel/runs) | Implemented | `api/v1/kie.py` |
| Chat integration | Implemented but **dark** | `KieResponder` in `kie/responder.py`; enabled only when `KBMTI_KIE_CHAT_RESPONDER=1` (default `0`); falls back to `RuleBasedResponder` |
| Knowledge base / RAG | **Absent** | No embedding store, no document corpus, no retrieval code |
| Fine-tuning / LoRA support in the runtime | **Absent** | The runtime shim (`kie/runtime/bindings.py`) is inference-only (`llama_model_load`, `llama_decode`, sampling); no training API is bound |
| UI surfacing of KIE | **Absent** | `apps/desktop/src/lib/api.ts` contains no `/kie` call; no KIE panel, badge or mode switch anywhere in `apps/desktop/src` |

### 3.5 Trade intelligence, strategy, risk, journal, learning

A repository-wide search was run for `strategy|stop_loss|take_profit|position_size|journal|r_multiple|backtest|drawdown`.
**The only match outside KIE is `PRAGMA journal_mode=WAL` in `persistence/db.py:206`.**

| Target component | Status |
|---|---|
| Market Intelligence Engine | Absent (only indicator snapshot + rule-based bias exist) |
| Market Structure Engine | Absent |
| Momentum Analysis Engine | Absent as a module (RSI/MACD readings only) |
| Volatility Analysis Engine | Absent as a module (ATR value only) |
| Liquidity Analysis Engine | Absent |
| Multi-Timeframe Analysis Engine | Absent |
| Strategy Knowledge Base | Absent |
| Strategy Evaluation Engine | Absent |
| Trade Setup Engine | Absent |
| Signal Validation Engine | Absent |
| Risk Management Engine | Absent |
| Trade Management Engine | Absent |
| Trade Assistant UI | Absent |
| Trade Journal | Absent |
| Trade Outcome Analyzer | Absent (PATRON forecast scoring is the only outcome-like evaluation) |
| Dataset Builder | Absent |
| LoRA Training Pipeline | Absent |
| Model Evaluation / Version Management | Absent (KIE reports the model that is loaded; there is no registry, promotion or rollback) |

### 3.6 Chat

| Capability | Status | Evidence |
|---|---|---|
| Deterministic rule-based chat | Implemented | `backend/app/chat/service.py` (`ChatService`, `RuleBasedResponder`, `ChatContext`) |
| Conversations, messages, suggestions | Implemented | `ChatRepository`, `chat_conversations`, `chat_messages`, `api/v1/chat.py` |
| Chat grounded in snapshot/signal/forecast/PATRON | Implemented | `ChatService.build_context()`; `KieResponder.context_payload()` projects the same context |
| Optional LLM responder with deterministic fallback | Implemented, disabled by default | `KieResponder`, `Settings` flag `KIE_CHAT_RESPONDER` via `kie/config.py` |

---

## 4. API surface inventory (all verified route decorators)

Prefix `/api/v1` (`backend/app/api/v1/router.py`):

| Router | Endpoints |
|---|---|
| `health.py` | `GET /health` |
| `market.py` | `GET /market/snapshot`, `/market/candles`, `/market/symbols`, `/market/timeframes`, `/market/providers`, `/market/provider`; `POST /market/symbol`, `/market/timeframe`, `/market/provider`, `/market/connect`, `/market/reconnect`, `/market/disconnect`, `/market/refresh` |
| `mt5.py` | `GET /mt5/status`, `/mt5/terminal`, `/mt5/diagnostics`, `/mt5/history-check`, `/mt5/symbols`, `/mt5/symbols/{symbol}`; `POST /mt5/connect`, `/mt5/reconnect`, `/mt5/disconnect`, `/mt5/terminal`, `/mt5/test-connection` |
| `indicators.py` | `GET /indicators` |
| `signals.py` | `GET /signals/current`, `/signals/history` |
| `forecast.py` | `GET /forecast/status`, `/forecast/latest`, `/forecast/live`, `/forecast/timeline`, `/forecast/history`, `/forecast/{run_id}`; `POST /forecast/run`, `/forecast/evaluate` |
| `patron.py` | `GET /patron/status`, `/patron/info`, `/patron/health`, `/patron/readiness`; `POST /patron/load`, `/patron/infer` |
| `chat.py` | `GET /chat/suggestions`, `/chat/conversations`, `/chat/conversations/{id}/messages`; `POST /chat/conversations`, `/chat/conversations/{id}/messages`; `DELETE /chat/conversations/{id}`, `/chat/conversations/{id}/messages` |
| `kie.py` | `GET /kie/status`, `/kie/models`, `/kie/tools`, `/kie/runs`, `/kie/runs/{id}`; `POST /kie/load`, `/kie/unload`, `/kie/chat`, `/kie/chat/stream`, `/kie/cancel` |
| `system.py` | `GET /system/status` |
| `settings.py` | `GET /settings`, `/settings/timeframes`; `PATCH /settings` (chart/data/ui/mt5 preferences) |
| `diagnostics.py` | `GET /diagnostics`, `/diagnostics/logs` |
| `replay.py` | `GET /replay/window` (candle stepping only; message says point-in-time PATRON replay is not implemented) |

WebSocket: `/ws/market` (`app/main.py`).

No endpoint in the codebase accepts an order, a broker credential, or a shell command.

---

## 5. Persistence inventory

`backend/app/persistence/db.py` creates these tables (all `IF NOT EXISTS`):

| Table | Purpose | Repository |
|---|---|---|
| `app_settings` | key/value UI + market preferences | `SettingsRepository` |
| `market_candles` | OHLCV cache | `CandleRepository` |
| `market_ticks` | tick cache | `TickRepository` |
| `signal_snapshots` | persisted bias results | `SignalRepository` |
| `indicator_snapshots` | created but **unused**: no repository, writer or reader references it (only the `CREATE TABLE` statement) | — |
| `forecast_runs` | PATRON run header | `ForecastRepository` |
| `forecast_candles` | predicted candles per run | `ForecastRepository` |
| `forecast_evaluations` | realised-vs-predicted per step | `ForecastRepository` |
| `chat_conversations` / `chat_messages` | chat history + context JSON | `ChatRepository` |
| `kie_runs` | KIE run metrics/status | `kie/repository.py` |
| `kie_tool_calls` | KIE tool audit rows (unused: no tools registered) | `kie/repository.py` |

`Database.initialize()` also runs three bespoke, idempotent migrations after the schema statements:
`_ensure_forecast_output_column`, `_ensure_evaluation_columns` (both `ALTER TABLE … ADD COLUMN`)
and `_ensure_candle_source_primary_key` (rebuilds a legacy `market_candles` table). There is no
Alembic and no schema-version table.

There is **no** setup/positions/trades/outcomes/datasets/models/strategies table.

---

## 6. Desktop client inventory

Routes (`apps/desktop/src/App.tsx`): `/` Overview, `/chart` Market Analysis, `/signals` Signal
Research, `/chat` AI Assistant, `/history` Forecasting, `/replay` Replay, `/settings`,
`/diagnostics` Model Status, `*` NotFound.

Key building blocks:

| Area | Files / symbols |
|---|---|
| Shell and navigation | `components/layout/AppShell.tsx`, `Sidebar.tsx` (`GROUPS` with Workspace/Intelligence/System), `StatusBar.tsx`, `MarketToolbar.tsx` |
| UI design system | `components/ui/{Panel,Badge,Button,DataRow,EmptyState,Meter,Segmented,Spinner,Toggle,AiNotice}.tsx`, Tailwind theme in `styles/global.css`, `lib/theme.ts` |
| Charts | `components/market/PriceChart.tsx` (lightweight-charts; EMA/BB/volume/RSI/MACD layers, `ChartSettings` toggles), `ForecastChart.tsx` (custom SVG, PATRON predicted-candle hatch), `ChartWorkspace.tsx` (layer menu) |
| Market panels | `MarketIntelligence.tsx` (quote, provenance, technical readings, bias), `BottomIntelligence.tsx` (PATRON preview/status strip), `SignalDistribution.tsx` |
| Market state | `state/MarketProvider.tsx`, `market-context.ts`, `live-candles.ts`, `hooks/useMarketStream.ts`, `hooks/usePolling.ts` |
| API client | `lib/api.ts` — covers health, market, indicators, signals, forecast, patron, chat, system, settings, diagnostics, replay. **No `/kie` and no trading endpoints.** |
| Tests | vitest + Testing Library; 4 test files (listed in §2) |

Everything the UI shows is read from existing endpoints. There is no trade plan, journal, outcome
or model-version screen to extend; those are new surfaces.

---

## 7. Test and quality infrastructure

- Pytest with a shared `conftest.py` that builds the app through `create_app`/`build_container`
  with fake providers (`tests/fake_mt5.py`).
- KIE has dedicated fakes: `tests/kie_fakes.py` (`FakeEngine`, `EngineFactory` with `failures`,
  `gate`, `chunk_delay`, `kv_mb`, `gpu_present`).
- Real-model tests are separated by the `kie_runtime` marker
  (`backend/pyproject.toml`: `addopts = "-q -m 'not kie_runtime'"`).
- `ruff` configuration exists in both root and backend `pyproject.toml` (E, F, I, B, UP).
- Frontend: `npm run typecheck`, `npm run lint`, `npm run test` scripts exist.
- No coverage gate, no CI configuration found in the repository.

---

## 8. Defects and inconsistencies found during the audit

These were discovered by inspection, not by changing code. Severity is relative to the upgrade.

| # | Finding | Severity | Evidence |
|---|---|---|---|
| A1 | `backend/app/evaluation/__init__.py` imports `app.evaluation.metrics` and `app.evaluation.regimes`, **which do not exist**. Importing `app.evaluation` raises `ModuleNotFoundError` (reproduced). Nothing imports it today, so the app boots; any new module that imports it will fail. | High (latent) | `ls backend/app/evaluation` → only `__init__.py`; `python -c "import app.evaluation"` → `ModuleNotFoundError: No module named 'app.evaluation.metrics'` |
| A2 | PATRON is hard-bound to BTC/USDT and M15 (`PatronForecastProvider.run` raises `ValidationError` otherwise). Only one symbol/timeframe can have a forecast. | Medium (scope constraint) | `forecasting/patron_provider.py:99-113` |
| A3 | Forecast auto-scheduling is hard-coded to `BTCUSDT` + `M15` closed bars. | Medium | `container.py` `route_binance_event` |
| A4 | MT5 account data deliberately excludes balances/equity and instrument contract size/margin; it exposes masked login, leverage, currency, `digits`, `point`, `volume_min`, `volume_step`, bid/ask. Position sizing therefore has no valid account input today. | High (blocks sizing) | `market_data/mt5_gateway.py:164-210` |
| A5 | `GET /kie/tools` returns an empty registry; the model cannot fetch market data itself. | Medium (by design, Phase C) | `kie/service.py:123`; `docs/KIE_PHASE_B_RESULTS.md` §8 |
| A6 | KIE is completely absent from the desktop client (`api.ts` has no `/kie`). Loading a model, mode selection and tool traces are invisible. | Medium (Phase E) | `apps/desktop/src/lib/api.ts` |
| A7 | LLM chat is dark by default (`KBMTI_KIE_CHAT_RESPONDER=0`); responses are deterministic rules only. | Low (intentional) | `kie/config.py`, `container.py` |
| A8 | `app/replay.py` explicitly limits itself to candle stepping; no point-in-time replay of PATRON or strategy state exists. Backtesting/paper trading has no harness. | High (blocks Phase 8 evidence) | `api/v1/replay.py` `REPLAY_MESSAGE` |
| A9 | Repository is not under git; there is no diff/revert safety net for a multi-phase upgrade. | Medium (process risk) | `git rev-parse` fails at project root |
| A10 | Two documentation sets disagree on the first deliverable names (`NEW_AI_UPDATE/readme.md` asks for `docs/KBMTI_*.md`; the task brief asks for `docs/AI_TRADING_UPGRADE/*.md`). This audit follows the task brief and maps the pack documents in `PHASE_0_RESULTS.md` §4. | Low | `NEW_AI_UPDATE/readme.md` §"Start with a repository audit" vs the Phase 0 brief |

Additional constraints confirmed, not defects:

- The KIE runtime is inference-only and single-flight; there is no training entry point and no
  second GPU process. Any LoRA work must be a separate offline job (Phase 7 of the roadmap).
- Context 4096 is the measured safe default; Phase B measured ≈3.3 GB of llama.cpp buffers at 4096.
- The desktop app talks to the backend over HTTP (`lib/api.ts`) and a WebSocket; adding endpoints is
  additive and does not require a Tauri change.

---

## 9. Not verified during this audit

| Item | Reason |
|---|---|
| Frontend test run, lint, typecheck | Audit was scoped to reading; running the Node toolchain was not required for Phase 0 and was not executed |
| Live MT5 terminal / broker account state | Requires the user’s terminal session; only the code paths were inspected |
| Real KIE model load in this session | Opt-in `kie_runtime` test not run now; Phase B reports the measured run (load 2.17 s, Vulkan, 37/37 layers, 2 982.7 MB, 19.4 tok/s) and those numbers are not re-claimed here |
| PATRON checkpoint presence/hash on disk | Not re-hashed in this audit; `PatronInferenceService.status()` computes it at runtime |
| Whether the RX 580 can sustain any LoRA training | Not attempted; the inference Vulkan stack proves nothing about training support |

---

## 10. Preservation constraints recorded for every later phase

1. `PATRON/` (code, configs, checkpoints, training scripts) and `backend/app/patron/service.py`
   must not be modified by this upgrade.
2. `backend/app/chat/service.py` — `ChatService`, `RuleBasedResponder`, and the `/api/v1/chat/*`
   response shapes — must remain byte-compatible. New intelligence may be added behind explicit
   flags, never by rewriting the rules engine.
3. Existing endpoints listed in §4 must keep their paths and payload keys; all new capabilities
   are additive.
4. No Ollama, `llama-server`, cloud inference, external inference server, or shell execution.
5. No automatic order placement, no exchange credentials, no account-balance invention.
6. No claim of profitability or calibrated probability without measurement.
7. `WAIT` and `NO_TRADE` remain first-class outcomes; a failed dependency must produce a safe
   degraded state, never a fabricated setup.
