# KBMTI — MetaTrader 5 Integration

KBMTI reads market data from an **already installed, running and logged-in** MetaTrader 5 terminal through the official `MetaTrader5` Python package. It does not log in, store credentials, or send trade requests.

---

## 1. Attachment model

- Transport: local MT5 IPC bridge (`MetaTrader5.initialize`).
- Account: whatever account the terminal is logged into; KBMTI never asks for login, password or server.
- Terminal path: auto-detected from common install locations, or configured explicitly in **Settings → MetaTrader 5** (must exist on disk). The backend also retries attaching without an explicit path if a configured path fails.
- Read-only: only `terminal_info`, `symbol_info`, `symbols_get`, `copy_rates_*` and `symbol_info_tick` are used. No `order_send`, no `positions_*`, no `history_deals_*`.
- The service can start before MT5 is open: health, settings, diagnostics and cached data remain available.

### Connection timing

| Parameter | Value |
| --- | --- |
| IPC handshake timeout | **8 s** (`MT5_INIT_TIMEOUT_MS`) |
| Poll interval | 1 s |
| Candle refresh | 5 s |
| Stale threshold | 120 s without a fresh tick |
| Symbol cache | 300 s |
| Reconnect backoff | `2^attempt` seconds, capped at 30 s |
| Missing package backoff | 60 s |

The 8 s bound was added after a closed terminal blocked initialization for ~70 s during the live test.

### Freshness states

| State | Meaning |
| --- | --- |
| `live` | Connected and the last tick is newer than the stale threshold. |
| `stale` | Connected, but the last tick is older than 120 s (market closed, frozen feed). |
| `unavailable` | Not connected and no cached candles. |
| `cached` | Not connected but previously cached candles exist. |

`data_state` in the snapshot is derived from these plus connection state. `stale_reason` explains the condition.

---

## 2. Symbols and suffixes

Different brokers expose Bitcoin under different names. Discovery is **ranked, not assumed**:

| Match | Score | Reason |
| --- | --- | --- |
| `BTCUSD` | 100 | Exact match |
| `BTCUSDm`, `BTCUSD.`, `BTCUSD_i` | 94 | `BTCUSD` with broker suffix |
| `BTC...USD` | 92 | BTC pair with USD quote |
| `XBT...USD` | 88 | XBT alternative ticker |
| Other name containing `BTC` | 84 | Broker-specific format |
| Other name containing `XBT` | 78 | Alternative ticker |
| Name without BTC/XBT but description/path mentions Bitcoin | 64 | Description match |

Adjustments: `+2` for a crypto group path, `-15` when trading is disabled (`trade_mode == 0`), `+1` when visible. Results are sorted by score then name; the first is marked `recommended`.

`GET /api/v1/mt5/symbols` returns these candidates; the UI requires an explicit choice and persists it. A BTC-like check is also returned for the selected symbol.

If the terminal is offline, the symbol list is empty with an explanatory `error`; the rest of the UI remains usable.

---

## 3. Timeframes

| UI value | MT5 constant | Seconds |
| --- | --- | --- |
| `M1` | `TIMEFRAME_M1` | 60 |
| `M5` | `TIMEFRAME_M5` | 300 |
| `M15` | `TIMEFRAME_M15` | 900 |
| `M30` | `TIMEFRAME_M30` | 1800 |
| `H1` | `TIMEFRAME_H1` | 3600 |
| `H4` | `TIMEFRAME_H4` | 14400 |

Changing the timeframe reloads the cached candle series and refreshes indicators. The default is `M15`.

---

## 4. Market data semantics

### Candles

- Source: `copy_rates_from_pos` (with `copy_rates_from` as a range-based fallback).
- Fields: broker time, open, high, low, close, `tick_volume`, `spread`, `real_volume`.
- Invalid rows (non-finite prices, high/low inconsistencies) are removed and reported in `warnings`.
- The current bar is kept separate as `forming_candle`; completed candles are used for indicators and signals.
- History depth is user-configurable (60–1500 candles; default 500).

### Ticks and quotes

- `symbol_info_tick` supplies bid, ask, last, tick time and tick volume.
- Snapshot exposes bid, ask, spread in points and price, tick lag, daily change against the latest daily bar, and the last completed candle time.
- Spread points = `(ask - bid) / point`, using the broker’s `point` and `digits`.

### Timestamps

- MT5 timestamps are **broker server epoch seconds**.
- KBMTI labels them `time_basis = "broker_server"` and displays them as UTC-formatted broker time with a “broker” hint.
- They are **not** claimed to be verified UTC and are not converted using a guessed offset.
- Server offset is not applied to the underlying epoch values.

### Volume

- `tick_volume` is the broker’s count of price updates for the bar — **not exchange-traded volume**.
- Every chart and API payload labels it as broker tick volume via `tick_volume_note`.

---

## 5. Caching and resilience

- Candles are upserted into SQLite (`market_candles`) and served from cache when MT5 is offline (`data_state = "cached"`).
- Ticks are persisted at a throttled rate into `market_ticks`; retention defaults to 7 days (candles 30 days).
- Connection errors set `last_error`, increment `reconnect_attempts`, and schedule a retry; the UI shows the state.
- A manual **Connect MT5** bypasses backoff; **Disconnect** shuts down the IPC session.
- The WebSocket broadcasts snapshot/status changes; the client reconnects with exponential backoff (1 s → 12 s cap).
- If the feed is stale, indicators still render cached candles but signals return `WAIT` with a stale reason.

---

## 6. Live test on this machine

Performed 12 November 2026 with `MetaTrader5 5.0.6231`:

```
terminal installed:  yes (two paths detected)
terminal running:    no
initialize(timeout=8000) -> False after 8.64 s
last_error:          (-10005, 'IPC timeout')
terminal_info():     None
version():           (0, 0, '')
symbols / candles:   not available
```

Detected paths:

- `C:\Program Files\MetaTrader 5\terminal64.exe`
- `C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe`

The backend's offline behavior was verified end-to-end: health OK, snapshot `connected:false`, `data_state:"unavailable"`, and the IPC timeout surfaced as `stale_reason`; settings and diagnostics remained functional.

**To complete live validation:** launch MetaTrader 5, log in, wait for quotes, start the backend, then:

```powershell
curl.exe -X POST http://127.0.0.1:8756/api/v1/mt5/connect
curl.exe "http://127.0.0.1:8756/api/v1/mt5/symbols?refresh=true"
curl.exe -X POST -H "Content-Type: application/json" -d "{\"symbol\":\"BTCUSDm\"}" http://127.0.0.1:8756/api/v1/market/symbol
curl.exe http://127.0.0.1:8756/api/v1/market/candles
```

Use the exact symbol your broker lists.

---

## 7. Error reference

| Code | API status | Meaning | Action |
| --- | --- | --- | --- |
| `MT5_PACKAGE_MISSING` | 503 | `MetaTrader5` not installed in the backend venv | `pip install -r requirements.txt` |
| `MT5_NOT_CONNECTED` | 503 | Terminal closed, not logged in, or IPC blocked | Open/log in to MT5, then Connect |
| `MT5_DATA_UNAVAILABLE` | 422 | Symbol/rates/ticks unavailable | Check Market Watch, symbol name, timeframe |
| `VALIDATION_ERROR` | 422 | Unknown timeframe/symbol or invalid settings | Use M1–H4 and a broker-listed symbol |
| `PATRON_UNAVAILABLE` | 503 | PATRON model or checkpoint unavailable | Start the backend with the shipped checkpoint, or train one |
| `NOT_FOUND` | 404 | Unknown conversation/forecast run | Refresh the relevant list |

MT5 codes are translated into readable messages, e.g. `-10005` → “The terminal rejected the automated interface request. (code -10005: IPC timeout)”.

---

## 8. Read-only guarantee

- KBMTI contains no order, position or trade-management functions.
- The OpenAPI schema is tested to contain no `order`, `trade`, `position`, `buy` or `sell` paths.
- The Python gateway only exposes read calls.
- No credentials or API tokens are stored in SQLite, logs or the client.

KBMTI is a monitoring and analysis tool, not a trading system.
