# Changelog

All notable changes to KBMTI. Dates are local (UTC+08:00 unless noted).

## [1.2.0] — 2026-11-17

### Added

- Native desktop launcher: `python -m kbmti` validates the environment, selects free loopback ports, starts FastAPI/uvicorn and Vite, waits for real HTTP readiness, and opens the existing interface in a PySide6/Qt WebEngine window.
- `kbmti/` package with `--help`, `--version`, `--headless`, `--devtools`, `--screenshot`, `--window-size`, pinned ports, data-dir override and development/production frontend modes.
- Native loading and startup-error screens with retry, log tail and log-folder actions.
- Child process tree shutdown (`taskkill /T /F` on Windows) so closing the window leaves no backend/frontend orphan listeners.
- Vite dev and preview proxy targets receive `VITE_BACKEND_ORIGIN` from the launcher, so random free ports work end to end.
- Dark quantitative workstation theme using the existing KBMTI blue brand hue, neutral surfaces and market-only green/red.
- Live PATRON lifecycle badge and settings access in the top application bar.
- Status footer shows the actual backend origin selected for the session.
- Launcher tests for port selection, occupied ports, npm/Vite commands, environment validation and child termination.
- `DEVELOPMENT.md`, updated `README.md`, `SETUP_WINDOWS.md`, `pyproject.toml`, `.gitignore`, `.env.example`.

### Changed

- Navigation/workspace titles aligned to desktop terminology: Market Analysis, Signal Research, AI Assistant, Forecasting, Model Status.
- Candlestick, volume, EMA, Bollinger, RSI and MACD colors retuned for the dark canvas; removed the chart library watermark.
- Chart volume/technical labels are now provider-neutral instead of MT5-specific.
- Bottom diagnostics strip is compacted on short desktop displays.
- Version bumped to `1.2.0` across backend, frontend and launcher.

### Fixed

- Forecast readiness no longer stays false when the WebSocket hello payload predates PATRON loading.
- Market freshness now reflects the live snapshot rather than a stale secondary status object.
- Native window startup proceeds only after the frontend proxy reaches the backend.

### Limitations

- No EXE/installer is generated yet; production mode requires an existing `apps/desktop/dist`.
- Qt WebEngine screenshots were captured with software rendering for QA; normal launches use the default GPU path.
- The PATRON checkpoint and calibration limitations from 1.1.0 remain.

## [1.1.0] — 2026-11-17

### Added

- Real PATRON 1.0.0 integration: lazy single-flight loader, `DISABLED/NOT_CONFIGURED/LOADING/READY/ERROR` lifecycle, health/readiness/info/status/load/infer endpoints, CPU inference with 272,618 parameters.
- Local PATRON checkpoint trained from public Binance data (`backend/models/patron/best.pt`), SHA-256 provenance and warm-up parquet.
- PATRON-backed forecast provider on the native contract: BTC/USDT spot, 15m, 96 closed candles + 384 warm-up bars → 6 quantile steps / 90 minutes.
- Forecast persistence: runs, display candles, full raw model payload, warnings, latency, evaluation per step.
- `POST /api/v1/forecast/run`, `GET /latest`, `GET /history`, `GET /{run_id}`, `POST /evaluate`.
- Matured-forecast evaluation: MAE, MAPE, direction accuracy, q10–q90 band coverage and `awaiting` accounting.
- Binance history client with pagination, retries/backoff, rate-limit headroom, closed-candle filtering, validation and 5 s cache.
- React Forecasts page with run action, horizon selector, SVG forecast chart with q10–q90 band, barrier/momentum panels, model monitoring, evaluation and run history.
- PATRON status in Overview, model status strip, Chat model panel, Diagnostics panel, health and WebSocket hello payload.
- Trade-off transparency: derived OHLC adjustments are reported as warnings; raw quantiles are never overwritten.
- `scripts/train_patron.py` reproducible download → dataset → train → publish pipeline with provenance.
- Documentation: `README.md`, `docs/API_PATRON.md`, updated `docs/API_CONTRACTS.md`, `.env.example`, `backend/requirements-patron.txt`.
- Backend tests for PATRON loading, inference, validation, forecast contract and API behavior; injectable PATRON/history services for tests.

### Changed

- Stage bumped from 1 to 2; version `1.1.0`; UI labels now say PATRON rather than Stage 1/Kronos.
- Forecast status now reports `provider: patron`, `model_id: patron-1.0.0`, no tokenizer, native contract and checkpoint state.
- Chat answers are grounded in the latest persisted PATRON run and state when no forecast exists; `context.ai_available` now reflects forecast availability, not LLM availability.
- No-trade-route guarantees and loopback-only behavior remain unchanged.

### Fixed

- SQLite migration adds `forecast_runs.output_json` and `forecast_evaluations` without deleting existing data.
- `ForecastService` history method shadowing.
- PATRON warm-up copy self-overwrite error in the training script.
- Chat no longer lets an unavailable live chart feed hide an available stored forecast.

### Limitations

- Shipped checkpoint is locally trained for 4 CPU epochs, not the unreleased PATRON reference checkpoint; barrier/momentum metrics are near chance.
- PATRON supports only BTC/USDT 15m and a 90-minute horizon.
- No point-in-time replay scoring and no trading/execution features.
