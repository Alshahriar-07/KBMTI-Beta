# 06 — Trade Planning, Risk and Management

## 1. Authority

A deterministic Trade Planner and Risk Engine own all numeric calculations. Qwen can request calculations and explain them. It cannot override risk limits or invent levels.

## 2. Trade plan fields

- side: LONG or SHORT;
- entry type: market, limit, stop-entry (only if supported);
- entry zone or exact trigger;
- stop-loss price and rationale;
- take-profit levels TP1/TP2/TP3, if supported;
- invalidation condition;
- expected reward/risk;
- estimated fees and slippage assumptions;
- max account-risk percentage;
- position size and notional, if account inputs are available;
- setup expiry;
- required confirmation;
- plan status.

If account balance, contract specification, fee schedule or lot-size rules are unavailable, do not fabricate position size. Display “not calculated” and explain the missing input.

## 3. Validation rules

For LONG:
- stop must be below the valid entry reference;
- targets must be above the entry reference;
- all levels must be finite and aligned to instrument tick size.

For SHORT:
- stop must be above the valid entry reference;
- targets must be below the entry reference;
- all levels must be finite and aligned to instrument tick size.

Also validate:
- non-zero stop distance;
- risk/reward calculation;
- min/max quantity and lot step;
- max configured risk;
- data freshness;
- plan expiry;
- fees/slippage assumptions;
- no duplicate active setup for the same strategy unless explicitly allowed.

## 4. Position risk

Position sizing must use instrument-specific contract rules. For a simple spot illustration only:

`risk_amount = account_equity * risk_fraction`

`quantity = risk_amount / abs(entry_price - stop_price)`

Production calculations must also account for quote/base currency, contract multiplier, tick/lot size, fees, funding and slippage as applicable. Do not apply the simplified formula blindly to derivatives.

## 5. Trade lifecycle

`PROPOSED -> WAITING_CONFIRMATION -> ACTIVE -> PARTIAL -> CLOSED`

Alternative terminal states:
- CANCELLED;
- EXPIRED;
- INVALIDATED;
- REJECTED.

Every transition must have timestamp, actor/source, reason and evidence reference.

## 6. Management guidance

The system may show rule-based guidance:
- confirmation not reached: wait;
- invalidation reached: plan invalid;
- TP1 reached: show the configured partial/management rule;
- stop reached: mark stopped;
- time expiry reached: review/close according to the configured strategy rule;
- conditions materially changed: request re-evaluation.

Do not tell the user to move a stop farther away to avoid a loss. Breakeven or trailing-stop changes must be predefined, versioned strategy rules and separately tested.

## 7. Risk controls

- Global maximum risk per trade and daily loss threshold are configuration values.
- Default to conservative disabled/observe mode until values are explicitly configured.
- Enforce maximum concurrent exposure and correlated exposure limits where account data exists.
- Stop generating actionable setups when data is stale, feed is unhealthy, or risk service is unavailable.
- No automatic live order placement in this project phase.
