# KBMTI — Windows Setup Guide

This guide sets up KBMTI 1.1.0 on Windows 10/11 x64: the Python backend with PATRON, the React desktop client, and optionally the Tauri native shell.

---

## 1. Prerequisites

| Requirement | Version used | Purpose |
| --- | --- | --- |
| Windows | 10/11 x64 | Desktop target |
| Python | 3.12.10 x64 | Backend runtime |
| Node.js / npm | 24.15.0 / 11.12.1 | Frontend build and Tauri CLI |
| MetaTrader 5 terminal | Optional | Secondary chart feed; the default is public Binance |
| WebView2 Runtime | Current | Tauri webview (normally preinstalled on Windows 11) |
| Rust + Cargo | 1.77.2 or newer | **Only for the Tauri native shell** |
| Visual Studio Build Tools | “Desktop development with C++” + Windows SDK | **Only for the Tauri native shell** |

The web client, PATRON inference and Binance integration run without Rust. The `.exe`/installer requires Rust and MSVC. No Binance API key is needed.

---

## 2. Repository layout

```
AI TREDER/
├─ backend/            FastAPI service, Python venv, tests
├─ apps/desktop/       React/Vite client + src-tauri shell
├─ PATRON/             model source/wheel, configs, training artifacts
├─ docs/               setup, MT5, API and PATRON guides
└─ scripts/            training and icon scripts
```

All paths below assume the repository root, for example:

```
C:\Users\<you>\OneDrive\Documents\AI TREDER
```

---

## 3. Backend setup

Open PowerShell:

```powershell
cd "C:\path\to\AI TREDER\backend"

# Create and activate a virtual environment
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install runtime and development dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-patron.txt
python -m pip install -r requirements-desktop.txt
python -m pip install -r requirements-dev.txt
```

`requirements-patron.txt` installs CPU-only `torch==2.4.1`, PATRON and its feature dependencies. The checkpoint lives at `backend/models/patron/best.pt`; see `README.md` for retraining. Copy `.env.example` to `.env` only if you need to override defaults — existing `.env` files are never overwritten.

Return to the repository root and launch the native desktop app:

```powershell
cd "C:\path\to\AI TREDER"
.\backend\.venv\Scripts\python.exe -m kbmti
```

The launcher starts the backend, PATRON and Vite automatically, waits for real health checks, then opens the KBMTI window. No browser is opened. Use `python -m kbmti --headless` for service diagnostics; `--help` lists ports, DevTools, production preview and screenshot options.

> The backend starts even when MetaTrader 5 is closed; Binance is the default feed. No broker or Binance credentials are requested.

### Backend tests and lint

```powershell
cd "C:\path\to\AI TREDER\backend"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests
```

Expected result: `86 passed`; Ruff: `All checks passed!`.

---

## 4. Desktop launcher and frontend

Install frontend dependencies once:

```powershell
cd "C:\path\to\AI TREDER\apps\desktop"
npm ci
cd ../..
```

The development interface is the native window started by `python -m kbmti`. Vite runs automatically with HMR on a free loopback port; the launcher proxies `/api` and `/ws` to the backend. Do not start a browser tab for normal use.

### Frontend checks

```powershell
cd apps\desktop
npm run typecheck
npm run lint
npm test
npm run build
```

The production bundle is written to `apps/desktop/dist/`. To load that bundle inside the native window:

```powershell
cd ..\..
.\backend\.venv\Scripts\python.exe -m kbmti --mode production
```

See `DEVELOPMENT.md` for lifecycle, logs, ports, screenshots and packaging notes.

---

## 5. MetaTrader 5 setup

1. Install the MT5 terminal from your broker.
2. Launch it and **log in** to the broker account.
3. Leave the terminal running while KBMTI is in use.
4. No API keys, passwords or investor credentials are needed — KBMTI attaches locally through the official `MetaTrader5` Python package.

If the terminal is closed, the backend returns an IPC timeout and remains usable in offline mode. See `docs/MT5_INTEGRATION.md` for symbol discovery, timestamp semantics and troubleshooting.

---

## 6. Packaging status

No EXE or installer is produced in this phase. The native shell is PySide6 + Qt WebEngine and is structured for a future PyInstaller bundle (see `DEVELOPMENT.md`). The legacy `apps/desktop/src-tauri/` directory is not used by the launcher.

---

## 7. Configuration

Backend environment variables (optional):

| Variable | Default | Description |
| --- | --- | --- |
| `KBMTI_HOST` | `127.0.0.1` | Bind address; keep loopback for security |
| `KBMTI_PORT` | `8756` | API port |
| `KBMTI_DATA_DIR` | `%LOCALAPPDATA%\KBMTI` | SQLite database and logs |
| `KBMTI_POLL_INTERVAL` | `1.0` | Seconds between MT5 polls |
| `KBMTI_CANDLE_REFRESH` | `5.0` | Seconds between candle cache refreshes |
| `KBMTI_STALE_SECONDS` | `120.0` | Tick age that marks data stale |
| `KBMTI_DEFAULT_TIMEFRAME` | `M15` | Initial timeframe |
| `KBMTI_DEFAULT_CANDLE_LIMIT` | `500` | Initial candle history |

Frontend environment variables (optional, `apps/desktop/.env.local`):

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE` | empty (same-origin proxy) | Optional REST base override |
| `VITE_BACKEND_ORIGIN` | set by launcher | Vite dev/preview proxy target |

### Data locations

- Database: `%LOCALAPPDATA%\KBMTI\kbmti.db`
- Logs: `%LOCALAPPDATA%\KBMTI\logs\kbmti-backend.log`

Deleting these files resets settings, cached candles, chat and forecast history. No credentials are stored there.

---

## 8. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `Cannot reach the local KBMTI backend` | Use `python -m kbmti`; read `.local/desktop-logs/` and the native error screen. |
| MT5 shows offline with `IPC timeout` | Open and log in to the MetaTrader 5 terminal, then click **Connect MT5**. |
| `MT5_PACKAGE_MISSING` | Activate the backend venv and install `MetaTrader5` from `requirements.txt`. |
| No BTC symbols listed | The terminal is offline, or the broker uses an unusual symbol description. Use the manual symbol field/picker after discovery, or select the exact symbol in MT5’s Market Watch. |
| Charts empty but MT5 connected | History may still be warming up, or the broker has no candles for that instrument/timeframe. Check **Diagnostics → MT5**. |
| Settings PATCH returns 422 | Candle limit must be 60–1500; timeframes must be M1/M5/M15/M30/H1/H4/D1; custom terminal paths must exist. |
| Desktop window is blank | Check `.local/desktop-logs/frontend.log`; install `node_modules` with `npm ci`. |
| WebSocket keeps reconnecting | Backend stopped or proxy target mismatch. The client retries with exponential backoff. |
| Pinned port already in use | Stop the other process or pass different `--backend-port` / `--frontend-port`. |

---

## 9. Security notes

- The backend binds to loopback only by default.
- CORS allows the Vite dev origins and Tauri origins, not arbitrary websites.
- No credentials, cookies or API keys are collected or stored.
- No order execution, position management or trading endpoints exist.
- Read-only market data only; the Tauri CSP allows connections only to `127.0.0.1:8756`.
