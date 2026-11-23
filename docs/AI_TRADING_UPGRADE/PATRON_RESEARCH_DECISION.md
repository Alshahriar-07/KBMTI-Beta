# PATRON research decision — persistence remains the benchmark

**Date:** 2026-11-23
**Decision:** `NO_DEMONSTRATED_EDGE`
**Production checkpoint:** unchanged (`backend/models/patron/best.pt`, SHA-256 `bd809766…b26ec`)
**Rollback checkpoint:** unchanged (`backend/models/patron/CHAMPION_V1_ROLLBACK.pt`, SHA-256 `52346bf3…ea327`)
**Promotion:** none; neither candidate is eligible
**Evidence:** [`PATRON_PREDICTIVE_EDGE_RESEARCH.md`](PATRON_PREDICTIVE_EDGE_RESEARCH.md),
[`PATRON_PREDICTIVE_EDGE_RESULTS.json`](PATRON_PREDICTIVE_EDGE_RESULTS.json),
protocol [`PATRON_PREDICTIVE_EDGE_PROTOCOL.md`](PATRON_PREDICTIVE_EDGE_PROTOCOL.md)

## 1. Why persistence is the benchmark

Persistence forecasts the last closed close for every future horizon. It has no
learned parameters, no scaler, no checkpoint and no training leakage, so it is the
honest floor any model must beat before a more complex method is worth deploying.

The comparison is deliberately narrow and falsifiable:

- same four chronological test blocks;
- same 240,336 close-path forecasts;
- same 6-bar horizon;
- same MAE/RMSE, directional, coverage and pinball metrics;
- same day-block bootstrap for paired differences.

The deployed PATRON checkpoint is shown only as a reference. It was excluded from
promotion because its scaler was fit on full history and it has seen earlier parts of
the fold periods. It also fails to beat persistence (+0.59 bp pooled).

## 2. Why PATRON has not demonstrated an edge

| Candidate | Pooled MAE | Persistence | Difference | 97.5% CI | Fold wins |
|---|---:|---:|---:|---:|---:|
| Absolute | 29.85 bp | **27.08 bp** | +2.76 bp worse | [+2.52, +3.04] | 0/4 |
| Residual | 29.87 bp | **27.08 bp** | +2.79 bp worse | [+2.56, +3.04] | 0/4 |

- Both candidates lose in **every fold**, not just on average.
- The confidence intervals exclude zero on the wrong side: the evidence says worse,
  not “inconclusive.”
- The residual model also loses to the statistical drift baseline by **+1.88 bp**
  (97.5% CI [+1.66, +2.10]), so residualising did not isolate a learnable signal.
- Directional balanced accuracy is **49.91%** absolute and **49.56%** residual; the
  97.5% intervals do not establish above-chance direction.
- Persistence wins every predefined regime slice and every horizon.
- Absolute calibration is unstable (fold coverage 93.64% / 75.21% / 85.26% / 85.98%);
  residual coverage is acceptable but its error and direction are worse.

This is not a claim that PATRON can never work. It is a claim that **this tested
design, data, target and budget did not beat the benchmark**, and therefore must not
be promoted or described as validated alpha.

## 3. Separate research questions worth pursuing

These are research candidates, not production changes:

1. **Volatility and uncertainty.** The model exposes quantiles, but calibration is
   not stable. A separate study should test interval coverage, interval width and
   quantile loss under regime shifts. Success is calibration, not a prettier point
   forecast.
2. **Regime classification.** Predicting regime transitions or structure-state
   persistence is a different task from predicting the close path. It could be
   useful as a conditioning variable even if it never produces a price forecast.
3. **Alternative horizons.** The tested 6-bar close path may be the wrong target.
   Separate pre-registered tests could cover 1-bar, 4-bar and 24-bar horizons, with
   horizon-specific persistence and drift baselines.
4. **Economic evaluation.** Accuracy research must eventually be connected to costs,
   spread, slippage, fill assumptions and position sizing. That is a separate
   execution-aware study, not a promotion shortcut.

None of these deserves automatic retraining or a production checkpoint change.

## 4. Evidence that would justify another experiment

A new experiment is justified only if it is pre-registered and has a measurable
chance of clearing all of the following:

- genuine walk-forward folds with train-only normalization, purge/embargo and
  untouched later test blocks;
- a paired improvement over persistence with the **upper bound of the 97.5% CI below
  zero** for MAE (or an equivalent pre-declared proper score);
- improvement over the statistical drift baseline, not merely over an older model;
- directional skill whose **lower bound** is above 50% and stable across folds;
- calibrated intervals (pre-declared coverage tolerance) without a material error
  regression;
- reproducibility from a fixed seed, dataset hash, protocol hash and artifact;
- a separate economic evaluation before any claim of profitability.

If those conditions are not met, the correct outcome is `NO_DEMONSTRATED_EDGE` and
the production checkpoint stays unchanged.

## 5. Forecast accuracy is not profitability

A lower MAE only means the forecast is closer to the realised close under the chosen
loss. It does **not** mean:

- a trade would have been profitable;
- spread, fees, funding or slippage would be covered;
- entries, stops or targets would have filled;
- position sizing or risk limits would have been satisfied;
- the strategy gate would pass;
- execution is enabled.

The repository has no order execution, no verified account sizing and a **PENDING**
strategy gate. No PnL, win rate, expectancy or “validated alpha” is claimed here.
WAIT and NO_TRADE remain valid outcomes.
