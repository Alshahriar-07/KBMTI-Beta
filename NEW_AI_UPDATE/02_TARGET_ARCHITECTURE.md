# 02 — Target Architecture

## 1. High-level flow

```text
Market data + indicators + structure
                 |
          Market Context Builder
                 |
       +---------+----------+
       |                    |
    PATRON                Analysis Engines
 Candle Forecast       Structure / Momentum /
       |               Volatility / Regime
       |                    |
       +---------+----------+
                 |
         Strategy Candidate Engine
                 |
       Deterministic Risk & Trade Planner
                 |
       Qwen Trading Intelligence
     (interpret, compare, explain,
      request tools, structured proposal)
                 |
          Result / Policy Validator
                 |
       Trade Assistant UI + Journal
                 |
       Outcome Monitor + Failure Review
                 |
       Dataset Curation + Retraining
                 |
          Offline Evaluation Gate
```

## 2. Component responsibilities

### Market Context Builder
Build a timestamped, immutable snapshot containing OHLCV, indicator values, structure events, volatility, market regime, data source and freshness metadata.

### Analysis Engines
Prefer deterministic calculations for:
- trend and swing structure;
- momentum and momentum change;
- ATR/volatility;
- support/resistance candidates;
- volume features;
- liquidity-sweep candidates;
- multi-timeframe alignment, when data is available.

Each feature must include its calculation/version and validity status.

### PATRON Adapter
Expose the existing forecast output through a read-only adapter. Do not alter PATRON internals. Include forecast horizon, quantiles, model version, generated-at time and staleness.

### Strategy Candidate Engine
Evaluate versioned, explicit strategy rules. Return eligible candidates and rejection reasons. Do not ask the LLM to invent strategy rules during inference.

### Risk & Trade Planner
Calculate entry/stop/targets, position sizing and risk/reward with deterministic code. Enforce configured risk limits. Reject invalid or underspecified setups.

### Qwen Intelligence
Use the embedded Qwen3-4B runtime. It can interpret context, compare candidates, ask approved read-only tools for data, and explain a validated plan. It cannot override hard risk rules.

### Result Validator
Validate schema, referenced evidence IDs, timestamp consistency, price ordering, expiry, risk bounds and allowed action. Reject unsupported claims or invalid numbers.

### Trade Journal and Outcome Monitor
Persist proposals and lifecycle events. Match future market data to setup conditions and calculate outcome metrics.

### Learning Pipeline
Curate labels, train candidate LoRA adapters offline, evaluate on time-separated data, and promote only after all gates pass.

## 3. Trust boundaries

- Market feed is untrusted input until validated.
- LLM output is untrusted until schema and policy validation.
- Strategy rules are versioned code/configuration.
- Risk engine is authoritative for risk calculations.
- Journal is append-only for audit-critical events.
- Training pipeline cannot change production weights directly.
- Production model promotion requires explicit approval and rollback support.

## 4. Suggested package boundaries

Adapt names to the actual repository; inspect existing structure before creating files.

```text
app/
  market_context/
  analysis/
  strategies/
  trade_planning/
  risk/
  intelligence/
  trade_journal/
  outcomes/
  learning/
  evaluation/
  api/
```

Do not create duplicate services if equivalent modules already exist. Extend existing dependency injection and protocols.
