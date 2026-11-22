# Qwen-centric frontend data pipeline

**Date:** 2026-11-22
**Endpoint:** `GET /api/v1/assistant/market-intelligence`
**Evidence:** [`LIVE_QWEN_FRONTEND_EVIDENCE.json`](LIVE_QWEN_FRONTEND_EVIDENCE.json)
(one real embedded-Qwen run), plus targeted backend/frontend tests listed below.

## 1. Previous architecture

Before this change the frontend treated PATRON as the final market interpretation:

```
Binance/MT5 candles -> /market/candles, /indicators, /signals
                    -> /forecast/latest (raw PATRON payload + derived candles)
                    -> Overview rail / bottom strip / signal distribution
                    -> user reads PATRON's q50, barrier and momentum directly
```

`MarketIntelligence.tsx` and `BottomIntelligence.tsx` received `ForecastRun` and displayed
PATRON's median path, barrier winner and model status without a validated interpretation.
There was no single contract combining market condition, PATRON assessment, deterministic
strategy/risk and Qwen narration.

## 2. New architecture

```
Market data provider
  -> market-data validation (existing AnalysisService provenance/validation)
  -> PATRON forecast adapter (existing ForecastService.latest + raw payload)
  -> deterministic analysis (trend, structure, momentum, volatility, regime)
  -> PATRON assessment (freshness, schema, conflicts, interval width)
  -> Qwen3-4B interpretation (embedded llama.cpp, optional)
  -> AI output validation (action, refs, numbers, prohibited claims)
  -> unified MarketIntelligence response
  -> AiIntelligencePanel / BottomIntelligence / Overview
```

PATRON is still shown, but explicitly as **source evidence**. Qwen is the interpretation
layer; deterministic engines remain authoritative for prices, geometry and risk. The
strategy gate remains **PENDING (0/60)** and execution remains disabled.

## 3. Backend changes

| File | Change |
|---|---|
| `app/intelligence/market_contracts.py` | New `MarketIntelligence`, `ForecastSourceInfo`, `ForecastAssessment`, `MarketCondition`, `UnifiedTradePlan`, `RiskValidationView`, `MarketQwenOutput` |
| `app/intelligence/market.py` | Deterministic forecast extraction/assessment, conflict rules, evidence bullets, risk/plan views |
| `app/intelligence/service.py` | `IntelligenceService.market_intelligence()`, cached Qwen narration, prompt, validation fallback |
| `app/intelligence/validator.py` | Shared claim validator + `parse_market_output` / `validate_market_output` |
| `app/api/v1/assistant.py` | New read-only endpoint |
| `app/container.py` | Passes the forecast service into the intelligence layer |
| `backend/scripts/qwen_pipeline_smoke.py` | Reproducible real embedded-Qwen smoke run |

The response is cached by `snapshot_id | evaluation_id | plan_id | forecast_run_id | use_qwen`
for 45 seconds. A newer market bar or forecast run cannot reuse an older Qwen answer. A lock
prevents concurrent duplicate inference.

## 4. API contract (summary)

| Field | Meaning |
|---|---|
| `market_snapshot` | Last price, ATR/ATR%, EMA9/21/50, RSI, MACD, validation, provenance |
| `market_condition` | Trend/strength/alignment, structure, momentum/phase, volatility/phase, regime, direction, summary |
| `forecast_source` | Immutable PATRON model id/version, checkpoint hash, as-of, reference close, exact `range_quantiles`, stored predicted candles, barrier probabilities, momentum, source hash |
| `forecast_assessment` | `VALID` / `LOW_CONFIDENCE` / `CONFLICTING_EVIDENCE` / `STALE` / `INVALID` / `UNAVAILABLE`, reasons, conflicts, `usable_in_decision`, measured interval/barrier/momentum diagnostics |
| `ai_market_interpretation` | Qwen summary or deterministic fallback |
| `ai_forecast_interpretation` | Qwen's reading of PATRON, constrained by the assessment |
| `bullish_evidence` / `bearish_evidence` | Deterministic evidence, optionally extended by validated Qwen bullets |
| `strategy_candidates` | Deterministic strategy comparison and PENDING gate status |
| `decision` / `decision_reason` | `LONG` / `SHORT` / `WAIT` / `NO_TRADE` from the deterministic planner |
| `trade_plan` | Hypothetical geometry only; no fill, no size |
| `risk_validation` | Risk status, execution eligibility, checks; position size always `NOT_CALCULATED` |
| `invalidation_conditions` | From the deterministic plan |
| `data_freshness` | Market/forecast as-of, ages, stale flags, bar seconds |
| `model_versions` | Market feature, strategy/config, plan, risk policy, PATRON, Qwen |
| `evidence_refs` | Snapshot, evaluation, plan, forecast, knowledge references |
| `warnings` / `unavailable_fields` | Explicit degradation and missing data |
| `ai_status` | `USED` / `UNAVAILABLE` / `INVALID` / `TIMEOUT` / `DISABLED`, model, run id, latency, validation notes |
| `execution` / `position_size` / `disclaimer` | Always `DISABLED`, `null`, and the non-advice boundary |

There is no arbitrary numeric forecast confidence: `forecast_assessment.confidence_score` is
always `null`, and the status is qualitative and rule-based.

## 5. Forecast assessment rules

1. **UNAVAILABLE** — no persisted run or no PATRON payload.
2. **INVALID** — status not `OK`, missing quantiles, non-numeric or unordered q10/q50/q90.
3. **STALE** — forecast is more than two 15m bars behind the latest closed market bar.
4. **CONFLICTING_EVIDENCE** — PATRON median path or momentum opposes deterministic
   direction, or the dominant barrier opposes the deterministic side.
5. **LOW_CONFIDENCE** — interval wider than 8 ATR or narrower than 0.05 ATR, barrier margin
   below 40%, momentum margin below 30%, or PATRON data-quality warnings.
6. **VALID** — schema, freshness and cross-checks pass. It is still probabilistic evidence.

`usable_in_decision` is true only for `VALID`. A `LOW_CONFIDENCE` or conflicting forecast is
still returned as evidence, but explicitly excluded from the decision.

## 6. Qwen input and output example

The prompt contains only authoritative data, capped at 8,500 characters to fit the embedded
3,072-token context. It requires exact JSON keys and forbids new numbers, confidence scores
and execution instructions.

Actual live run (`docs/AI_TRADING_UPGRADE/LIVE_QWEN_FRONTEND_EVIDENCE.json`):

- Model: `Qwen3-4B-Q4_K_M.gguf (Q4_K_M) · llama.cpp b12503`, Vulkan, AMD RX 580.
- Load: **2.343 s**.
- Inference: **42.3 s** (32.0 s on an earlier, slightly smaller prompt).
- Validation: `schema valid`, `11 known evidence references`, `all numeric claims verified`.
- Decision: `NO_TRADE` (deterministic).
- Forecast assessment: `CONFLICTING_EVIDENCE`; PATRON median path bullish, deterministic
  market direction bearish; PATRON momentum `strong_bullish`, deterministic direction
  bearish.
- Qwen market summary: *“Regime TRENDING_DOWN; trend STRONG_BEARISH (STRONG, BEARISH_STACK);
  structure DOWNTREND; momentum BEARISH (ACCELERATING); volatility LOW (STABLE).”*
- Qwen forecast interpretation: *“PATRON's median path is BULLISH while deterministic market
  direction is BEARISH; PATRON momentum is strong_bullish while deterministic direction is
  BEARISH.”*

The exact PATRON quantiles in the response remain unchanged. Qwen's explanation did not
replace any price, action, stop, target or risk result.

## 7. Error handling

| Failure | Response |
|---|---|
| Qwen not configured | `UNAVAILABLE`; deterministic interpretation; market/risk unchanged |
| Qwen disabled | `DISABLED`; deterministic interpretation |
| Model not loaded | `UNAVAILABLE`; explicit error; no fabricated analysis |
| Timeout | `TIMEOUT`; deterministic fallback; warning appended |
| Malformed JSON / schema violation | `INVALID`; deterministic fallback; no partial fields accepted |
| Wrong action | `INVALID`; whole answer rejected |
| Unknown evidence ref | `INVALID`; whole answer rejected |
| Invented number | `INVALID`; whole answer rejected |
| Prompt too large | `UNAVAILABLE` with the real context-budget error; no truncation of authoritative numbers (the prompt payload was compacted and retried successfully) |
| No PATRON run | Forecast `UNAVAILABLE`; deterministic analysis continues; decision still `WAIT`/`NO_TRADE` when appropriate |

The frontend has explicit loading, unavailable, stale and AI-failure states. `AiIntelligencePanel`
shows the AI status/error; `BottomIntelligence` labels the old block “PATRON source evidence”
and renders the unified decision in “AI market view”.

## 8. Performance

Measured on the development machine:

| Stage | Measurement |
|---|---:|
| PATRON CPU inference (480-bar window) | 152.9 ms in the live run; 220 ms in a separate load |
| PATRON checkpoint load | ~2.4 s |
| Deterministic unified response (no Qwen), 30 runs | mean **57.2 ms**, median 57.0 ms, p95 61.7 ms |
| Qwen model load | 2.343 s |
| Qwen inference (unified prompt) | **42.3 s** (32.0 s observed on the earlier prompt) |
| Cold unified API (after PATRON is loaded) | **~42.4 s**, dominated by Qwen |
| Cached unified response | no model call; returns the cached `MarketIntelligence` (45 s TTL) |

The frontend polls the endpoint every 30 s for the active BTCUSDT M15 scope. The backend
cache and single-flight lock prevent one Qwen call per component or per poll. A new market
snapshot or forecast run changes the cache key, so stale Qwen text is never reused.

## 9. Frontend changes

| File | Change |
|---|---|
| `lib/types.ts` | `MarketIntelligence`, forecast assessment/source, market condition, plan/risk views |
| `lib/api.ts` | `api.marketIntelligence(useQwen, refresh)` |
| `pages/Overview.tsx` | One `usePolling` for the unified response, scoped to BTCUSDT M15; passed to rail and bottom strip |
| `components/market/AiIntelligencePanel.tsx` | Shared decision, assessment, AI interpretation, evidence, warnings, unavailable state |
| `components/market/MarketIntelligence.tsx` | Rail renders the unified panel above technicals |
| `components/market/BottomIntelligence.tsx` | PATRON relabelled source evidence; second pane becomes the AI market view; old model status retained in fallback |
| `pages/SignalsPage.tsx` | Removed raw PATRON fetch; BUY/SELL split is now the deterministic rule reading only |
| `AiIntelligencePanel.test.tsx` | Loading, unavailable, conflict/exclusion and AI-failure rendering |

PATRON's forecast chart, forecast-history workspace and `/forecast/*` APIs are preserved for
source-evidence visualization. The bottom strip labels its data "PATRON source evidence" and
the Signals page labels its rule split as deterministic, not PATRON or the AI decision. No
market-analysis or decision component treats the raw PATRON response as the final AI
analysis.

## 10. Test results

- New backend `tests/test_market_intelligence.py`: **10 passed**.
  Covers PATRON context in the prompt, provenance/source hash, exact quantile preservation,
  stale/missing/invalid forecasts, conflicting evidence, valid Qwen narration, invented
  numbers, malformed JSON, timeout, unavailable Qwen, and the unified endpoint.
- Existing `tests/test_assistant_api.py` + `tests/test_intelligence.py`: **8 passed**.
- PATRON/forecast contract tests: **16 passed** after checkpoint promotion.
- Frontend: **30 tests passed**, TypeScript clean, ESLint clean; SignalsPage no longer
  fetches `/forecast/latest`.
- Full backend suite: **282 passed, 1 deselected, 1 warning** in 67.9 s. Ruff clean.
- Production frontend build succeeded (651 kB bundle; existing chunk-size warning).

## 11. Remaining limitations

- Qwen is a 4B quantised model on an RX 580. A cold unified response took 32–42 s in measured
  runs; the UI relies on caching and polling rather than per-component calls.
- The embedded context is 3,072 tokens. The prompt payload is compacted and capped; the
  validator, not the prompt, enforces numerical trust.
- Qwen can still produce schema-invalid output (observed once: `next_action: "WAIT"`); the
  entire answer is rejected and the deterministic fallback is returned. The prompt now asks
  for a full instruction sentence.
- The deterministic strategy gate remains **PENDING at 0/60 reviewed cases**. The unified
  response does not create a validated trade, order, fill or position size.
- PATRON still has no demonstrated directional edge (see
  [`PATRON_IMPROVEMENT_RESULTS.md`](PATRON_IMPROVEMENT_RESULTS.md)); the pipeline correctly
  flags its conflict with the deterministic bearish market rather than hiding it.
- The default local database created by older builds may lack newer `trade_plans` columns;
  fresh databases work. This is a pre-existing persistence migration gap, not a Qwen
  pipeline failure, and it does not fabricate an analysis.
