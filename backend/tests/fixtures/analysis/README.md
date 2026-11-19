# Analysis fixtures (synthetic, frozen)

These JSON files are **deterministic synthetic BTCUSDT M15 candles** used only by
the market-intelligence tests. They are not real market history and make no
performance claim. Each file records `"synthetic": true` and a description.

| File | Purpose |
|---|---|
| `uptrend.json` | Rising path with regular swings; expects `UPTREND`, bullish EMA structure, BOS_UP |
| `downtrend.json` | Falling path with regular swings; expects `DOWNTREND`, BOS_DOWN |
| `sideways.json` | Range around 60000; expects neutral trend, `RANGING`, `RANGING` regime |
| `high_volatility.json` | Wide range and large wicks; expects `HIGH`/`EXTREME` ATR percentile |
| `low_volatility.json` | Normal range followed by sustained contraction; expects `LOW` volatility |
| `breakout.json` | 30-hour range then a close-based rally; expects a confirmed `BOS_UP` |
| `reversal.json` | Uptrend then decline through prior swing lows; expects `CHOCH_DOWN` |
| `insufficient.json` | 40 bars; below the 100-bar warm-up requirement |
| `invalid.json` | 140 bars with one candle whose high is below its low |
| `future_forming.json` | 140 closed bars plus two future/forming bars that must be excluded |
| `liquidity.json` | Equal highs/lows plus a wick sweep that closes back inside and is confirmed next bar |

Candle times start at 2026-10-20T00:00Z and step 900 seconds. Tests derive their
injected clock from the last eligible candle close, so no fixture depends on the
wall clock. Regenerating them is a deliberate test-data change, not a runtime task.
