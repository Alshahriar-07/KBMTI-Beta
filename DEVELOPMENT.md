# KBMTI Desktop Development

The official desktop entry point is:

```text
KBMTI-RAW-TEST.exe
```

It runs the `x.bat` login UI, verifies the access key with the KBMTI license service, and only then starts the backend, PATRON, and Vite frontend in a PySide6/Qt WebEngine window. `python -m kbmti` redirects to the EXE and never initializes the app.

For licensed development, use the authenticated gateway:

```bash
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER
```

You do not need to run `uvicorn` or `npm run dev` separately.

## 1. Environment

Use the backend virtual environment so the launcher, backend, and PATRON share one interpreter.

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

`requirements-desktop.txt` installs PySide6 6.9.x with Qt WebEngine. No hosted service or browser is required.

## 2. Run

Start the license service, configure `KBMTI_LICENSE_SERVER_URL` in `.env`, then run:

```text
KBMTI-RAW-TEST.exe
```

For a licensed headless development check:

```bash
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER --headless
```

## 3. Launcher files

| File | Responsibility |
| --- | --- |
| `kbmti/__main__.py` | argparse CLI, headless mode, process exit codes |
| `kbmti/config.py` | project paths, free-port detection, npm/Vite commands, environment validation |
| `kbmti/services.py` | managed child processes, log capture, health probes, process-tree shutdown |
| `kbmti/desktop.py` | Qt application, loading/error screens, secure WebEngine profile, shutdown |
| `pyproject.toml` | package metadata, `kbmti` console script, launcher dependencies |
| `backend/requirements-desktop.txt` | PySide6 runtime for the existing backend venv |

## 4. Startup sequence

1. Parse CLI options and resolve free loopback ports.
2. Validate Python 3.12, repository paths, Node/npm, frontend scripts, and backend imports.
3. Start `sys.executable -m app` with `cwd=backend`, `KBMTI_HOST=127.0.0.1`, `KBMTI_PORT=<n>`.
4. Start Vite using the npm CLI entry point (not the `.cmd` shim) with `--strictPort`.
5. Pass `VITE_BACKEND_ORIGIN` to Vite; both dev and preview proxies forward `/api` and `/ws`.
6. Probe `GET /api/v1/health`, `GET /` and `GET /api/v1/health` through the frontend proxy.
7. Load `http://127.0.0.1:<frontend-port>` in the QWebEngineView.
8. On close, kill the full child tree with `taskkill /T /F` on Windows.

There are no fixed startup sleeps. Health checks and child-exit monitoring decide readiness.

## 5. Useful commands

```bash
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER --devtools
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER --backend-port 8756 --frontend-port 5173
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER --headless --timeout 60
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER --screenshot .local/screenshots/app.png --window-size 1366x768
backend/.venv/Scripts/python.exe -m kbmti.launch --role DEVELOPER --mode production
```

`python -m kbmti.runtime` and `python -m app` are internal and refused without a signed launch ticket.

`--headless` is useful in CI or when debugging service startup: it launches the real backend/frontend, probes them, prints the resolved ports and PATRON state, then stops everything. It does not import Qt.

`--screenshot` is a diagnostic mode. It starts the real window, waits for the UI, captures the native window, and exits. It is intended for design QA at `1920x1080`, `1600x900`, `1366x768`, and `1280x720`.

## 6. Ports and Vite

The launcher prefers a free ephemeral port. To pin a port, pass `--backend-port` or `--frontend-port`. If a pinned port is occupied, startup fails with a clear message rather than killing the other process.

The frontend's `vite.config.ts` reads `VITE_BACKEND_ORIGIN`, set by the launcher. This keeps the API proxy correct even with random ports. API calls from React are relative, so they work through the Vite proxy in development and preview.

Hot module replacement remains enabled in development mode because the native window loads the Vite dev server directly.

## 7. Logs and troubleshooting

- Backend log: `.local/desktop-logs/backend.log`
- Frontend log: `.local/desktop-logs/frontend.log`
- Startup failures show the log tail in the native error screen; "Open logs" opens Explorer.

Common issues:

| Symptom | Cause / fix |
| --- | --- |
| `PySide6 is not installed` | Install `backend/requirements-desktop.txt` into the active interpreter. |
| `npm was not found` | Install Node.js 20+ and reopen the terminal. |
| `Frontend dev server exited` | Read the frontend log; usually missing `node_modules` (`npm ci`). |
| Port already in use | Stop the other process or pass different ports. |
| PATRON stays `LOADING` | First CPU load takes ~2–3 s. Check backend log for a checkpoint error. |
| Window is blank | Check the frontend log and the Qt error screen; verify the Vite proxy. |
| `--mode production` fails | Build first: `cd apps/desktop && npm run build`. |

## 8. Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest
.venv/Scripts/ruff.exe check app tests ../scripts/train_patron.py

cd ../apps/desktop
npm run typecheck
npm run lint
npm test
npm run build
```

Launcher-specific tests cover free-port selection, occupied-port failure, npm/Vite command construction, loopback child environment, environment validation, and child termination (`backend/tests/test_desktop_launcher.py`).

## 9. Security model

- Official entry point is `KBMTI-RAW-TEST.exe`; `python -m kbmti` redirects to it.
- Access keys are verified by the separate license service over HTTPS; the client pins an Ed25519 public key.
- Launcher and backend tickets are short-lived, audience-bound, device-bound and one-time; launcher tickets are consumed before startup.
- `KBMTI_ROLE`, fake tokens and direct Python/app startup do not authorize a session.
- Backend and frontend bind to `127.0.0.1` only.
- Qt navigation is restricted to the active local frontend origin.
- JavaScript, local storage and HMR are enabled; plugins, popup windows, remote local-content access and insecure content are disabled.
- No Binance credentials are requested or stored.
- Child process output is written to local log files. No shell command is built from user input.
- Closing the window stops the complete child process tree.

See [`docs/AUTHENTICATION_AND_LICENSING.md`](docs/AUTHENTICATION_AND_LICENSING.md) for the threat model and server setup.

## 10. Packaging

The official launcher is `KBMTI-RAW-TEST.exe`, built from `launcher/KBMTILauncher.cs` and the current `x.bat` integrity hash:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File launcher/build.ps1
```

It does not bundle Python or the frontend; the adjacent `backend/` environment and `apps/desktop` are still required. The EXE is not Authenticode-signed in this repository.
