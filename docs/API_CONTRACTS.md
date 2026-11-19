# KBMTI — API Contracts (v1.2.0)

Forecast/model endpoints are documented in depth in [API_PATRON.md](API_PATRON.md).

Local backend: `http://127.0.0.1:8756` (the native launcher chooses a free port per session; see the app footer)
Base path: `/api/v1` · WebSocket: `/ws/market` · OpenAPI: `/docs` and `/openapi.json`

All responses are JSON. No authentication is required because the service binds to loopback only. There are **no trading endpoints**.

---

## 1. Error envelope

Every handled error returns:

```json
{
  "error": {
    "code": "MT5_NOT_CONNECTED",
    "message": "The terminal rejected the automated interface request. (code -10005: IPC timeout)",
    "details": {}
  }
}
```

| Code | HTTP | Meaning |
| --- | --- | --- |
| `VALIDATION_ERROR` | 422 | Invalid payload, timeframe, symbol or settings |
| `MT5_PACKAGE_MISSING` | 503 | `MetaTrader5` package absent |
| `MT5_NOT_CONNECTED` | 503 | Terminal not reachable |
| `MT5_DATA_UNAVAILABLE` | 422 | Rates/ticks/symbol unavailable |
| `AI_NOT_AVAILABLE` | 501 | AI feature not available in this build |
| `PATRON_UNAVAILABLE` | 503 | PATRON is not loaded or no checkpoint is configured |
| `PATRON_INPUT_INVALID` | 422 | Native PATRON payload violates the 96-candle contract |
| `PATRON_TIMEOUT` | 504 | Inference exceeded the configured timeout |
| `NOT_FOUND` | 404 | Conversation or forecast run does not exist |

Pydantic request-validation failures are normalized into the same envelope with `details.errors`.

---

## 2. Health, root and diagnostics

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | App name, version, stage, docs link, read-only note |
| `GET` | `/api/v1/health` | Status, version, stage, uptime, started_at, database path |
| `GET` | `/api/v1/diagnostics` | App/backend/Python/platform/MT5/database/logs/settings snapshot |
| `GET` | `/api/v1/diagnostics/logs?limit=200` | Log file path and tail |

`diagnostics.database` includes `path`, `size_bytes`, `tables` (row counts) and `integrity` (`"ok"` after an integrity check).

---

## 3. MT5 session

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/mt5/status` | Full session status |
| `POST` | `/api/v1/mt5/connect` | Force attach to the running terminal |
| `POST` | `/api/v1/mt5/disconnect` | Shut down the IPC session |
| `GET` | `/api/v1/mt5/symbols?refresh=false` | Ranked BTC-like broker symbols |
| `GET` | `/api/v1/mt5/symbols/{symbol}` | Broker symbol details + `btc_like` |

`MT5Status` fields: `stage`, `package_available`, `package_version`, `connected`, `terminal`, `terminal_paths`, `selected_symbol`, `symbol_info`, `timeframe`, `last_error`, `reconnect_attempts`, `next_retry_seconds`, `poll_interval_seconds`, `stale_after_seconds`, `freshness`, `freshness_reason`, `time_basis`, `warnings`, `ai_available`, `uptime_seconds`.

`SymbolListResponse`: `connected`, `symbols[]` (with `match_score`, `match_reason`, `recommended`, `btc_like`), `count`, `selected_symbol`, `error`, `note`, `fetched_at`.

---

## 4. Market data

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/market/snapshot` | Quote, spread, daily change, freshness |
| `GET` | `/api/v1/market/candles?limit=500&refresh=false` | Completed candles + forming candle |
| `GET` | `/api/v1/market/timeframes` | `[{value,label,seconds}]` |
| `POST` | `/api/v1/market/symbol` | Body `{ "symbol": "BTCUSDm" }` |
| `POST` | `/api/v1/market/timeframe` | Body `{ "timeframe": "M15" }` |
| `POST` | `/api/v1/market/refresh` | Force poll + candle refresh, returns snapshot |

`limit` is 1–1500. Snapshot fields include `bid`, `ask`, `last`, `spread_points`, `spread_price`, `digits`, `point`, `tick_time`, `tick_time_iso`, `tick_lag_seconds`, `candle_time`, `candle_time_iso`, `tick_volume`, `daily_change`, `daily_change_percent`, `data_state`, `stale_reason`, `last_update`, `time_basis`, `tick_volume_note`, `candle_source`.

`CandleSeriesResponse` adds `count`, `candles[]` (`time,open,high,low,close,tick_volume,spread,real_volume`), `forming_candle`, `source`, `connected`, `data_state`, `time_basis`, `warnings`, `tick_volume_note`, `fetched_at`.

All timestamps are **broker server epoch seconds**; ISO strings are formatted from those values and labelled broker time.

---

## 5. Indicators

`GET /api/v1/indicators?limit=500`

```json
{
  "symbol": "BTCUSDm",
  "timeframe": "M15",
  "candle_count": 500,
  "last_candle_time_iso": "2026-11-12T08:00:00+00:00",
  "series": {
    "ema9": [{"time": 1700000000, "value": 64123.45}],
    "ema21": [], "ema50": [],
    "bbUpper": [], "bbMiddle": [], "bbLower": [],
    "rsi14": [], "macd": [], "macdSignal": [], "macdHistogram": [], "atr14": []
  },
  "latest": {"ema9": 0, "ema21": 0, "ema50": 0, "rsi14": 0, "macd": 0, "macd_signal": 0, "macd_histogram": 0, "bb_upper": 0, "bb_middle": 0, "bb_lower": 0, "atr14": 0},
  "parameters": {"ema_fast": 9, "ema_mid": 21, "ema_slow": 50, "rsi_period": 14, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "bb_period": 20, "bb_std": 2.0, "atr_period": 14},
  "warmup_bars": 50,
  "data_state": "unavailable",
  "warnings": [],
  "time_basis": "broker_server"
}
```

Series keys are camelCase (`bbUpper`, `macdSignal`, `macdHistogram`); `latest` keys are snake_case (`bb_upper`, `macd_signal`, `macd_histogram`). Indicators are computed server-side only.

---

## 6. Technical bias (not AI)

`GET /api/v1/signals/current?refresh=false`
`GET /api/v1/signals/history?limit=50&symbol=BTCUSDm`

`SignalResponse`:

```json
{
  "symbol": "BTCUSDm",
  "timeframe": "M15",
  "label": "BUY BIAS | SELL BIAS | WAIT | NO CLEAR SETUP",
  "direction": "bullish | bearish | neutral | undetermined",
  "score": 0.56,
  "generated_at": "...",
  "data_as_of": "...",
  "freshness": "live | stale | unavailable",
  "supporting": [{"id":"trend_stack","label":"...","detail":"...","weight":0.32,"direction":"bullish"}],
  "conflicting": [],
  "neutral": [],
  "invalidation": ["..."],
  "metrics": {"rsi14": 61.2, "atr14": 31.4, "close": 64200.0},
  "warnings": [],
  "source_candle_count": 220,
  "engine": "rule-based-technical-v1",
  "ai_available": false,
  "ai_note": "PATRON forecasts are reported separately and are not part of this rule score.",
  "disclaimer": "Rule-based technical analysis for monitoring only. It is not AI, not financial advice, and not an order or trade instruction."
}
```

Decision thresholds: `score >= 0.45` → BUY BIAS, `score <= -0.45` → SELL BIAS, `|score| < 0.2` → NO CLEAR SETUP, otherwise WAIT. Two or more conflicting factors downgrade low-conviction biases to WAIT. Fewer than 50 completed candles → NO CLEAR SETUP. Non-fresh data → WAIT.

`GET /signals/history` returns `{ "events": [...], "count": N }`; events are persisted rule-based snapshots.

---

## 7. Forecast contract (PATRON)

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/api/v1/forecast/status` | PATRON state, `ai_available`, checkpoint info, native contract |
| `POST` | `/api/v1/forecast/run` | Fetch closed Binance BTCUSDT 15m candles, run PATRON, persist the run; 503 `PATRON_UNAVAILABLE` if not ready |
| `GET` | `/api/v1/forecast/latest` | Most recent stored run, or `null` before the first run |
| `GET` | `/api/v1/forecast/history?limit=50` | Stored runs, aggregate evaluation and latest run |
| `GET` | `/api/v1/forecast/{run_id}` | One run with full model payload and evaluation |
| `POST` | `/api/v1/forecast/evaluate` | Score matured runs against realised Binance candles |

Model id: `patron-1.0.0`. Tokenizer: none (PATRON is a direct numerical forecaster, not a token LLM). Contract: BTC/USDT spot, 15m, exactly 96 closed input candles + 384 warm-up bars → 6 steps (90 minutes).

Run body (all optional):

```json
{ "symbol": "BTCUSDT", "timeframe": "M15", "horizon": 6 }
```

The provider always fetches its own authoritative BTCUSDT 15m window from Binance. Request `candles` are not reused for PATRON input. Stored output contains derived display candles plus raw `range_quantiles`, `barrier_probabilities`, `momentum`, `patterns`, `data_quality`, `capabilities` and `meta.reference_close`.

Provider protocol (`backend/app/forecasting/base.py`):

```python
class ForecastProvider(Protocol):
    provider_id: str
    model_id: str
    tokenizer_id: str
    def status(self) -> dict[str, Any]: ...
    def run(self, request: ForecastRequest) -> ForecastOutput: ...
```

`ForecastRequest`: `symbol`, `timeframe` (`Timeframe`), `candles` (ascending, unique timestamps), `horizon` 1–6 (API default 6), `context_limit` (default 512).

`ForecastOutput`: `candles`, `provider`, `model_id`, `tokenizer_id`, `latency_ms`, `runtime`, `input_candle_count`, `input_last_bar_at`, `warnings`, `metadata`.

`validate_forecast_request` enforces non-empty sorted unique candles, horizon 1–12, positive context limit. `validate_forecast_output` enforces exact horizon length, strictly increasing continuous timestamps, finite positive prices and OHLC invariants; timestamp gaps become warnings.

---

## 8. Chat (deterministic, not AI)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/chat/suggestions` | Suggested prompts + `context_available` |
| `GET` | `/api/v1/chat/conversations` | Conversation list |
| `POST` | `/api/v1/chat/conversations` | Create; body `{ "title": "..." }` optional |
| `DELETE` | `/api/v1/chat/conversations/{id}` | Delete conversation |
| `GET` | `/api/v1/chat/conversations/{id}/messages` | Messages + context |
| `POST` | `/api/v1/chat/conversations/{id}/messages` | Body `{ "content": "..." }` (1–2000 chars) |
| `DELETE` | `/api/v1/chat/conversations/{id}/messages` | Clear messages |

`POST .../messages` returns `{ user_message, assistant_message, context }`. Messages include `id`, `conversation_id`, `role`, `content`, `context`, `created_at`. The responder is deterministic text, not a language model; when a forecast is stored it is grounded in that PATRON JSON. `context.ai_available` means a PATRON-grounded forecast is available.

---

## 9. System, settings and replay

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/system/status` | CPU, memory, GPU, temperature, backend, MT5, platform |
| `GET` | `/api/v1/settings` | Symbol, timeframe, candle_limit, chart/data/mt5/ui |
| `PATCH` | `/api/v1/settings` | Partial update; returns full settings |
| `GET` | `/api/v1/settings/timeframes` | `["M1","M5","M15","M30","H1","H4","D1"]` |
| `GET` | `/api/v1/replay/window?start=0&count=200` | Slice of cached candles |

Settings constraints: `candle_limit` 60–1500; timeframe must be one of the seven; `mt5.terminal_path` must exist on disk; chart flags are merged with defaults.

System status never fabricates values: unavailable GPU/temperature are returned as `available:false` with a `note`.

Replay returns `symbol`, `timeframe`, `start_index`, `end_index`, `total`, `candles[]`, `source`, `data_state`, `time_basis`, `ai_available` and a pointer to the Forecasts page for scoring. No point-in-time backtest is computed here.

---

## 10. WebSocket `/ws/market`

Events are JSON objects with `type` and `payload`.

**Hello (on connect):**

```json
{
  "type": "hello",
  "payload": {
    "status": { "connected": false, "last_error": "...", "...": "..." },
    "snapshot": { "bid": null, "ask": null, "data_state": "unavailable", "...": "..." },
    "forecast": { "stage": 2, "provider": "patron", "ai_available": true, "...": "..." },
    "server_time": "2026-11-12T08:00:00+00:00"
  }
}
```

**Updates:**

- `{"type":"market","payload": Snapshot}` — broadcast after each poll when the snapshot changes.
- `{"type":"status","payload": MT5Status}` — broadcast when the serialized status changes.
- `{"type":"heartbeat","payload":{"server_time":"..."}}` — every 20 s of inactivity.

The client reconnects automatically with exponential backoff; slow consumers have queued events dropped rather than blocking the poller.

---

## 11. CORS and security

Allowed origins: Vite dev (`localhost`/`127.0.0.1:5173`), preview (4173), and Tauri (`tauri://localhost`, `http://tauri.localhost`, `https://tauri.localhost`). Methods: GET, POST, PATCH, DELETE, OPTIONS.

No authentication is used because the API is loopback-only. Do not bind it to a public interface. No credentials are accepted or stored. No order/trade/position endpoints exist by design and by test.
