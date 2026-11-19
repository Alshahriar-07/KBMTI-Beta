# 01 — Master Update Plan

## 1. Product goal

Upgrade KBMTI into an **AI Market Analysis & Trading Assistance System**. The system should help a user understand the current market, evaluate a potential setup, plan risk, manage an open trade, and learn from the outcome.

The UI should answer these practical questions:

- What is the current market condition?
- Is there a valid setup now, or should the user wait?
- What evidence supports the setup?
- What price invalidates the idea?
- Where are the planned entry, stop-loss and take-profit levels?
- What is the estimated risk/reward and position risk?
- What should the user monitor after entry?
- If a prior setup failed, what specifically failed and what evidence supports that diagnosis?

It must not promise that the next trade will be profitable.

## 2. Keep two models separate

### PATRON — forecasting only

Keep PATRON's existing responsibility and interface: produce future candle/price forecasts and quantile outputs. Its forecasting objective, training pipeline, and chart role remain unchanged in this project.

### Qwen3-4B — trading intelligence

Use Qwen as a language/reasoning assistant for:
- interpreting structured market context;
- explaining technical concepts and strategy rules;
- comparing eligible strategy candidates;
- producing a structured setup proposal;
- explaining uncertainty and invalidation;
- summarizing trade lifecycle events;
- classifying possible failure causes from verified evidence;
- explaining validated learning/retraining reports.

Qwen does not directly calculate authoritative price levels or risk. It requests calculations from deterministic services and explains their returned values.

## 3. Product experience

The main market screen should combine:
1. Existing candlestick chart.
2. Existing PATRON predicted candles, clearly distinguished from historical candles.
3. Market context panel: trend, structure, momentum, volatility, volume and regime.
4. AI trade assistant panel: `LONG`, `SHORT`, `WAIT` or `NO_TRADE`.
5. Trade plan overlay: entry zone, stop, targets, invalidation and risk/reward.
6. Evidence panel: reasons for, reasons against, confirmation required, data freshness.
7. Trade journal: active, completed, cancelled and expired setups.
8. Outcome review: result in R, fees/slippage, MFE/MAE and failure analysis.
9. Model/strategy health: model version, strategy version, evaluation date and deployment status.

## 4. Core principles

- Evidence before signal.
- No forced trade.
- No fabricated precision.
- Separate forecast direction from trade decision.
- Risk limits are enforced by code, not by prompt.
- Every proposal has a timestamp, expiry, data snapshot and version IDs.
- Backtest, paper-trade and live results are kept separate.
- A failed trade is not automatically a failed model; diagnose with evidence.
- Do not train on future information or leak outcome labels into inputs.
- Retraining candidates must pass independent evaluation before promotion.

## 5. Initial scope

Start with the currently supported BTCUSDT M15 workflow. Design contracts so more symbols/timeframes can be added later, but do not claim they are supported until implemented and tested.

## 6. Explicit non-goals for this upgrade

- Replacing PATRON with Qwen.
- Training Qwen to predict candles.
- Guaranteeing profitable trades.
- Automatically placing real orders.
- Unrestricted shell, exchange-account, or credential access for the LLM.
- Automatically deploying a newly fine-tuned model after a single successful backtest.
- Modifying PATRON's existing model or training logic.
