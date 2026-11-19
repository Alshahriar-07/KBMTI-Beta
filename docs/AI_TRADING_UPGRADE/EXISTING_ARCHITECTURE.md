# KBMTI — Existing Architecture (Phase 0 baseline)

**Status:** description of the system as it exists on 2026-11-19, before any upgrade work.
**Companion documents:** `REPOSITORY_AUDIT.md` (capability inventory), `IMPLEMENTATION_GAP_ANALYSIS.md`
(target-vs-actual mapping).

Everything below was read from the repository. File paths are relative to the project root
`AI TREDER/`.

---

## 1. Runtime topology

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Windows desktop process                                              │
│  Tauri 2 shell  ──►  React 19 SPA (apps/desktop)                     │
│                       │  HTTP          │  WebSocket                   │
│                       ▼                ▼                             │
│  FastAPI backend (backend/app, one process)                          │
│   ├── MarketDataService ──► Binance REST/WS  or  MetaTrader 5 (read-  │
│   │                        only, via MetaTrader5 package)            │
│   ├── SignalService ──► indicators + rule engine                     │
│   ├── ForecastService ──► PatronForecastProvider ──► PATRON (CPU)    │
│   ├── ForecastAutomation (closed 15m bar scheduler)                  │
│   ├── ChatService ──► RuleBasedResponder [or KieResponder if enabled]│
│   ├── KieService ──► ModelManager ──► llama.cpp DLLs (Vulkan/CPU)    │
│   │                                  └─► Qwen3-4B GGUF (in-process)  │
│   └── SQLite database (backend data dir)                             │
└──────────────────────────────────────────────────────────────────────┘
```

There is **one** backend process. There is no inference server, no Ollama, no subprocess model,
no cloud call. PATRON and KIE both run inside the FastAPI process.

---

## 2. Backend package map

| Package / file | Responsibility | Key symbols |
|---|---|---|
| `backend/app/main.py` | App factory, lifespan, routers, WebSocket, logging | `create_app(settings, gateway, binance, binance_history, patron, kie, start_polling, configure_logs)`, `lifespan` |
| `backend/app/container.py` | Composition root | `AppContainer` (dataclass), `build_container(...)` |
| `backend/app/api/deps.py` | DI accessor | `get_container`, `ContainerDep` |
| `backend/app/api/v1/router.py` | `/api/v1` aggregation | `api_router` (prefix `/api/v1`) |
| `backend/app/core/config.py` | Env-driven settings | `Settings`, `get_settings()`, `KBMTI_*` env names, `stale_after_seconds`, `default_timeframe`, `patron_*`, `forecast_*` |
| `backend/app/core/timeframes.py` | Timeframe enum + MT5 mapping | `Timeframe` (M1…D1), `TIMEFRAME_SECONDS`, `TIMEFRAME_MT5_CONSTANT`, `DEFAULT_TIMEFRAME` |
| `backend/app/core/errors.py` | Typed API errors | `ApiError`, `ValidationError`, `ForecastUnavailableError`, … |
| `backend/app/market_data/` | Feed abstraction, providers, cache, stream | `MarketDataService` (`manager.py`), `MT5MarketDataProvider` (`service.py`), `BinanceMarketDataProvider` (`providers/binance.py`), `MT5Gateway` (`mt5_gateway.py`), `BinanceHistoryClient` (`binance_history.py`), `Broadcaster` (`broadcaster.py`), `CandleSeries`/candle helpers (`candles.py`), symbol registry (`symbols.py`) |
| `backend/app/indicators/engine.py` | Pure pandas indicator math | `compute_indicators`, `IndicatorBundle`, `ema`, `rsi`, `macd`, `bollinger`, `atr`, `true_range` |
| `backend/app/signals/` | Explainable rule-based bias | `evaluate_signal` (`engine.py`), `SignalResult`, `Factor`, `SignalService` (`service.py`) |
| `backend/app/patron/service.py` | PATRON model lifecycle + inference | `PatronInferenceService` (`ensure_loaded`, `reload`, `shutdown`, `infer_payload`, `forecast_from_candles`, `infer_with`, `status`, `info`, `health`, `readiness`), `WARMUP_BARS=384`, `SEQUENCE_LENGTH=96`, `MODEL_ID="patron-1.0.0"` |
| `backend/app/forecasting/` | Forecast contract, provider adapter, run persistence, scheduling | `ForecastRequest`, `ForecastOutput`, `ForecastProvider` Protocol, `validate_forecast_request/output` (`base.py`); `PatronForecastProvider` (`patron_provider.py`); `ForecastService` (`service.py`); `ForecastAutomation` (`automation.py`) |
| `backend/app/chat/service.py` | Deterministic assistant, conversations | `ChatContext`, `ChatResponder` Protocol, `RuleBasedResponder`, `ChatService` |
| `backend/app/kie/` | Embedded LLM engine | `KieService`, `KieCore`, `ModelManager`, `Planner`, `WorkflowController`, `ReasoningEngine`, `ToolRegistry`, `ToolEngine`, contracts/errors/config/repository/responder, `runtime/*` |
| `backend/app/persistence/` | SQLite schema + repositories | `Database` (`db.py`), `SettingsRepository`, `CandleRepository`, `TickRepository`, `SignalRepository`, `ForecastRepository`, `ChatRepository` (`repositories.py`) |
| `backend/app/system/monitor.py` | Host telemetry | `SystemMonitor` (`cpu`, `memory`, `gpu`, `temperature`, `platform_info`, `status`) |
| `backend/app/evaluation/` | **Broken placeholder** (imports missing modules) | `__init__.py` only |
| `backend/app/api/v1/*.py` | Thin routers; all logic in services | see `REPOSITORY_AUDIT.md` §4 |
| `backend/tests/` | 15 test modules + fakes | `conftest.py`, `fake_mt5.py`, `kie_fakes.py` |

Legend for extension work: routers are thin and delegate to `AppContainer` services, so a new
capability = new package + service + router + `AppContainer` field + `build_container` wiring +
`api_router.include_router(...)`. No plugin registry exists.

---

## 3. Composition and dependency injection

`build_container(settings, gateway, binance, binance_history, patron, kie)`:

1. `Database(settings.db_path).initialize()` — creates all tables.
2. Constructs repositories.
3. Constructs two broadcasters: `broadcaster` (active provider stream) and `mt5_broadcaster`
   (isolated MT5 session; never publishes into the active stream).
4. Constructs `MarketDataService(settings, settings_repo, binance, mt5, broadcaster)`.
5. Constructs `PatronInferenceService(settings)`; `SignalService(market, signal_repo, settings)`.
6. Constructs `ForecastService(provider=PatronForecastProvider(patron, binance_history, settings),
   repository=forecast_repo, history=binance_history)`.
7. Constructs `ForecastAutomation`, attaches `forecast.automation_status`, and sets the forecast
   event sink to `broadcaster.publish`.
8. Subscribes `route_binance_event` to the Binance provider: publishes live frames and, for a
   **closed `BTCUSDT` `M15`** candle, calls `forecast_automation.notify_closed(...)`.
9. Constructs `KieService(db=db)` (never loads the model at construction) and
   `ChatService(..., responder=KieResponder(kie) if kie.config.chat_responder else None)`.
10. Returns `AppContainer`.

`create_app` stores the container at `application.state.container`; `get_container` exposes it as
`ContainerDep`. The lifespan order is: bind broadcaster loop → start market polling → background
PATRON load → start forecast automation → `kie.startup()` (guarded, failure only logs) → yield →
`kie.shutdown()` → automation stop → PATRON shutdown → market stop.

**Implication for the upgrade:** a Trading Intelligence service belongs in `build_container`, its
state in `AppContainer`, and its routers in `api_router`. It must never be constructed in a way
that can prevent app startup (follow the KIE precedent: construct, do not require).

---

## 4. Request/data flows

### 4.1 Market → indicators → bias

```text
MarketDataService.run()/refresh     (backend/app/market_data/manager.py)
  → provider.completed_candles()
  → CandleRepository.upsert_*()
  → Broadcaster.publish({type: "candle"|"tick"|"status"})
GET /market/candles    → MarketDataService.candle_series()
GET /indicators        → compute_indicators(candles, params) → IndicatorBundle.to_payload()
GET /signals/current   → IndicatorBundle + close/freshness → evaluate_signal() → SignalResult
                       → SignalService persists a snapshot to signal_snapshots
```

Freshness is decided by `Settings.stale_after_seconds`, provider state, and the last candle time;
it surfaces as `data_state`/`freshness`. The signal engine refuses to emit a directional bias when
data is stale or warm-up is incomplete (`evaluate_signal` early returns `NO_CLEAR_SETUP`/`WAIT`).

### 4.2 PATRON forecast

```text
closed BTCUSDT M15 bar
  → ForecastAutomation.notify_closed()
  → ForecastService.run_forecast(request)
  → PatronForecastProvider.run(request)
       validates symbol=BTCUSDT, timeframe=M15, 1 ≤ horizon ≤ 6
       ensures PATRON loaded (PatronInferenceService.ensure_loaded)
       fetches ≥480 closed Binance 15m candles (BinanceHistoryClient.recent)
       PatronInferenceService.forecast_from_candles(rows)
       derives candle OHLC from q50 + reference close; keeps raw quantiles in metadata
  → ForecastRepository stores forecast_runs + forecast_candles
  → event published to broadcaster
  → ForecastService.evaluate() (manual POST /forecast/evaluate) scores matured steps
       against real candles → forecast_evaluations
```

The forecast payload exposes: `candles[]` (derived OHLC with `sequence`), `patron.range_quantiles[]`
(p10/p50/p90 per step for high/low/close), `reference_close`, `reference_close_time`,
`checkpoint_sha256`, `latency_ms`, `runtime="cpu"`, warnings. `GET /forecast/live` merges the
latest run with the live series for the chart.

### 4.3 Chat

`ChatService.build_context()` assembles `ChatContext` from: active symbol/timeframe, snapshot,
last N candles, indicator latest values, current signal dict, PATRON status, latest forecast and
its evaluated accuracy. `RuleBasedResponder.respond()` is a keyword router (`_overview`,
`_structure`, `_signal`, `_invalidation`, `_volatility`, `_levels`, `_timeframes`, `_forecast`).
`ChatService.send_message()` stores the user message, gets one answer, stores the assistant message
with `context_json`. If `KieResponder` is enabled and the model is ready, it answers from a
rendered context block; on **any** error it falls back to `RuleBasedResponder`.

### 4.4 KIE run

`POST /kie/chat` → `parse_run_request` → prompt budget check → `KieCore.run` → `Planner` (one
`answer` step) → `WorkflowController` → `ReasoningEngine` (system prompt + CONTEXT) →
`ModelManager.generate` (single-flight, cancel callback, wall-clock timeout) → `StreamFilter`
(thinking vs answer) → `KieRepository` persist → SSE events / JSON result. `GET /kie/status`
reports `backend`, `accelerated`, `identity`, `memory`, `fallback_reason`, queue and counters.

---

## 5. Persistence and schema conventions

- SQLite, WAL mode (`PRAGMA journal_mode=WAL`), foreign keys on.
- Schema is a tuple of `CREATE TABLE/INDEX IF NOT EXISTS` statements (`SCHEMA_STATEMENTS`) executed
  in `Database.initialize()`.
- **There is no Alembic and no schema-version table.** Migrations are bespoke, idempotent
  `_ensure_*` methods called after the schema statements:
  `_ensure_forecast_output_column` (`ALTER TABLE forecast_runs ADD COLUMN output_json`),
  `_ensure_evaluation_columns` (adds the candle-level OHLC/error columns to
  `forecast_evaluations`), and `_ensure_candle_source_primary_key` (rebuilds legacy
  `market_candles` so `source` is part of the primary key).
- Consequence for the upgrade: new tables are added to `SCHEMA_STATEMENTS`; any change to an
  existing table must follow the same guarded pattern (check `PRAGMA table_info`, then alter) and
  must be idempotent across restarts.
- Timestamps are ISO-8601 UTC strings; candle times are epoch seconds; forecast target times are
  epoch seconds.
- JSON blobs are stored as TEXT (`warnings_json`, `context_json`, `arguments_json`).
- Repositories expose explicit methods (`list_runs`, `get_run`, `evaluation_summary`,
  `upsert_evaluation`, `recent_runs`, …) and return plain dicts.

---

## 6. API conventions

- Prefix `/api/v1`; routers per domain; Pydantic `response_model` in `backend/app/schemas/models.py`
  for the older domains, plain dicts for newer ones (`kie`, `settings`, `replay`, `diagnostics`).
- Errors are `ApiError` subclasses carrying `code`, `status_code`, `message`, `details`; the app
  exception handler renders `{error: {code, message, details}}`.
- SSE is used for streaming (`/kie/chat/stream`); WebSocket only for the market stream.
- No authentication layer exists (local desktop app). Privileged/new actions must therefore be
  gated by explicit config flags and operator confirmation rather than by user roles.

---

## 7. Frontend architecture

- `main.tsx` → `App.tsx` (`HashRouter`, `ThemeProvider`, `MarketProvider`) → `AppShell`.
- `MarketProvider` owns `settings`, `stream` (snapshot + status + ws state) and save helpers;
  `usePolling(key, fetcher, intervalMs)` is the standard REST refresh pattern; `useLiveCandle`
  merges the WS frame into chart data.
- `lib/api.ts` is the single HTTP surface (`request`/`post`, `ApiError`), typed by `lib/types.ts`.
- Charts: `PriceChart` uses `lightweight-charts` with toggleable EMA/BB/volume/RSI/MACD layers
  driven by persisted `ChartSettings`; `ForecastChart` is a bespoke SVG that renders actual,
  forming and PATRON predicted candles with a hatch pattern, `P1..Pn` labels and a legend.
- Styling: Tailwind 4 tokens (`bg-surface`, `text-ink-muted`, `border-line`, `text-bull`/`text-bear`),
  shared primitives in `components/ui/`; panels use `Panel`/`GroupLabel`/`DataRow`/`Badge`.
- Pages are composed of panels; `MarketIntelligence` is the right-hand context rail,
  `BottomIntelligence` is the compact PATRON/engine status strip.

**Design constraint for later phases:** reuse these primitives and tokens. New surfaces should be
new panels/pages, not a restyle. Any chart overlay must be an independently toggleable layer and
must not alter the existing predicted-candle rendering.

---

## 8. PATRON boundary (frozen)

- Location: `PATRON/` (package `patron`, wheel `patron-1.0.0b1-py3-none-any.whl`), model card
  `PATRON/MODEL_CARD.md` (CNN + BiLSTM + self-attention, 272,618 parameters, 4 heads).
- Integration point: `backend/app/patron/service.py` imports the installed package lazily and owns
  the single model instance; `backend/app/forecasting/patron_provider.py` adapts it to the forecast
  contract.
- Checkpoint path comes from `Settings.patron_checkpoint`; SHA-256 is computed and reported.
- Training code (`PATRON/scripts/train.py`, `train_multiseed.py`, `run_training.*`) and experiment
  folders exist but are **not** part of this upgrade and must not be invoked.

---

## 9. Extension seams (the exact places later phases will touch)

| Seam | File | How to extend |
|---|---|---|
| Composition root | `backend/app/container.py` | add fields to `AppContainer`, construct new services after repositories, pass into `ChatService`/KIE tools |
| App factory/lifespan | `backend/app/main.py` | optional constructor args (default `None`), guarded startup like `container.kie.startup()` |
| Routing | `backend/app/api/v1/router.py` | `api_router.include_router(new.router)` |
| Schema | `backend/app/persistence/db.py` | append additive `CREATE TABLE/INDEX IF NOT EXISTS` statements |
| Repositories | `backend/app/persistence/repositories.py` | new repository classes following dict-returning style |
| Settings | `backend/app/api/v1/settings.py` (`build_settings`, `DEFAULT_*`) and `SettingsRepository` | new settings groups (e.g. `risk`, `assistant`) via the existing key/value store |
| Analysis math | `backend/app/indicators/engine.py` | new pure functions + dataclasses; keep it deterministic and unit-tested |
| Forecast access | `backend/app/forecasting/service.py` (`latest`, `get_run`, `history`, `evaluate`) | read-only adapter should wrap these, not query PATRON directly |
| KIE tools | `backend/app/kie/tools/registry.py` + `backend/app/kie/service.py` | register `ToolSpec` + handler with `Access.READ`, JSON-schema args, bounded output |
| HTTP client | `apps/desktop/src/lib/api.ts`, `lib/types.ts` | add typed endpoints |
| Navigation | `apps/desktop/src/components/layout/Sidebar.tsx` (`GROUPS`) and `App.tsx` routes | add a group/page |
| Charts | `apps/desktop/src/components/market/ForecastChart.tsx`, `PriceChart.tsx` | add optional overlay props; default off |

---

## 10. Testing architecture

- `tests/conftest.py` builds the app with fakes; tests never hit the network or MT5.
- Deterministic fixtures exist for indicators, signals, forecast contracts, persistence, API shapes.
- KIE tests use `tests/kie_fakes.py` and never load the real model (marker separation).
- Tests assert response keys and degraded states, which is the pattern new trading tests should
  follow: frozen fixtures, explicit absence assertions (`NO_TRADE`, `not_calculated`), no time- or
  randomness-dependent expectations.
- Frontend tests run under vitest + jsdom with `src/test/setup.ts`.

---

## 11. Architectural facts that constrain the upgrade

1. **One symbol/timeframe of truth:** PATRON supports BTCUSDT M15 only; forecast automation is
   hard-coded to it. Any strategy engine must treat other symbols/timeframes as unsupported until
   separately implemented and tested.
2. **No account state:** MT5 account balance/equity and instrument contract size are deliberately
   not exposed. Position size cannot be computed without new, explicit inputs.
3. **Inference is a scarce, single-slot resource:** one active KIE generation, queue of 3, 30 s
   wait, 4096 context, ~19 tok/s decode. Multi-step tool loops multiply latency.
4. **CPU PATRON competes for the same cores as the backend and (CPU-fallback) KIE.**
5. **No execution path exists anywhere** — there is no order API to disable; the upgrade must not
   add one.
6. **The repository is not version-controlled**, so phase reports must list every changed file
   explicitly.
