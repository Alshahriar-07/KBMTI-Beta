# 07 — Trading UI/UX Specification

## 1. Design goal

Make the next decision understandable at a glance: what the market is doing, whether a setup exists, what must happen next, and what invalidates the idea.

Preserve KBMTI's existing visual language and layout conventions. Do not redesign unrelated screens. Add components incrementally.

## 2. Main chart

Retain historical candles and the existing PATRON predicted-candle visualization. Add clear labels and visual distinction:
- historical market candles;
- PATRON forecast candles and quantile/uncertainty area;
- support/resistance zones;
- market structure markers;
- entry zone;
- stop-loss line;
- TP1/TP2/TP3 lines;
- invalidation marker;
- active-trade progress.

Do not visually merge PATRON predictions with actual candles. Include forecast horizon and generated-at timestamp. Do not display a trade entry solely because forecast candles are bullish/bearish.

## 3. AI Trading Assistant panel

Recommended sections:

### Current market
- Regime: trending / ranging / volatile / uncertain.
- Structure: HH/HL or LH/LL and recent BOS/CHoCH events.
- Momentum: direction, strength and change.
- Volatility: ATR and current volatility state.
- Multi-timeframe alignment, only when supported.

### Decision card
Large state label:
- LONG
- SHORT
- WAIT
- NO TRADE

Show:
- strategy name/version;
- setup quality/rule-completion score (not a profit probability);
- generated time and expiry;
- evidence for;
- evidence against;
- missing confirmation;
- uncertainty/data warnings.

### Trade plan card
- Entry zone/trigger;
- Stop Loss;
- TP1 / TP2 / TP3;
- risk/reward;
- position risk/size only if valid account/instrument inputs exist;
- invalidation condition;
- management rules.

Show “Not available” instead of guessing missing values.

### Next action card
One clear next step, for example:
- Wait for candle close above the trigger.
- Do not enter; confirmation is missing.
- Setup invalidated; discard this plan.
- No trade: volatility/data conditions fail configured rules.

This is guidance, not a guarantee of profit.

## 4. User workflow

1. User opens BTCUSDT M15.
2. UI loads fresh market snapshot and PATRON forecast.
3. Analysis engines calculate market context.
4. Strategy Engine evaluates candidates.
5. Qwen explains the best eligible candidate or explains why no trade exists.
6. Risk Engine validates numeric plan.
7. UI displays a setup only after validation.
8. User chooses whether to act manually.
9. Journal tracks the setup and user-confirmed trade state.
10. Outcome review appears after closure/expiry.

## 5. Chart interactions

- Toggle each overlay independently.
- Click an entry/SL/TP line to inspect source, calculation and strategy rule.
- Hover a setup to see timestamp, expiry and evidence references.
- Keep forecast and trade plan layers independently hideable.
- Avoid clutter: default only the active setup and essential structure markers.
- Use consistent colors/icons with text labels; never rely on color alone.

## 6. History and review UI

Add tabs or sections:
- Active Setups;
- Open Trades (manual/paper status only unless execution is separately approved);
- Completed Trades;
- Failed/Invalidated Setups;
- Strategy Performance;
- Model & Dataset Versions.

## 7. Explainability

Every recommendation should offer:
- Why this action?
- What evidence supports it?
- What evidence conflicts?
- What must happen next?
- What invalidates it?
- Which strategy/model versions were used?

## 8. Data states

Design explicit loading, stale-data, unavailable-model, invalid-forecast, risk-rejected and no-trade states. Never show an old setup as current without a stale badge.
