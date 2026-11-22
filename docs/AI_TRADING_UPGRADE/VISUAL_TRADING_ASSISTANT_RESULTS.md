# Visual Trading Assistant — implementation results

## Scope

The existing **Assistant** route is now the visual trading-assistant workspace. It is not a
separate demo and it does not create a new market-data or model path.

Verified scope: **BTCUSDT · M15**, using the existing Binance provider and the unified
`/api/v1/assistant/market-intelligence` response. Other symbols/timeframes show an explicit
out-of-scope state. Forex is not enabled: there is no verified FX provider, pip contract,
spread model, or instrument-specific test suite yet. Crypto price arithmetic is not reused for
FX.

Execution remains **DISABLED**, position size remains **NOT_CALCULATED**, and the Phase 2
strategy gate remains **PENDING at 0/60 reviewed**.

## UI changes

### Chart-first layout

- Main column: interactive `lightweight-charts` candlestick chart, overlay toolbar, annotation
  selection strip, possible-next-movement scenarios, trade management, scope notice.
- Right column: AI market view, current condition, trade recommendation, supporting/conflicting
  evidence, PATRON assessment, data/model health.
- Responsive single-column stacking below the `xl` breakpoint. The chart keeps a usable
  minimum height instead of collapsing into a text card.
- Existing chart interactions are preserved: zoom, pan, crosshair, fit, EMA/Bollinger/RSI/MACD/
  volume layers, theme colors, and broker/source footer semantics.

### Chart layers and controls

The overlay toolbar toggles:

- Trade levels (entry zone, entry, confirmation boundary, stop, TP1/TP2/TP3)
- Support/resistance and liquidity levels
- Market structure markers (HH, HL, LH, LL, BOS, CHoCH, liquidity sweeps)
- PATRON median path
- Conditional scenario paths
- Risk/reward shading

All overlays are **off by default where they could be mistaken for realised data** (scenario
paths). PATRON is always dashed and labelled as source evidence. The legend distinguishes actual
candles, entry/risk/reward zones, PATRON median, and conditional scenarios.

### Entry, stop and targets

The planning engine remains the sole source of numeric trade geometry:

- Entry zone: `trade_plan.entry_zone.lower..upper`
- Suggested entry: `trade_plan.suggested_entry`
- Confirmation boundary: upper edge for LONG / lower edge for SHORT
- Stop: `trade_plan.stop_loss`; stop basis is shown verbatim
- Targets: all three `take_profits` with method and R multiple
- R:R: all three deterministic ratios
- Setup expiration: `trade_plan.expires_at`
- Distances: computed from the suggested entry and displayed as absolute price and percentage

The chart uses these values directly. No hardcoded example prices exist in production.

### Risk and reward regions

A canvas primitive attached to the candle series draws full-width translucent bands using the
series' own price scale. Bands are recalculated from the current viewport during zoom, pan and
resize, so they stay aligned with prices.

- Entry zone: blue
- Entry-to-stop risk: red
- Entry-to-final-target reward: green
- Dashed boundaries and small labels keep the bands readable without covering candles

### Market structure

The snapshot's already-computed `structure.levels`, `structure.events`, and liquidity pools are
rendered as:

- Horizontal support/resistance/liquidity lines with touch count and last-test detail
- Swing/event markers labelled HH, HL, LH, LL, BOS_UP/DOWN, CHoCH_UP/DOWN, and sweep events
- A selectable annotation list that explains each level or marker's calculation source

Levels are filtered to the current price side (support below, resistance above) and marker times
to the visible candle range. No level, swing, or sweep is synthesized in the frontend.

### PATRON visualisation

The stored `forecast_source.predicted_candles` are rendered as a second, translucent ghost
candlestick series with no price line or last-value badge. `forecast_source.range_quantiles[*].close.q50`
is also projected from the stored reference close and `input_last_bar_at` into a dashed median
path. Neither is drawn when the deterministic assessment is `STALE`, `INVALID`, or
`UNAVAILABLE`. Predicted candles are never merged into the realised candle series.

The right panel shows the assessment status, reasons, freshness, source model, source as-of
time, and whether the forecast was usable in the decision. Qwen's explanation is labelled as
interpretation and cannot change the path or the deterministic decision.

### Conditional scenarios

Five scenarios are generated deterministically in
`backend/app/intelligence/visualization.py`:

1. Bullish continuation
2. Bearish reversal
3. Bearish continuation
4. Bullish reversal
5. Sideways consolidation

Every scenario carries:

- Starting condition
- Verified trigger, target and invalidation (or an explicit unavailable reason)
- Confirmation trigger text
- Invalidation text
- Supporting and opposing evidence
- Optional chart path expressed as **bar offsets**, not timestamps or invented candles

A path is emitted only when the required verified level exists. If a support, resistance, or
both range boundaries are missing, the scenario is marked unavailable and no line is drawn. The
card explains why. Sideways consolidation displays the verified range and deliberately has no
directional path.

Scenario paths are dashed and hypothetical. Clicking a card focuses that scenario on the chart;
“show all scenarios” resets the focus. This gives separate LONG/SHORT/range inspection without
clutter.

### Trade management

The panel explains what to monitor before entry, at TP1/TP2/TP3, and at the invalidation
boundary. It is educational and condition-based. It never automatically moves a stop or target.
Any modification requires a new deterministic plan and risk validation.

## Data flow

```
Binance closed candles
        │
        ▼
Market snapshot + deterministic structure/levels
        │
        ├── Strategy evaluation ──► Trade planning + risk validation
        │                                  │
        ▼                                  ▼
PATRON source evidence ──────────► Unified market-intelligence response
        │                                  │
        └──────────────► Qwen narration ───┤ schema/evidence/number validation
                                           ▼
                                  Visual Trading Assistant
```

- `MarketIntelligence.chart_overlay` carries verified levels, structure markers and scenarios.
- `MarketIntelligence.trade_plan` carries every displayed numeric level.
- `MarketIntelligence.forecast_source` carries PATRON's immutable source evidence.
- Qwen contributes only `ai_market_interpretation`, `ai_forecast_interpretation`, and evidence
  prose after validation.
- The frontend `buildTradeChartOverlay` is a pure projection of those fields plus candles; it
  invents no prices.

## Scenario generation rules

- Support/resistance come from closed-candle swing clusters; liquidity pools are repeated swing
  levels, not order-book depth.
- Bullish continuation requires resistance above price.
- Bearish continuation and bullish reversal require support below price.
- Bearish reversal requires resistance above price.
- Sideways requires both a verified support and resistance.
- A plan's TP3 may be used as a scenario target only when its direction matches the scenario;
  otherwise the next verified structural level is used.
- Missing required levels produce `available=false` with a specific reason.
- No exact future price is claimed. The levels are conditional reference boundaries.

## Tests and results

Focused backend tests:

```
12 passed
```

Full backend suite: **282 passed, 1 deselected, 1 warning**. They cover source preservation,
stale/invalid/conflicting forecasts, Qwen acceptance and failure fallback, endpoint serialization,
missing-level scenarios, and the new chart overlay:
all five scenarios, verified levels, marker times, unavailable paths, confirmation boundary,
stop basis, and expiration.

Frontend:

```
30 tests passed
TypeScript clean
ESLint clean
Production build succeeded
```

New pure projection tests assert:

- Entry, confirmation, stop and TP3 lines exactly match deterministic plan values
- Risk band is stop-to-entry and reward band is entry-to-final-target
- Disabling trade/structure layers removes their chart geometry
- A focused scenario path starts at the last actual close and uses only its verified trigger and
  target
- PATRON median points come from reference close × (1 + q50), not from fabricated candles
- Stored PATRON predicted OHLC is passed through as ghost candles, separate from realised data

Chart price-line and band placement is validated through these projection tests plus the
underlying chart library's own coordinate handling. The canvas itself is not asserted in jsdom;
no pixel snapshots are used.

## Known limitations

- No supply/demand **zone width** is available from the current snapshot; the backend provides
  verified levels, so the chart renders lines rather than inventing a zone width.
- The current pullback plan does not emit breakout or retest prices. The UI says so explicitly
  instead of drawing arbitrary levels.
- Multi-timeframe alignment is not computed; the page states the fixed scope.
- Forex is not enabled or claimed.
- Scenario paths are level-to-level conditional sketches, not predicted candles and not
  probabilities.
- Qwen cold inference is 32–42 s on the measured RX 580; the page uses the unified cache and a
  60 s poll, so a cold load can show a deterministic chart while AI narration is unavailable.
- No live execution, stop movement, target change, or position sizing exists.
- The strategy gate is still PENDING at **0/60 reviewed cases**.
