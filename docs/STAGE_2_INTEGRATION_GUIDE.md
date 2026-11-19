# KBMTI — PATRON Integration Guide

This guide describes the implemented model integration. It supersedes the earlier Kronos Stage 2 plan; no Kronos or hosted LLM is used.

## 1. Constraints

1. **Read-only.** No order, position or trade route exists. This is enforced by a test that scans `/openapi.json`.
2. **Real model only.** PATRON 1.0.0 runs from `backend/models/patron/best.pt`. If the checkpoint or warm-up data is missing, the API returns an explicit unavailable/`NO_OUTPUT` state and never substitutes a prediction.
3. **Native contract.** BTC/USDT spot, 15m, exactly 96 closed candles + 384 warm-up bars, 6 quantile steps (90 minutes). No other pair, timeframe or horizon is silently remapped.
4. **Separation from rules.** The `rule-based-technical-v1` signal remains labelled as rule-based and does not consume model output.
5. **Local first.** Binance public REST/WebSocket only; no account, API key or secret is used. Model inference is local CPU.
6. **No secrets in the repo.** Paths and runtime settings come from `.env` / environment (`KBMTI_PATRON_*`).

## 2. Implemented components

| Component | Location |
| --- | --- |
| Model lifecycle + inference | `backend/app/patron/service.py` |
| Patron endpoints | `backend/app/api/v1/patron.py` |
| Forecast provider | `backend/app/forecasting/patron_provider.py` |
| Forecast persistence/evaluation | `backend/app/forecasting/service.py` |
| Binance closed-kline history | `backend/app/market_data/binance_history.py` |
| Forecast/patron endpoints | `backend/app/api/v1/forecast.py` |
| Checkpoint + provenance | `backend/models/patron/` |
| Warm-up history | `backend/data/patron/BTCUSDT_15m.parquet` |
| Reproducible training | `scripts/train_patron.py` |
| UI forecast workspace | `apps/desktop/src/pages/ForecastHistoryPage.tsx` |
| UI forecast chart | `apps/desktop/src/components/market/ForecastChart.tsx` |

## 3. Request flow

```
UI Run forecast
  -> POST /api/v1/forecast/run
  -> ensure PATRON loaded (single-flight)
  -> BinanceHistoryClient.recent("BTCUSDT", "15m", 520)
  -> filter closed candles, validate contiguity
  -> PatronInferenceService.forecast_from_candles(480 rows)
     -> static warm-up slice + 384 preceding bars
     -> 96 x 12 features, robust scaler from checkpoint
     -> PyTorch forward pass
  -> PatronForecastProvider maps quantiles to 6 display candles
  -> ForecastService persists run, candles, raw payload, warnings
  -> UI renders chart, barrier/momentum, history and evaluation
```

`GET /ws/market` also sends a `forecast` summary in its hello payload so the chart/status UI can show model state without another request.

## 4. Failure behavior

| Situation | Behavior |
| --- | --- |
| No checkpoint | State `NOT_CONFIGURED`; run returns `503 PATRON_UNAVAILABLE`; no candles |
| Load error | State `ERROR`, `last_error` exposed in health/status; no crash |
| Too little/gapped Binance history | `PATRON_HISTORY_INSUFFICIENT` / `PATRON_HISTORY_GAP`; no candles |
| Warm-up unavailable | Native `NO_OUTPUT`; forecast provider raises unavailable |
| Failed run | Persisted with `status: "error"` and warning; never fabricated values |
| Future targets | Evaluation reports `awaiting`, not a score |

## 5. Adding another model

Implement `ForecastProvider` in `backend/app/forecasting/base.py`, wire it in `backend/app/container.py`, and keep `/forecast/status` honest about provider, model id, tokenizer and capabilities. Do not reuse the PATRON endpoints for a model with a different contract.
