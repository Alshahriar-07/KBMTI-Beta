(assets/logo.png)

# KBMTI — Native Desktop Market Intelligence Workstation

KBMTI is a native Windows desktop application for BTC market intelligence. The React interface runs inside **PySide6 + Qt WebEngine**, backed by a local FastAPI service, live public Binance data, and the **PATRON** numerical forecasting model.

The only development command is:

```bash
python -m kbmti
```

No browser tab, no manual `npm run dev`, no hosted frontend. PATRON is the AI intelligence engine; Binance is the live market-data provider. There is no trading, order execution or financial advice.

## Desktop architecture

```
python -m kbmti
  └── kbmti launcher (PySide6)
      ├── validates Python/Node/npm/backend dependencies
      ├── chooses free loopback ports
      ├── starts FastAPI backend (uvicorn) in its own process
      ├── starts Vite frontend in its own process
      ├── probes /api/v1/health, the frontend HTML and the Vite API proxy
      ├── opens a native QMainWindow + QWebEngineView (KBMTI)
      └── terminates the full child process tree on close
            |
            ├── React 19 · Vite · TypeScript · Tailwind · lightweight-charts
            └── FastAPI · SQLite · Binance REST/WebSocket · PATRON (PyTorch CPU)
```

Development and production frontend loading are separate:

| Mode | Frontend | Command |
| --- | --- | --- |
| Development (default) | Vite dev server with HMR | `python -m kbmti` |
| Production preview | Existing `apps/desktop/dist` via Vite preview | `python -m kbmti --mode production` |

A packaged EXE/installer is intentionally not generated in this phase. The launcher keeps paths and process orchestration isolated in `kbmti/` so PyInstaller can bundle it later.

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

From the repository root, with the backend virtual environment active (or by calling its interpreter directly):

```bash
backend/.venv/Scripts/python.exe -m kbmti
```

Windows activation alternative:

```powershell
.\backend\.venv\Scripts\Activate.ps1
python -m kbmti
```

The native window opens automatically. Startup shows a KBMTI loading surface while the backend, PATRON and frontend become ready. A startup failure shows the real error and log tail, with Retry, Open logs and Quit actions. No browser window is opened.

Useful options:

```bash
python -m kbmti --help
python -m kbmti --version
python -m kbmti --devtools                 # F12 Chromium DevTools
python -m kbmti --backend-port 8756        # pin a port; conflicts fail clearly
python -m kbmti --frontend-port 5173
python -m kbmti --mode production          # requires apps/desktop/dist
python -m kbmti --headless                 # start/probe services, then stop
python -m kbmti --screenshot shot.png      # native-window diagnostic capture
```

The footer shows the actual backend origin chosen for the session. `python -m kbmti --headless` is the supported way to verify service orchestration without a display.

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

The upstream PATRON v1.0.0-beta.1 release ships **no trained weights**. This repository includes a checkpoint trained locally from public Binance data with PATRON's own dataset builder, scaler and trainer:

- `backend/models/patron/best.pt` — 1.12 MB, SHA-256 `52346bf3bb29ffcac9bf06cc57d4afc38ffef06626b0ac4d54903b1475dea327`
- `backend/models/patron/MODEL_PROVENANCE.json` — source data, experiment, metrics
- `backend/data/patron/BTCUSDT_15m.parquet` — warm-up bars for inference

This is **not** the unreleased PATRON reference checkpoint. It is a small research model, not a production trading system.

```bash
backend/.venv/Scripts/python.exe scripts/train_patron.py \
  --start 2024-01-01 --epochs 4 --stride 4
```

Verified run: 100,930 closed 15m candles, 47,547 supervised windows (17,523 train / 15,009 validation / 15,015 test), 4 CPU epochs, best val loss `1.4394`, barrier val accuracy `0.325`.

## Forecast pipeline

```
Binance closed BTCUSDT 15m history (paginated, retries, 5s cache)
  -> validation: count, ordering, duplicates, gaps, price/volume sanity
  -> 384 warm-up bars + 96 input candles
  -> PATRON feature order + train-time robust scaler
  -> PATRON forward pass (quantiles, barrier, momentum, patterns)
  -> display candles: close = reference_close * (1 + q50); open = previous close
  -> SQLite run + raw payload + evaluation
  -> Forecasts workspace, Overview strip and WebSocket hello
```

- No random, hardcoded or historical prices are presented as predictions.
- Raw quantiles are preserved; derived OHLC adjustments are reported in `warnings`.
- PATRON accepts only BTC/USDT spot 15m. The chart provider can be MT5, but PATRON always fetches Binance BTCUSDT 15m itself.
- Failed runs are stored with `status: "error"` and no candles.
- A run is scored only after its target candles close; future targets show `awaiting`.

## Desktop interface

- Dark quantitative workstation palette with KBMTI's established blue brand accent.
- Persistent collapsible rail, compact top instrument bar, dominant candlestick workspace, right market-intelligence rail and bottom model/diagnostics strip.
- Live Binance connection state, transport state and PATRON lifecycle are represented from actual backend status, never hardcoded.
- Forecast chart separates realised history, PATRON median and the q10–q90 band.
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
| `POST` | `/api/v1/chat/conversations/{id}/messages` | Deterministic answer grounded in PATRON |

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

The launcher still uses an existing `.env`; it only overrides host/port/data-dir for the child process.

## Tests and verification

```bash
# Backend + launcher: 86 tests
cd backend
.venv/Scripts/python.exe -m pytest
.venv/Scripts/ruff.exe check app tests ../scripts/train_patron.py

# Frontend
cd apps/desktop
npm run typecheck
npm run lint
npm test
npm run build
```

Verified on 2026-11-17:

- `python -m kbmti --version` → `KBMTI 1.2.0`; `--help` lists all launcher options.
- Development headless launch: backend, Vite, frontend document and proxied API all ready; clean shutdown.
- Production preview launch: built frontend and API proxy ready; clean shutdown.
- Native window captured at 1600×900, 1366×768 and 1280×720; no content overflow at the tested desktop sizes.
- Backend 86 tests passed, Ruff clean; frontend TypeScript/ESLint clean, Vitest 6 passed, production build succeeded.
- Real Binance REST/WebSocket connection and PATRON `READY` (272,618 parameters) confirmed during launch.

## Known limitations

- The local checkpoint trained for 4 CPU epochs. Barrier validation accuracy is ~0.325 (chance ~0.333) and momentum is near chance; outputs are uncalibrated research estimates.
- Quantile bands are not calibrated; single-run coverage is not a performance claim.
- PATRON supports only BTC/USDT 15m and a 90-minute horizon.
- Chat is deterministic text grounded in PATRON output, not an LLM and not streaming.
- MT5 remains an optional secondary chart feed and is not used for PATRON input.
- No EXE/installer is produced yet. Production preview mode requires an existing frontend build.
- Backend is loopback-only with no authentication; do not expose it publicly.

## Repository layout

```
kbmti/                Python desktop launcher, Qt window, process lifecycle
backend/              FastAPI app, SQLite, tests, PATRON checkpoint and warm-up data
apps/desktop/         React interface, Vite config and unit tests
PATRON/               PATRON source/wheel release, configs and training artifacts
docs/                 API, PATRON, MT5, desktop and setup documentation
scripts/              Reproducible PATRON training pipeline
```
