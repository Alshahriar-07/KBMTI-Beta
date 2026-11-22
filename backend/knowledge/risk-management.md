<!-- id: risk-management version: 1.0.0 tags: risk reward stop invalidation position sizing breakeven partial exit -->

# Risk and trade management

Risk per unit is the distance between the planned entry and the structural stop. R:R is
the reward distance divided by that risk. A high R:R does not make a low-quality setup
good.

Invalidation is the observable condition that proves the setup wrong. It must be
defined before entry. For a long, a closed candle below the structural stop is an
invalidation; for a short, a closed candle above it. Moving a stop farther away to
avoid a loss changes the risk after the fact and is not allowed by the plan.

Partial exits and breakeven management must be predeclared. A common policy is to take
a partial at TP1 and only then consider moving the stop to breakeven, but KBMTI does
not assume that policy unless the plan says so.

Position size requires account equity, contract size, tick value, fees and a verified
risk budget. Without those inputs the status is NOT_CALCULATED. Never infer an account
balance from a chart or a model.

WAIT and NO_TRADE are valid decisions. A setup that is not confirmed is not a trade.
