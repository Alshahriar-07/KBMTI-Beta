# Next research priorities after `NO_DEMONSTRATED_EDGE`

**Date:** 2026-11-23
**Status:** research backlog only
**Production effect:** none; checkpoint, strategy rules, thresholds and execution unchanged

The PATRON edge study is closed with `NO_DEMONSTRATED_EDGE`. The next work should
answer narrower, falsifiable questions instead of retraining the same design harder.

## Priority order

### P1 — Uncertainty and volatility calibration

**Question.** Do PATRON's quantiles and volatility state provide usable uncertainty,
even when the point forecast is worse than persistence?

**Why first.** The residual model had acceptable coverage but poor error and no
directional skill. Calibration is a separate, measurable property and can be useful
for WAIT/NO_TRADE decisions without pretending to forecast price.

**Pre-registered success.** Pre-declared 80%/90% coverage tolerance in every fold,
quantile/pinball loss no worse than persistence, stable interval width under
volatility regimes, and no degradation of the deterministic risk decision.

**Do not.** Convert a calibrated interval into an entry, stop or position size.

### P2 — Regime and structure-state classification

**Question.** Can a model predict regime persistence or transition better than a
simple state baseline?

**Why second.** Regime classification might condition risk and setup selection even
if close-path forecasting fails. It is a different label and must use a different
baseline.

**Pre-registered success.** Out-of-sample balanced accuracy with a lower confidence
bound above the majority/state-persistence baseline, per-regime confusion matrices,
and stable performance across folds.

**Do not.** Treat a regime label as a trade instruction.

### P3 — Alternative horizons

**Question.** Is there a horizon where a causal, retrained model beats persistence?

**Why third.** The current study tests a 6-bar close path. A 1-bar, 4-bar or 24-bar
target may have different signal-to-noise and different costs; each needs its own
persistence/drift baseline and pre-registered threshold.

**Pre-registered success.** Same fold/leakage discipline, paired CI upper bound below
zero for the chosen proper score, and no cherry-picking the best horizon after seeing
results.

**Do not.** Reuse the 6-bar protocol's thresholds without a new registration.

### P4 — Execution-aware economic evaluation

**Question.** If a forecast or regime signal exists, does it survive spread, fees,
slippage, latency and realistic fills?

**Why later.** Accuracy is not profitability. This study requires a cost model,
fill assumptions, and a strategy/risk gate that is still PENDING.

**Pre-registered success.** Net expectancy after costs with a confidence interval,
drawdown/risk limits, and no dependence on impossible fills. A positive gross
accuracy result alone is not enough.

### P5 — Data quality and leakage hardening

**Question.** Are there dataset shifts, duplicate bars, missing candles or target
alignment errors that explain the no-edge result?

**Why continuous.** Every experiment must record dataset hash, feature hash, fold
boundaries and scaler fit boundaries. Data quality is a precondition, not a result.

## Explicit non-priorities

- No automatic retraining or checkpoint replacement.
- No “more epochs” run used as promotion evidence without a new pre-registration.
- No multi-seed ensemble presented as independent validation.
- No model comparison that uses the deployed checkpoint as leakage-safe test evidence.
- No change to frozen strategy rules, risk authority, planning gates or execution.
- No profitability claim from forecast accuracy.

## Decision rule for the next experiment

The next experiment may start only when its protocol states, before execution:

1. the hypothesis and the single primary metric;
2. folds, purge/embargo, train-only scaling and untouched test blocks;
3. the persistence and statistical baselines;
4. the confidence procedure and promotion threshold;
5. the artifact hash and seed;
6. what result would be reported as a failure.

Until then, PATRON remains a probabilistic source input, not validated alpha. The
strategy gate remains PENDING and execution remains DISABLED.
