(assets/logo.png)

# KBMTI — Native Desktop Market Intelligence Workstation

KBMTI is a native Windows desktop application for BTC market intelligence. The React interface runs inside **PySide6 + Qt WebEngine**, backed by a local FastAPI service, live public Binance data, the **PATRON** numerical forecasting model, and an embedded **Qwen3-4B** interpretation layer. Deterministic analysis and risk remain authoritative; Qwen explains and assesses, it never changes PATRON's prices or issues an order.

The official user-facing entry point is:

```text
KBMTI-RAW-TEST.exe
```

It runs the `x.bat` authentication UI, verifies the access key with the KBMTI license service, and only then starts the desktop runtime. `python -m kbmti` redirects to the official EXE and never initializes the application directly.

For licensed development, the authenticated gateway is:

```bash
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER
```

No browser tab, no manual `npm run dev`, no hosted frontend. PATRON is probabilistic source evidence, Qwen is the AI interpretation layer, and Binance is the live market-data provider. There is no trading, order execution or financial advice.

## Desktop architecture

```
KBMTI-RAW-TEST.exe
  └── x.bat authentication + signed-ticket gateway
      └── kbmti runtime (PySide6)
      ├── validates Python/Node/npm/backend dependencies
      ├── chooses free loopback ports
      ├── starts FastAPI backend (uvicorn) in its own process
      ├── starts Vite frontend in its own process
      ├── probes /api/v1/health, the frontend HTML and the Vite API proxy
      ├── opens a native QMainWindow + QWebEngineView (KBMTI)
      └── terminates the full child process tree on close
            |
            ├── React 19 · Vite · TypeScript · Tailwind · lightweight-charts
            └── FastAPI · SQLite · Binance REST/WebSocket
                ├── PATRON (PyTorch CPU; quantile/barrier source evidence)
                ├── deterministic analysis, strategy, risk and trade planning
                └── Qwen3-4B Q4_K_M (embedded llama.cpp, Vulkan/CPU; narration only)
```

Development and production frontend loading are separate:

| Mode | Frontend | Command |
| --- | --- | --- |
| Development (default) | Vite dev server with HMR | `KBMTI-RAW-TEST.exe` |
| Production preview | Existing `apps/desktop/dist` via Vite preview | `KBMTI-RAW-TEST.exe`, then licensed runtime `--mode production` |

The official `KBMTI-RAW-TEST.exe` is built from `launcher/KBMTILauncher.cs` plus the `x.bat` source and an integrity hash. It does not bundle the Python backend; the adjacent `backend/` directory and virtual environment are still required. See [`KBMTI-RAW-TEST.md`](KBMTI-RAW-TEST.md) and [`docs/AUTHENTICATION_AND_LICENSING.md`](docs/AUTHENTICATION_AND_LICENSING.md).

## Requirements

- Windows 10/11 x64
- Python 3.12
- Node.js 20+ and npm
- The same Python environment must contain backend, PATRON and PySide6 dependencies

## Install

```bash
py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -U pip
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt

cd backend
.venv/Scripts/python.exe -m pip install -r requirements-patron.txt
.venv/Scripts/python.exe -m pip install -r requirements-desktop.txt
cd ..

cd apps/desktop
npm ci
cd ../..
```

Optional configuration: copy `.env.example` to `.env`. Existing `.env` files are never overwritten. No Binance API key or secret is used.

## Start

Configure the license service in `.env`, start the license service, then launch:

```text
KBMTI-RAW-TEST.exe
```

The native window opens only after the access key is verified. Startup shows a KBMTI loading surface while the backend, PATRON and frontend become ready. A startup failure shows the real error and log tail, with Retry, Open logs and Quit actions. No browser window is opened.

For licensed development, bypass the EXE only through the authenticated gateway:

```bash
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER --headless
```

Useful runtime options are passed after the gateway:

```bash
... -m kbmti.launch --role DEVELOPER --devtools
... -m kbmti.launch --role DEVELOPER --backend-port 8756
... -m kbmti.launch --role DEVELOPER --mode production
... -m kbmti.launch --role DEVELOPER --headless
```

Direct `python -m kbmti` intentionally redirects to the EXE. Direct `python -m kbmti.runtime` and `python -m app` are refused without a signed launch ticket. The footer shows the actual backend origin chosen for the session.

## Desktop lifecycle

1. Validate Python 3.12, project paths, Node/npm, frontend scripts and backend imports.
2. Resolve free loopback ports (or reject a pinned conflict).
3. Start `python -m app` with `KBMTI_HOST=127.0.0.1` and `KBMTI_PORT=<free>`.
4. Start Vite with the detected port and `--strictPort`; Vite proxies `/api` and `/ws` to the actual backend.
5. Wait for backend health, the frontend document, and the proxied health endpoint. A child exit fails fast with its log tail.
6. Open the Qt window and load the local frontend URL.
7. On close, `taskkill /T /F` terminates the Vite/Node and uvicorn process trees; no orphan listeners remain.

Logs: `.local/desktop-logs/backend.log` and `.local/desktop-logs/frontend.log`.

## Checkpoint and training

The upstream PATRON v1.0.0-beta.1 release ships **no trained weights**. This repository includes a checkpoint trained locally from public Binance data with PATRON's own dataset builder, scaler, trainer and architecture:

- `backend/models/patron/best.pt` — 1.1 MB, SHA-256 `bd809766fdd76fcd325f55f0092cc93b334d2d08ba6fa84c836624b3d89b26ec` (promoted numerical-sanity candidate)
- `backend/models/patron/CHAMPION_V1_ROLLBACK.pt` — previous champion, SHA-256 `52346bf3bb29ffcac9bf06cc57d4afc38ffef06626b0ac4d54903b1475dea327`
- `backend/models/patron/MODEL_PROVENANCE.json` — source data, experiment, training history, evaluation and rollback metadata
- `backend/data/patron/BTCUSDT_15m.parquet` — warm-up bars for inference

This is **not** the unreleased PATRON reference checkpoint. It is a small research model, not a production trading system. The promotion fixed an uninitialised quantile-head bias; it is **not** evidence of a directional edge. The previous champion is retained for rollback.

```bash
backend/.venv/Scripts/python.exe scripts/train_patron_candidate.py \
  --config PATRON/configs/candidate_v2.yaml
```

Measured candidate: 100,930 closed 15m candles, 15 epochs (best epoch 7, patience stop), 12m43s on CPU, best val loss `1.41644`. On 2,517 held-out windows: close MAE `24.13 bp` (champion `86.61 bp`, persistence `23.44 bp`), pinball `0.000851`, interval coverage `86.6%`, directional accuracy `50.35%`. Full comparison, calibration and rollback steps are in [`docs/AI_TRADING_UPGRADE/PATRON_IMPROVEMENT_RESULTS.md`](docs/AI_TRADING_UPGRADE/PATRON_IMPROVEMENT_RESULTS.md).

## Forecast and AI pipeline

```
Binance closed BTCUSDT 15m history (paginated, retries, 5s cache)
  -> validation: count, ordering, duplicates, gaps, price/volume sanity
  -> 384 warm-up bars + 96 input candles
  -> PATRON feature order + train-time robust scaler
  -> PATRON forward pass (quantiles, barrier, momentum, patterns)
  -> SQLite run + raw payload + evaluation
  -> deterministic snapshot: trend, structure, momentum, volatility, regime
  -> PATRON assessment: freshness, schema, conflict, interval diagnostics
  -> Qwen3-4B interpretation (optional; validation + deterministic fallback)
  -> unified GET /api/v1/assistant/market-intelligence
  -> Visual Trading Assistant, AI rail, Overview and BottomIntelligence
```

- Every frontend market-analysis component consumes the unified response; raw PATRON data is rendered only as clearly labelled source evidence.
- Raw PATRON quantiles are preserved unchanged. Qwen may explain reliability, conflicts or uncertainty but cannot modify a price, entry, stop, target, risk result or position size.
- If Qwen is unavailable, invalid or times out, the endpoint returns explicit `UNAVAILABLE`/`INVALID`/`TIMEOUT` status and a deterministic interpretation; it never presents raw PATRON as the final AI decision.
- Qwen runs locally through embedded llama.cpp. No Ollama, cloud API or shell inference.
- PATRON accepts only BTC/USDT spot 15m. The chart provider can be MT5, but PATRON always fetches Binance BTCUSDT 15m itself.
- Failed runs are stored with `status: "error"` and no candles. A run is scored only after its target candles close.

Measured unified path (RX 580 Vulkan): Qwen load 2.343 s, Qwen inference 42.3 s on the final prompt (32.0 s on an earlier, smaller prompt), deterministic response construction 57.2 ms mean / 61.7 ms p95. The endpoint caches the validated result for 45 s and uses a single-flight lock, so components do not trigger separate inferences.

## Desktop interface

- Dark quantitative workstation palette with KBMTI's established blue brand accent.
- Persistent collapsible rail, compact top instrument bar, dominant candlestick workspace, right market-intelligence rail and bottom model/diagnostics strip.
- Live Binance connection state, transport state and PATRON lifecycle are represented from actual backend status, never hardcoded.
- Forecast chart separates realised history, PATRON median and the q10–q90 band.
- Visual Trading Assistant overlays deterministic entry, confirmation, stop and TP lines, risk/reward bands, support/resistance, structure events, PATRON median and conditional scenario paths on the live chart.
- Every chart overlay is toggleable; dashed paths are hypothetical or source evidence, never realised candles.
- Lightweight-charts uses tabular numerals, neutral grid lines and market-only green/red.
- Layout verified at 1920×1080, 1600×900, 1366×768 and 1280×720 through native-window captures.

## API

The launcher picks free ports; the footer shows the active backend origin. When running the backend directly it defaults to `http://127.0.0.1:8756`.

Full docs: [`docs/API_PATRON.md`](docs/API_PATRON.md) and [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md).

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | App, version, stage, PATRON state |
| `GET` | `/api/v1/patron/status` | Model lifecycle, readiness, counters |
| `POST` | `/api/v1/forecast/run` | Fetch Binance, run PATRON, persist |
| `GET` | `/api/v1/forecast/latest` | Latest stored run |
| `GET` | `/api/v1/forecast/history?limit=50` | Runs + evaluation summary |
| `POST` | `/api/v1/forecast/evaluate` | Score matured runs |
| `GET` | `/api/v1/assistant/market-intelligence` | Unified market + PATRON assessment + Qwen interpretation |
| `GET` | `/api/v1/assistant/current` | Trading-intelligence view (tools + optional Qwen) |
| `POST` | `/api/v1/kie/chat` | Local Qwen chat with read-only tools; no orders |
| `POST` | `/api/v1/chat/conversations/{id}/messages` | Deterministic chat grounded in PATRON |

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `KBMTI_DATA_DIR` | `%LOCALAPPDATA%/KBMTI` | SQLite DB and backend logs |
| `KBMTI_HOST` / `KBMTI_PORT` | `127.0.0.1` / `8756` | Overridden by the launcher for each session |
| `KBMTI_DEFAULT_PROVIDER` | `binance` | `binance` or `mt5` chart feed |
| `KBMTI_BINANCE_REST_URL` | `https://data-api.binance.vision` | Public REST base |
| `KBMTI_BINANCE_WS_URL` | `wss://stream.binance.com:9443` | Public WebSocket base |
| `KBMTI_PATRON_CHECKPOINT` | `backend/models/patron/best.pt` | Model weights |
| `KBMTI_PATRON_WARMUP` | `backend/data/patron/BTCUSDT_15m.parquet` | Warm-up history |
| `KBMTI_PATRON_AUTOLOAD` | `true` | Background model load at backend startup |
| `KBMTI_PATRON_THREADS` | `4` | CPU torch threads |
| `KBMTI_KIE_ENABLED` | `true` | Enable the embedded Qwen layer |
| `KBMTI_KIE_AUTOLOAD` | `true` | Warm and inference-verify Qwen in the background at startup |
| `KBMTI_KIE_BACKEND` | `auto` | `auto`/`vulkan` require Vulkan; `cpu` is explicit CPU-only |
| `KBMTI_KIE_CTX` | `4096` | Embedded Qwen context budget |
| `KBMTI_KIE_VRAM_BUDGET_MB` | `4096` | Measured Vulkan buffer budget |

The launcher still uses an existing `.env`; it only overrides host/port/data-dir for the child process.

## Tests and verification

```bash
# Backend + launcher + license enforcement
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check app tests scripts ../kbmti ../license_server

# Licensing / EXE-only checks
cmd /c "x.bat /selftest"
cmd /c "KBMTI-RAW-TEST.exe /selftest"
cmd /c "backend\.venv\Scripts\python.exe -m kbmti /selftest"

# Frontend
cd apps/desktop
npm run typecheck
npm run lint
npm test -- --run
npm run build
```

Latest verification (2026-11-23):

- Backend: **322 passed, 2 deselected** (opt-in real-model/KIE tests), 1 warning.
- Licensing enforcement: **17 passed**; launcher and EXE self-tests pass; licensed User/Developer/Admin headless launches reached `Workspace ready`.
- Ruff: clean across `app`, `tests`, `scripts` and the candidate trainer.
- Frontend: TypeScript clean, ESLint clean, **30 tests passed**, production build built in 0.76 s (651 kB bundle, existing chunk-size warning).
- Visual Trading Assistant chart projection tests assert exact entry/SL/TP prices, risk/reward bands, scenario paths and PATRON median points.
- Real embedded Qwen unified run: `USED`, model identity confirmed, schema valid, 11 known evidence references, all numeric claims verified, 42.3 s inference.
- Real embedded PATRON run after promotion: `READY`, checkpoint SHA verified, sane output, 153 ms inference.
- Real Binance REST/WebSocket and native-window launch checks were last verified on 2026-11-17; the launcher code was not changed by the AI/PATRON work.

## Known limitations

- The promoted checkpoint fixes a large quantile bias (close MAE 86.61 → 24.13 bp) but has **no demonstrated directional edge** (50.35%); it is slightly worse than last-close persistence MAE (23.44 bp). It is not a profitable-forecast claim.
- Quantile intervals are better centred but coverage is 86.6% for nominal 80%, and calibration by regime remains incomplete.
- PATRON supports only BTC/USDT 15m and a 90-minute horizon.
- The embedded Qwen answer took 32–42 s cold in measured runs. The UI polls every 30 s and the backend caches for 45 s; a cold request may show loading.
- The deterministic strategy gate remains **PENDING at 0/60 reviewed cases**. `LONG`/`SHORT` responses are hypothetical geometry, never orders or fills.
- The pre-existing `/api/v1/chat/*` endpoint remains deterministic; Qwen is used by `/api/v1/assistant/*` and `/api/v1/kie/*`.
- MT5 remains an optional secondary chart feed and is not used for PATRON input. The visual assistant reports BTCUSDT M15 only; Forex is not enabled.
- Supply/demand zone widths, breakout/retest prices and multi-timeframe alignment are not computed; the UI labels them unavailable rather than inventing levels.
- An older default local database may lack recent `trade_plans` columns; use a fresh `KBMTI_DATA_DIR` or migrate it. Fresh databases are covered by tests.
- The EXE is built, but it is not Authenticode-signed. Production preview mode still requires an existing frontend build.
- The local backend requires a launcher-issued signed ticket. It is still loopback-only; do not expose it publicly.
- Source distribution means local checks can be patched. The server-side license signature is the security boundary; see [`docs/AUTHENTICATION_AND_LICENSING.md`](docs/AUTHENTICATION_AND_LICENSING.md).

## Repository layout

```
kbmti/                Python desktop launcher, Qt window, process lifecycle
backend/              FastAPI app, SQLite, tests, PATRON checkpoint and warm-up data
apps/desktop/         React interface, Vite config and unit tests
PATRON/               PATRON source/wheel release, configs and training artifacts
docs/                 API, PATRON, MT5, desktop and setup documentation
scripts/              Reproducible PATRON training pipeline
```
