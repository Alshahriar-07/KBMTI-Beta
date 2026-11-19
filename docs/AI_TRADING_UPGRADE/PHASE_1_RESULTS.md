# Phase 1 — Market Intelligence Foundation: Results

**Phase:** 1 — Market context and deterministic analysis
**Date:** 2026-11-19
**Scope delivered:** BTCUSDT M15 immutable snapshots, trend, market structure, momentum,
volatility, regime, liquidity context, snapshot persistence, and two additive read-only endpoints.
**Gate status:** **G1 met for the implemented scope** (table in §15). Phase 2 has not started.
**PATRON, chat, KIE and the desktop client are unchanged** (verified with `git diff 00ad7a6..HEAD`).

---

## 1. Implementation summary

Phase 1 adds a deterministic market-intelligence layer that turns closed BTCUSDT M15 candles into
one immutable, auditable `MarketSnapshot`:

- **Contracts** (`app/analysis/contracts.py`): frozen Pydantic v2 models with timezone-aware
  timestamps, explicit enums, per-feature metadata (`version`, `source`, `calculated_at`, `valid`,
  `reason`) and a compact dashboard view.
- **Feature engines**: EMA trend, closed-candle swing structure (HH/HL/LH/LL, BOS, CHoCH,
  support/resistance), RSI/MACD/ROC momentum, ATR volatility, repeated-swing liquidity pools and
  sweep candidates, and a documented regime classifier.
- **Snapshot builder** (`app/analysis/context.py`): strict closed-candle eligibility, OHLCV
  validation, warm-up gating, staleness, deterministic input hash and snapshot id.
- **Service** (`app/analysis/service.py`): Binance history source with a stored-candle fallback,
  five-second cache, persistence, staleness re-evaluation on cache hits, diagnostics.
- **Persistence** (`market_snapshots` table + `MarketSnapshotRepository`): append-only, idempotent
  by deterministic `snapshot_id`.
- **API** (`/api/v1/market/context`, `/api/v1/market/analysis`): thin typed routes through the
  existing `AppContainer` dependency.
- **Integration**: optional service construction exactly like KIE; a construction failure leaves the
  rest of the application running and makes only the analysis routes return `503`.

No strategy, trade plan, risk sizing, Qwen tool, UI, journal or training work was added.

---

## 2. Architecture and data flow

```text
BinanceHistoryClient.recent("BTCUSDT","15m",500)        (live, canonical)
        │  (on failure)
        └── CandleRepository.recent(..., source="binance")   (stored fallback)
                    │
                    ▼
            FallbackCandleSource  ── notes: "live fetch failed; stored candles"
                    │
                    ▼
            AnalysisService (5 s cache, scope check, persistence)
                    │
                    ▼
        MarketContextBuilder.build(...)
          ├─ drop forming/future candles
          ├─ compute as_of = newest close time
          ├─ validate OHLCV / duplicates / ordering
          ├─ gate on 100-bar warm-up
          ├─ compute_indicators(eligible)  ← existing engine
          ├─ trend / structure / momentum / volatility / liquidity
          ├─ regime classification (documented rule order)
          └─ provenance.input_hash + deterministic snapshot_id
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
market_snapshots (SQLite)   GET /api/v1/market/context
                            GET /api/v1/market/analysis
```

The builder never fetches, persists or reads a clock implicitly; those belong to the service / API
layers and are injectable in tests.

---

## 3. Exact files created

```
backend/app/analysis/__init__.py
backend/app/analysis/contracts.py
backend/app/analysis/util.py
backend/app/analysis/trend.py
backend/app/analysis/structure.py
backend/app/analysis/momentum.py
backend/app/analysis/volatility.py
backend/app/analysis/liquidity.py
backend/app/analysis/regime.py
backend/app/analysis/context.py
backend/app/analysis/sources.py
backend/app/analysis/service.py
backend/app/api/v1/analysis.py
backend/tests/analysis_fixtures.py
backend/tests/test_analysis_features.py
backend/tests/test_analysis_service.py
backend/tests/test_analysis_api.py
backend/tests/fixtures/analysis/README.md
backend/tests/fixtures/analysis/{uptrend,downtrend,sideways,high_volatility,low_volatility,
                                  breakout,reversal,insufficient,invalid,future_forming,
                                  liquidity}.json
docs/AI_TRADING_UPGRADE/README.md
docs/AI_TRADING_UPGRADE/PHASE_1_RESULTS.md
```

The fixtures are synthetic and deterministic, marked `"synthetic": true`; they are test inputs, not
market-performance evidence.

## 4. Exact files modified

| File | Change |
|---|---|
| `backend/app/container.py` | imports; `AppContainer.analysis`; optional `analysis` argument to `build_container`; guarded construction with Binance primary + stored fallback and `MarketSnapshotRepository`; logger |
| `backend/app/main.py` | optional `analysis` argument on `create_app`, forwarded to the container |
| `backend/app/api/v1/router.py` | `include_router(analysis.router)` |
| `backend/app/core/errors.py` | additive `UnsupportedScopeError` (422, `UNSUPPORTED_SCOPE`) and `AnalysisUnavailableError` (503, `MARKET_ANALYSIS_UNAVAILABLE`) |
| `backend/app/persistence/db.py` | additive `market_snapshots` table + scope/time index |
| `backend/app/persistence/repositories.py` | additive `MarketSnapshotRepository` (`insert`, `latest`, `get`, `count`) |
| `backend/tests/conftest.py` | forwards an injected `analysis` service to `create_app` |
| `.gitignore` | excludes model weights, runtime data, generated reports, all virtualenvs, `.patron-src`, `assets.zip` and the independent `/PATROR/` backup before the baseline commit |

No file under `PATRON/`, `PATROR/`, `backend/app/patron/`, `backend/app/chat/`, `backend/app/kie/`,
`apps/desktop/` or `backend/app/forecasting/` was modified.

---

## 5. Database changes

Additive only; no existing table or column altered, no Alembic.

```sql
CREATE TABLE IF NOT EXISTS market_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    provider TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    data_as_of TEXT NOT NULL,
    is_stale INTEGER NOT NULL DEFAULT 0,
    feature_version TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_scope
    ON market_snapshots (symbol, timeframe, data_as_of DESC);
```

- `payload_json` stores the complete typed snapshot (features, evidence, validation, provenance).
- Scalar columns exist for scope/time lookup and audit; raw candles are **not** duplicated — the
  snapshot carries `provenance.input_hash`, candle count and first/last closed times, and the candles
  remain in `market_candles`.
- `snapshot_id` is deterministic:
  `sha256(input_hash | feature_version | as_of)[:28]`, prefix `mkt_`; re-insertion is a no-op.
- Verified: insert twice → second returns `False`, row count 1; `latest`/`get` round-trip the payload.

---

## 6. API contracts and examples

Both endpoints are `GET`, read-only, typed with Pydantic response models, and additive under the
existing `/api/v1/market` prefix.

| Endpoint | Response model | Purpose |
|---|---|---|
| `GET /api/v1/market/context` | `MarketContextResponse` | compact validated state for a dashboard |
| `GET /api/v1/market/analysis` | `MarketSnapshot` | full bundle with feature evidence and metadata |
| query `symbol`, `timeframe` | default `BTCUSDT`, `M15` | anything else → `422 UNSUPPORTED_SCOPE` |
| query `refresh` | default `false` | bypass the 5 s cache (used for measurement/debugging) |

Abridged real response from the `uptrend` fixture (values are test data, not live market claims):

```json
{
  "request_id": "d6e1fe3751de46d592ac4354726591cb",
  "snapshot_id": "mkt_cb30fe3bab873ad0961b26ce907a",
  "symbol": "BTCUSDT",
  "timeframe": "M15",
  "provider": "binance",
  "generated_at": "2026-10-21T21:00:30Z",
  "data_as_of": "2026-10-21T21:00:00Z",
  "is_stale": false,
  "feature_version": "market-intelligence-1.0.0",
  "scope": {"symbol": "BTCUSDT", "timeframe": "M15", "supported": true, "reason": null},
  "provenance": {
    "provider": "binance", "source": "fixture", "candle_count": 180,
    "first_candle_time": "2026-10-20T00:00:00Z", "last_closed_candle_time": "2026-10-21T21:00:00Z",
    "fetched_at": "2026-10-21T21:00:30Z", "input_hash": "9f2c…abridged", "timeframe_seconds": 900
  },
  "validation": {
    "status": "OK",
    "checks": ["closed_candles_only", "no_duplicate_timestamps", "monotonic_timestamps",
               "ohlcv_integrity", "minimum_warmup"],
    "errors": []
  },
  "last_price": 61745.06,
  "trend_state": "STRONG_BULLISH",
  "trend_strength": "STRONG",
  "structure_state": "UPTREND",
  "momentum_state": "BEARISH",
  "momentum_phase": "DECELERATING",
  "volatility_state": "NORMAL",
  "volatility_phase": "STABLE",
  "regime_state": "TRENDING_UP",
  "regime_reasons": ["Trend is STRONG_BULLISH and structure is UPTREND."],
  "warnings": []
}
```

`/market/analysis` adds `provenance` (`provider`, `source`, `candle_count`, `first/time`,
`input_hash`, `fetched_at`), `trend`, `structure` (`swings`, `events`, `levels`, `last_bos`,
`last_choch`), `momentum`, `volatility`, `liquidity` (`pools`, `sweeps`, `method_note`) and `regime`
each with `meta.version`, `meta.source`, `meta.calculated_at`.

Unsupported scope example:

```json
{"error": {"code": "UNSUPPORTED_SCOPE",
           "message": "Phase 1 market intelligence supports BTCUSDT M15 only; requested ETHUSDT M15.",
           "details": {"symbol": "ETHUSDT", "timeframe": "M15", "supported": false, "reason": "..."}}}
```

No existing route, payload key or status code was changed. `GET /api/v1/market/context` and
`/analysis` return `503 MARKET_ANALYSIS_UNAVAILABLE` only when the service was not constructed.

---

## 7. Feature calculation methodology

All features are computed from **eligible closed candles only**, on the existing
`app/indicators/engine.py` output (EMA 9/21/50, RSI 14, MACD, Bollinger, ATR 14).

### 7.1 Trend (`trend-1.0.0`)

Four conditions vote +1 bullish / −1 bearish / 0 unknown:

1. EMA 9 > EMA 21,
2. EMA 21 > EMA 50,
3. last close > EMA 21,
4. EMA 21 five-bar slope > +0.01 %/bar (bearish if < −0.01).

Net score: ≥3 `STRONG_BULLISH`, 2 `BULLISH`, ≤−3 `STRONG_BEARISH`, −2 `BEARISH`, otherwise
`NEUTRAL`. Strength = |score|. Consistency is HIGH when all votes agree, MEDIUM when none oppose,
LOW for mixed votes, UNKNOWN when all are zero. Phase compares the current EMA 21 five-bar slope
with the previous five-bar slope (`CONTINUING`, `WEAKENING`, `REVERSAL_RISK`, `UNKNOWN`). No
probability is emitted.

### 7.2 Structure (`structure-1.0.0`)

- Swings: strict local extremum with **2 closed candles on each side**; the last two bars can never
  be swings.
- Labels: consecutive swing highs → `HH`/`LH`; lows → `HL`/`LL`.
- Structural state: last two highs and lows → `UPTREND` (HH+HL), `DOWNTREND` (LH+LL),
  `RANGING` (mixed), `TRANSITION` when a CHoCH contradicts the labelled trend, or
  `INSUFFICIENT_DATA` (<4 swings).
- BOS/CHoCH: only a **closed candle close** beyond the latest unbroken confirmed swing level;
  a wick alone never qualifies. In a labelled uptrend a close above the last swing high is `BOS_UP`,
  a close below the last swing low is `CHOCH_DOWN`; symmetric for downtrends. Events record type,
  event price, broken level, candle timestamp, `confirmed=True` and evidence refs.
- Levels: swing highs/lows from the last 120 bars, clustered within max(0.25 × ATR14, 0.05 % of
  price); up to 8 levels with touch counts and source `swing_high`/`swing_low`.
- Payload truncation: last 16 swings, last 24 events, events limited to the last 80 bars.

### 7.3 Momentum (`momentum-1.0.0`)

Votes from RSI 14 (≥55 / ≤45), MACD histogram sign, MACD line vs signal, and 10-bar ROC. Net ≥2
`BULLISH`, ≤−2 `BEARISH`, mixed signs `MIXED`, otherwise `NEUTRAL`. Phase compares the 10-bar ROC
with its value five bars earlier: change > +0.05 percentage points `ACCELERATING`, < −0.05
`DECELERATING`, otherwise `STEADY`. RSI change and MACD-histogram change are reported.
**Momentum divergence is deferred** — no objective, confirmed pivot-pairing rule was approved in
Phase 1, so none is emitted.

### 7.4 Volatility (`volatility-1.0.0`)

- ATR 14 and ATR as % of last close.
- `atr_percentile` = share of the last 100 ATR values ≤ current ATR.
- State: ≤0.20 `LOW`, <0.80 `NORMAL`, <0.95 `HIGH`, else `EXTREME`.
- Expansion/contraction: current ATR vs the median of the previous 20 ATR values; ≥1.15
  `EXPANDING`, ≤0.85 `CONTRACTING`, else `STABLE`.
- `realized_vol_percent` = population standard deviation of the last 50 fifteen-minute log returns,
  in percent **per bar**, not annualised.

### 7.5 Regime (`regime-1.0.0`)

First match wins, in this exact order:

1. Any core feature insufficient/invalid → `INSUFFICIENT_DATA`.
2. Stale snapshot → `UNCERTAIN`.
3. Bullish/strong-bullish trend **and** uptrend structure → `TRENDING_UP`.
4. Bearish/strong-bearish trend **and** downtrend structure → `TRENDING_DOWN`.
5. Extreme ATR percentile → `HIGH_VOLATILITY`.
6. High ATR percentile (directional evidence did not agree) → `HIGH_VOLATILITY`.
7. Neutral trend with ranging/transition structure → `RANGING`.
8. Otherwise conflicting evidence → `UNCERTAIN`.

### 7.6 Liquidity (`liquidity-1.0.0`)

- Pool = at least two confirmed swings of the same kind within max(0.15 × ATR14, 0.02 % of price),
  and within 3 × ATR14 of the last close; up to 8 pools sorted by distance.
- Sweep = a closed candle whose wick exceeds the pool by ≥0.05 × ATR14 and whose close returns to
  the original side; `CONFIRMED` when the next closed candle closes on that side again, otherwise
  `UNCONFIRMED`.
- The payload states explicitly that these are repeated-swing proxies, **not** order-book,
  institutional or exchange liquidity data.

---

## 8. Temporal integrity guarantees

1. **Eligibility:** `candle.open_time + 900 <= now` for every input candle; the builder drops
   forming/future candles before anything else and adds a warning with the count.
2. **Snapshot time:** `data_as_of` = close time of the newest eligible candle, so every analysed
   candle satisfies `open_time + 900 <= data_as_of`.
3. **No lookahead:** feature modules receive only the eligible list; swings require two *later*
   closed candles for confirmation, so no partially formed bar can become a swing; invalid OHLCV
   stops feature calculation rather than being repaired.
4. **No outcome leakage:** no future candle, return, forecast or trade outcome is an input to any
   market feature.
5. **Freshness:** stale when `now − data_as_of > 900 + stale_after_seconds` (default 1 020 s).
   Stale snapshots still show descriptive facts but validation is `STALE` and the regime is
   `UNCERTAIN`.
6. **Warm-up:** fewer than 100 eligible bars → `INSUFFICIENT_DATA`; all feature states are
   `INSUFFICIENT_DATA` and the API returns 200 with that explicit state (no crash, no fabrication).
7. **Invalid data:** duplicate timestamps, non-increasing order, non-finite/non-positive prices or
   broken OHLC geometry → `INVALID`, errors listed, features unavailable.
8. **Determinism:** `provenance.input_hash` covers provider/scope and every eligible OHLCV value;
   `snapshot_id` derives from that hash, the feature version and `data_as_of`. Two builds over the
   same candles produce the same id, even if extra future candles are appended.
9. **Timezone:** every persisted/generated timestamp is timezone-aware UTC (`AwareDatetime`);
   naive datetimes are rejected by the contracts.

Verified by tests: future/forming exclusion, future-candle-invariance, stale transition (including
a cached snapshot becoming stale without a refetch), insufficient warm-up, invalid OHLCV, duplicate
idempotency, deterministic ids.

---

## 9. Tests executed and actual results

New deterministic tests (frozen synthetic fixtures):

```
PYTHONPATH=. .venv/Scripts/python.exe -m pytest \
  tests/test_analysis_features.py tests/test_analysis_service.py tests/test_analysis_api.py -q
→ 35 tests passed (exit 0)
```

Coverage:

| Area | Tests |
|---|---|
| Contracts / scope / timestamps | supported + unsupported scope, builder rejection, JSON round-trip, naive-datetime rejection |
| Trend | strong up, strong down, sideways neutral, feature metadata |
| Structure | HH/HL + BOS_UP, LH/LL + BOS_DOWN, RANGING, close-confirmed BOS, CHOCH_DOWN, S/R levels |
| Momentum | directional alignment, fields present |
| Volatility | HIGH/EXTREME and LOW percentile states |
| Regime | TRENDING_UP, TRENDING_DOWN, RANGING, HIGH_VOLATILITY |
| Liquidity | equal highs **and** equal lows, confirmed high sweep |
| Degraded data | insufficient warm-up, invalid OHLCV, stale, future/forming exclusion |
| Determinism | same snapshot id, different request ids; future candles cannot change the hash |
| Service | build + persist, cache reuse, refresh bypass, stale cache transition, fallback note, persistence failure non-fatal, unsupported scope, repository idempotency, status |
| API | context, full analysis, 422 unsupported scope, 503 when the service failed to initialise, persistence via HTTP, refresh, nine existing endpoints |

No new test failed on the final run. There are no skipped or xfailed Phase 1 tests. The synthetic
fixtures deliberately produce short-term momentum opposite to the trend in `uptrend` (a pullback),
which is why that example shows `STRONG_BULLISH` trend with `BEARISH` momentum; the test asserts the
state consistency rather than a fabricated agreement.

## 10. Existing regression results

```
PYTHONPATH=. .venv/Scripts/python.exe -m pytest
→ 187 passed, 1 deselected, 1 warning in 41.91 s
```

- Baseline before Phase 1: 152 passed, 1 deselected.
- 152 existing tests still pass unchanged; 35 new tests pass.
- `.venv/Scripts/python.exe -m ruff check app tests scripts` → `All checks passed!`
- The deselected test is the opt-in real-model KIE smoke test (`kie_runtime`), not run in Phase 1.

API compatibility was also asserted directly against `/health`, `/market/snapshot`,
`/market/candles`, `/indicators`, `/signals/current`, `/forecast/status`, `/chat/suggestions`,
`/kie/status` and `/system/status` — all 200 with the analysis service injected.

---

## 11. Performance measurements

**Machine / conditions:** Windows, Intel64 Family 6 Model 158 Stepping 10, 16 GB RAM class,
Python 3.12.10, backend `.venv`; one process; no concurrent training or inference; Binance public
REST reachable. Times are single-run microbenchmarks unless noted, measured with
`time.perf_counter()`.

| Measurement | Method | Result | Target |
|---|---|---|---|
| Live provider fetch (500 closed candles) | `BinanceCandleSource.fetch`, first call | **896.1 ms** | — |
| Build from 500 fetched candles | `MarketContextBuilder.build`, 10 runs, median (max) | **22.1 ms** (27.4 ms) | — |
| Provider-refresh construction | fetch + median build | **918.2 ms** | ≤ 2 000 ms ✅ |
| Cold end-to-end API (`/market/context`) | `TestClient`, real Binance source, includes SQLite insert | **849 ms** | ≤ 2 000 ms ✅ |
| Cached API (`/market/analysis`) | second request within 5 s, TestClient | **3.32 ms** | — |
| Cached service context | 100 calls, 180-bar fixture, median (p95) | **0.019 ms** (0.024 ms) | ≤ 250 ms ✅ |
| Cold fixture context (build + persist) | 180 bars, includes SQLite insert | **19.65 ms** | ≤ 250 ms ✅ |

Interpretation: the 2 s provider target is dominated by the network fetch; the deterministic
calculation itself is ~22 ms for 500 bars. The 250 ms cached target is met with a wide margin
because a cache hit does not rebuild. Network and disk timings vary by machine/connection; no
concurrent-load, multi-symbol or long-duration benchmark was performed.

---

## 12. Known limitations

1. **Scope:** BTCUSDT M15 only. Other symbols/timeframes return `422 UNSUPPORTED_SCOPE`; there is no
   silent substitution.
2. **Provider:** canonical data is Binance public history (the same source as PATRON). The fallback
   serves stored Binance candles from `market_candles` and labels itself `database_cache`; MT5
   `BTCUSDm` is never mixed into this analysis. If neither source works, the endpoint returns
   `503 MARKET_DATA_UNAVAILABLE` rather than an empty snapshot.
3. **Fixtures are synthetic.** Tests prove deterministic behaviour and known-answer geometry, not
   predictive value. The only real-data verification is the live smoke described in §11.
4. **Structure payload is truncated** (16 swings, 24 events, 80-bar event lookback, 120-bar level
   lookback) to bound payload size; older events are not returned.
5. **BOS/CHoCH are conservative:** a range break is not labelled until a structural trend exists, and
   only closes count. This can lag discretionary chart reading.
6. **Transition state is transient:** after a CHoCH, the recomputed swing labels may already describe
   the new trend; `last_choch` preserves the event.
7. **Momentum divergence is deferred** (no approved objective rule).
8. **Volume is not analysed.** Binance trade count is carried as tick volume but no volume feature or
   confirmation rule is implemented.
9. **Liquidity is a swing proxy.** No order-book, depth, funding or institutional data exists; the
   payload says so. Sweep confirmation is one subsequent closed candle, not a validated reversal.
10. **No multi-timeframe analysis** (deferred to a 1b task).
11. **Cached staleness transition** updates `is_stale`, validation and regime, but leaves the
    descriptive feature states (trend/structure/etc.) as calculated; consumers must honour
    `is_stale`/`validation.status` before acting.
12. **`refresh=true` bypasses the cache** and can force a Binance request; there is no per-client
    rate limit beyond the history client's own throttle. The API is local-only and unauthenticated,
    as is the rest of KBMTI.
13. **Persistence has no retention/pruning policy yet**; each closed bar creates at most one row per
    provider/feature version.
14. **Snapshot `request_id`:** persisted payloads contain the build request id; cache hits return a
    copy with the current request id while keeping the same `snapshot_id`. This is intentional but
    worth knowing when correlating logs.
15. **Single-process assumptions:** the service cache is in-memory; multiple backend processes would
    each build their own snapshots (SQLite deduplicates ids).
16. **No auth, no order execution, no account data** — by design.

No requirement was silently marked complete: liquidity is implemented; multi-timeframe and divergence
are explicitly deferred.

---

## 13. Deferred functionality

| Item | Reason / phase |
|---|---|
| Multi-timeframe alignment (M15 + H1) | Phase 1b optional task; requires a second fetch and a measured latency budget |
| Momentum divergence | No objective, confirmed pivot rule approved for Phase 1 |
| Volume features / confirmation | Not specified beyond raw tick volume in Phase 1 |
| Strategy registry (`trend_pullback`) | Phase 2 |
| Trade planning, validation, risk, sizing | Phase 3 |
| Qwen interpretation, tools, RAG | Phase 4 |
| Assistant UI and chart overlays | Phase 5 |
| Journal, monitoring | Phase 6 |
| Outcome/failure analysis | Phase 7 |
| Dataset builder, `app/evaluation` repair, walk-forward/backtest | Phase 8 |
| LoRA feasibility/promotion | Phase 9, separate environment |

---

## 14. Git commits created

| Commit | Content |
|---|---|
| `00ad7a6` | Baseline: existing project source, tests, docs and Phase 0 audit; model weights/runtime data/venvs/backup excluded via `.gitignore` |
| `2dd17b9` | Session checkpoint while Phase 1 code was in progress (message as recorded: `Initial test`) |
| `ddf926c` | Session checkpoint for fixtures/tests in progress (message as recorded: `Test 2`) |
| `19d62b0` | Phase 1 implementation: corrected analysis modules, persistence, API, wiring, 35 tests and fixtures |
| `98baf93` | Contract completion: source `provenance` on the compact context response, with its API assertion |
| documentation commit | This report and `docs/AI_TRADING_UPGRADE/README.md`, created after `98baf93` |

The two checkpoint commits are part of the working history; they captured intermediate states and
are superseded by `19d62b0`. No history was rewritten.

---

## 15. Gate G1 acceptance

Per `IMPLEMENTATION_TASKS.md` Phase 1 and the Phase 1 brief §14:

| Acceptance criterion | Status | Evidence |
|---|---|---|
| Snapshot contracts implemented | **Pass** | `contracts.py`; round-trip/naive-timestamp tests |
| Closed-candle enforcement works | **Pass** | builder eligibility; future/forming tests; snapshot invariance test |
| Trend analysis works | **Pass** | trend tests; uptrend/downtrend/sideways fixtures |
| Structure analysis works | **Pass** | HH/HL, LH/LL, BOS, CHoCH, levels tests |
| Momentum analysis works | **Pass** | directional alignment tests (divergence explicitly deferred) |
| Volatility analysis works | **Pass** | LOW/HIGH/EXTREME percentile tests |
| Regime classification works | **Pass** | four regime tests; documented rule order |
| Liquidity context (optional in brief) | **Pass** | equal highs/lows and confirmed sweep tests |
| Persistence works | **Pass** | insert/idempotency/latest/get tests; API persistence test |
| Both APIs work | **Pass** | context + analysis API tests, live smoke |
| Existing endpoints remain compatible | **Pass** | 152 legacy tests + nine-endpoint API test |
| PATRON remains unchanged | **Pass** | `git diff 00ad7a6..HEAD -- PATRON backend/app/patron` is empty |
| Chat/KIE/frontend remain unchanged | **Pass** | diff empty for those paths |
| Regression tests pass | **Pass** | 187 passed, 1 deselected |
| New tests pass | **Pass** | 35 passed |
| Performance targets measured | **Pass** | §11: 918 ms provider-refresh; 0.019 ms cached |
| Phase report complete | **Pass** | this document |

**Not claimed:** multi-timeframe analysis, divergence, strategy/risk/Qwen/UI work, real-market
accuracy, or any profitability characteristic. Gate G1 is met for the Phase 1 scope only.

---

## 16. Recommendation for Phase 2

Proceed to **Phase 2 — strategy registry and candidate engine** with `trend_pullback` as the single
activated strategy:

1. Freeze strategy version `1.0.0` with explicit, measurable conditions built on the Phase 1
   snapshot fields (trend state/strength, structure state, pullback zone from EMA/levels, closed-bar
   confirmation, invalidation level).
2. Add `strategy_evaluations` persistence, `GET /api/v1/strategies*`, and `WAIT`/`NO_TRADE` with
   rejection reasons.
3. Build the 60-case labelled snapshot benchmark before tuning; predeclare thresholds and report the
   confusion matrix. Do not activate `breakout_retest` until this strategy passes.

Before Phase 2, review two open items: whether the 5 s analysis cache is the right freshness policy
for strategy evaluation, and whether Phase 2 should consume `AnalysisService` directly or a
persisted `snapshot_id` reference (recommended, for reproducibility in later journal/outcome work).
