# PATRON Model & Forecast API (v1.2.0)

Base URL: `http://127.0.0.1:8756/api/v1` when the backend is started directly. The native launcher (`python -m kbmti`) selects free loopback ports; the app footer shows the active origin. OpenAPI: `/docs` · all responses JSON.

PATRON is a numerical forecaster, not a chat LLM. It consumes **BTC/USDT spot, 15-minute** data only. `/api/v1/patron/infer` accepts the native PATRON payload; `/api/v1/forecast/*` is the application layer that fetches Binance history, derives display candles, persists runs and scores matured forecasts.

## 1. Native model contract

| Item | Value |
| --- | --- |
| Model id | `patron-1.0.0` |
| Parameters | 272,618 (CPU) |
| Symbol / timeframe | `BTC/USDT` / `15m` |
| Input | exactly 96 closed candles + 384 warm-up bars (480 total) |
| Features | 12 per candle, PATRON's frozen feature order (`patron.features.schema`) |
| Output | 6 quantile steps (90 minutes): `high`, `low`, `close` at q10/q50/q90 |
| Extra heads | barrier probabilities (`tp_first`, `sl_first`, `timeout`), momentum classes, pattern probabilities |
| Tokenizer | none |
| Chat capability | none |

Checkpoint: `backend/models/patron/best.pt`, provenance in `backend/models/patron/MODEL_PROVENANCE.json`. The checkpoint was trained locally from public Binance data with PATRON's own dataset builder and trainer because the upstream release ships no weights; it is **not** the unreleased reference checkpoint.

## 2. Model lifecycle endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/patron/status` | Runtime state, readiness, checkpoint metadata, counters, last error |
| `GET` | `/patron/info` | Model id, version, contract, capabilities, checkpoint/scaler metadata |
| `GET` | `/patron/health` | PASS/WARN/FAIL checks: checkpoint, config, scaler, warm-up, runtime, inference |
| `GET` | `/patron/readiness` | `{ready, state, checkpoint_exists, message}` — cheap probe for UI |
| `POST` | `/patron/load` | Idempotent explicit load; concurrent callers share one initialization |
| `POST` | `/patron/infer` | Native 96-candle inference (no persistence) |

States: `DISABLED`, `NOT_CONFIGURED`, `LOADING`, `READY`, `ERROR`. Loading is lazy, single-flight and thread-safe; a failure moves the service to `ERROR` with `last_error` and does not crash the API.

### `POST /patron/infer`

```json
{
  "symbol": "BTC/USDT",
  "timeframe": "15m",
  "candles": [
    {
      "timestamp": "2026-11-16T00:00:00+00:00",
      "open": 64000.0,
      "high": 64210.5,
      "low": 63880.0,
      "close": 64150.2,
      "volume": 123.45
    }
  ]
}
```

Exactly 96 candles, oldest → newest, 15 minutes apart, no gaps or duplicates, positive prices, `high >= max(open, close, low)`, `low <= min(open, close, high)`. `symbol` must be `BTC/USDT` and `timeframe` `15m`. Warm-up bars come from the configured local parquet; without contiguous warm-up the model returns `NO_OUTPUT` instead of a cold-started prediction.

Response: PATRON's native JSON (`status`, `as_of`, `range_quantiles`, `barrier_probabilities`, `momentum`, `patterns`, `data_quality`, `capabilities`, `runtime`). Invalid payloads → `422 PATRON_INPUT_INVALID`; not loaded / missing checkpoint → `503 PATRON_UNAVAILABLE`; timeout → `504 PATRON_TIMEOUT`.

## 3. Forecast pipeline

```
Binance REST (closed BTCUSDT 15m, paginated + retries)
  -> freshness/contiguity validation
  -> 384 warm-up bars + 96 input candles
  -> PATRON feature builder + train-time robust scaler
  -> 272,618-parameter PyTorch model (CPU)
  -> quantiles / barrier / momentum / patterns
  -> display candles (close = reference_close * (1 + q50))
  -> SQLite run + raw payload + evaluation
  -> React Forecasts page and market WebSocket hello payload
```

Display derivation is explicit: step 1 open = reference close; later opens = previous predicted close; high/low = q50 high/low bounded by the open/close envelope. Adjustments are reported in `warnings`; raw quantiles remain untouched in `output.patron`.

### Forecast endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/forecast/status` | Provider state, `ai_available`, checkpoint info, contract |
| `POST` | `/forecast/run` | Body `{symbol?, timeframe?, horizon?}` (horizon 1–6). Fetches closed Binance history itself, runs PATRON, persists the run |
| `GET` | `/forecast/latest` | Latest stored run, or `null` before the first run |
| `GET` | `/forecast/history?limit=50` | Runs + aggregate evaluation + latest run |
| `GET` | `/forecast/{run_id}` | Full run: candles, raw output, evaluation |
| `POST` | `/forecast/evaluate?limit=50` | Score matured runs against realised Binance candles |

`POST /forecast/run` returns the stored run: `id`, `provider`, `model_id`, `symbol`, `timeframe`, `created_at`, `input_last_bar_at`, `input_candle_count`, `horizon`, `latency_ms`, `runtime`, `status`, `warnings`, `candles[]` (`sequence`, `timestamp_utc`, OHLC, `direction`), `output.patron`, `output.meta`, `evaluation`.

Failed attempts are persisted with `status: "error"` and a warning; no predicted candles are invented. A successful run has `status: "ok"`.

### Evaluation

For each stored candle whose target open time has a realised Binance candle, the evaluator stores step-level `actual_close`, `predicted_close`, `abs_error`, `pct_error`, `direction_correct` and `in_band` (q10–q90 close). Aggregate summary: `runs_evaluated`, `steps_evaluated`, `close_mae`, `close_mape`, `direction_accuracy`, `band_coverage`. Runs whose targets are still in the future are reported as `awaiting`, not scored.

## 4. Status codes

| HTTP | Code | Meaning |
| --- | --- | --- |
| 422 | `VALIDATION_ERROR` | Bad forecast request (symbol/timeframe/horizon) |
| 422 | `PATRON_INPUT_INVALID` | Native input violates the 96-candle schema |
| 503 | `PATRON_UNAVAILABLE` | Model not loaded, checkpoint missing, or too little Binance history |
| 504 | `PATRON_TIMEOUT` | Inference exceeded the timeout |
| 404 | `NOT_FOUND` | Unknown forecast run or conversation |

## 5. Training / reproducing the checkpoint

```bash
backend/.venv/Scripts/python.exe scripts/train_patron.py \
  --start 2024-01-01 --epochs 4 --stride 4
```

The script downloads public BTCUSDT 15m klines, builds PATRON's clean parquet and supervised dataset, runs PATRON's trainer, copies `best.pt` into `backend/models/patron/`, writes warm-up history to `backend/data/patron/` and records SHA-256 provenance.

Verified local run: 100,930 downloaded candles from 2024-01-01, 47,547 supervised windows (17,523 train / 15,009 validation / 15,015 test), 4 CPU epochs (~3 minutes total), best val loss `1.4394`, barrier val accuracy `0.325`, checkpoint SHA-256 `52346bf3bb29ffcac9bf06cc57d4afc38ffef06626b0ac4d54903b1475dea327`.
