# PATRON predictive-edge research protocol (pre-registered)

**Protocol version:** `patron-predictive-edge-1.0.0`
**Registered:** 2026-11-23, before any experiment results were produced
**Status:** frozen for this research round
**Production model:** unchanged; this protocol cannot promote a checkpoint by itself

This document freezes the evaluation design, promotion thresholds and statistical
method before the fold-wise experiments are run. If a result is disappointing, the
thresholds below are **not** revised to manufacture a pass. Any later change
requires a new protocol version and a new run.

## 1. Question

Does a retrained PATRON, or a PATRON residual model, beat the last-close
persistence forecast out of sample on close-path error and directional skill,
without losing calibration or uncertainty quality?

The current deployed candidate is **not** evidence of edge: it has close MAE
23.75 bp versus 23.11 bp for persistence, directional accuracy 50.12% and 80%
coverage 87.03%. This round tests that claim honestly.

## 2. Data and folds

- Dataset: `PATRON/data/features/BTCUSDT_dataset.parquet`, 100,930 M15 bars,
  2024-01-01 → 2026-11-17 UTC.
- Targets: PATRON's existing six-candle high/low/close relative returns.
- Four expanding-window chronological folds. Fold boundaries are percentages of
  the **valid window positions**, never random samples:

| Fold | Train | Validation | Test |
|---|---|---|---|
| 1 | first ~53.8% | next 6% | next 10% |
| 2 | first ~63.8% | next 6% | next 10% |
| 3 | first ~73.8% | next 6% | next 10% |
| 4 | first ~83.8% | next 6% | final 10% |

The exact boundary algorithm is `train_end = val_start - 24 windows`,
`val_end = test_start - 24 windows`, where 24 windows = 6-bar target purge plus
6-bar embargo plus a second 12-window buffer. The harness asserts
`max(train) < min(val) < max(val) < min(test)` and that no optimizer or scaler ever
sees a validation or test row.

- Every fold refits a `RobustFeatureScaler` on **training rows only**.
- Training windows are subsampled with stride 8 to bound CPU time; validation and
  test windows are not subsampled. Each model trains for at most **8 epochs** with
  early-stopping patience **3** on validation loss. This is fixed before results.
- No test block is used for early stopping. Best epoch is selected on validation
  loss only.
- The deployed checkpoint is evaluated as a **descriptive reference only**. It was
  trained with a scaler fitted on the full history and has seen earlier portions of
  the fold periods, so it is excluded from every promotion decision.

## 3. Candidates and baselines

Evaluated on the identical fold test blocks:

1. **Last-close persistence** — forecast 0 relative return at every step.
2. **Statistical drift baseline** — 96-bar rolling mean close-to-close return,
   compounded over the horizon: `(1 + mean96)^h - 1`. Parameters are causal and
   fitted from past prices only.
3. **Existing deployed PATRON** — descriptive reference, not promotion-eligible.
4. **PATRON absolute (fold-trained)** — same architecture and loss, retrained from
   scratch on each fold's training block, quantile head initialised at persistence.
5. **PATRON residual (fold-trained)** — same architecture and fold data, but the
   close-path target is `actual_close - drift_h`; inference adds `drift_h` back.
   High/low targets remain absolute. This tests incremental movement beyond the
   statistical drift baseline rather than replacing persistence blindly.

Both retrained candidates use the same seed, epochs, stride, loss and early-stopping
rule. Only the close-target transform differs.

## 4. Metrics

Primary metric: **pooled close MAE in basis points across all six horizons and all
four folds** (mean absolute error of the median forecast).

Secondary metrics, reported pooled, per fold and per horizon:

- close RMSE, bias, return prediction error (MAE);
- directional accuracy (all windows), non-neutral accuracy, balanced accuracy,
  up/down precision and recall;
- pinball loss for q10/q50/q90 and mean pinball;
- 80% interval coverage and mean interval width;
- regime slices (see below).

Directional labels use a 1 bp neutral band for realised moves. Balanced accuracy and
precision/recall are computed on non-neutral realised moves, with predicted up =
forecast > 0 and predicted down otherwise. This definition is fixed now.

## 5. Predefined regime groups

Regime labels use the bar at the end of each input window and are causal.

- `trend_score = mean(ema9_gap / atr14_pct, ema21_gap / atr14_pct)`.
- **strong bullish:** score ≥ +0.75 and both EMA gaps > 0.
- **weak bullish:** score > +0.25 and not strong bullish.
- **sideways:** −0.25 ≤ score ≤ +0.25.
- **weak bearish:** score < −0.25 and not strong bearish.
- **strong bearish:** score ≤ −0.75 and both EMA gaps < 0.
- **low / normal / high volatility:** PATRON's existing causal `regime_vol`
  labels (`low_vol`, `normal_vol`, `high_vol`), which use expanding shifted
  quantiles of realised volatility.

These eight groups are fixed before results. No group is selected because it looks
favorable afterwards. Groups with fewer than 100 windows are still reported but
marked low-sample and cannot support a promotion decision.

## 6. Statistical method

- Paired comparisons are made at the **forecast-window** level on the same test
  rows, never by comparing aggregate numbers from different periods.
- Confidence intervals use a **paired day-block bootstrap**: UTC days are resampled
  with replacement for 2,000 replicates, preserving intraday overlap and
  cross-horizon dependence. Percentile intervals are reported.
- Because two retrained candidates are tested, the family-wise 95% gate uses
  **97.5% two-sided intervals** (Bonferroni for two candidates). Ordinary 95%
  intervals are also reported for transparency.
- Fold consistency is counted independently: a candidate must beat persistence in
  at least **3 of 4** folds on close MAE.
- Directional skill is judged by balanced accuracy, not raw accuracy alone.

## 7. Promotion criteria (all must pass)

A retrained candidate is eligible for a **promotion recommendation** only if:

1. **MAE improvement:** pooled close MAE is at least **0.50 bp lower** than
   persistence, and the 97.5% paired day-block bootstrap upper bound of
   `candidate MAE − persistence MAE` is **below 0**.
2. **Fold consistency:** it beats persistence on close MAE in at least **3/4**
   folds.
3. **Directional skill:** balanced accuracy is **≥ 0.50**, and the 97.5%
   bootstrap lower bound is **> 0.50**.
4. **Calibration:** pooled 80% coverage is in **[0.75, 0.85]**, and every fold's
   coverage is in **[0.70, 0.90]**.
5. **No error trade-off:** close RMSE is not worse than persistence, and mean
   pinball is not worse than the same baseline's empirical quantile forecast.
6. **Residual incremental value:** the residual candidate must additionally beat
   the statistical drift baseline by at least **0.25 bp** MAE with a 97.5% upper
   confidence bound below 0. Beating persistence alone is not enough for the
   residual claim.

If neither retrained candidate passes all criteria, the outcome is
**`NO_DEMONSTRATED_EDGE`**. The current production checkpoint stays in place. No
threshold is relaxed after seeing results, and no production file is modified by
this research round.

If a candidate does pass, the outcome is **`PROMOTION_RECOMMENDED`** — a
recommendation for separate human review and a controlled promotion procedure, not
an automatic deployment. Production remains unchanged until that procedure is
approved.

## 8. Leakage and safety guards

The harness records and asserts:

- fold index ordering and non-overlap;
- train/validation/test bar date ranges;
- scaler fit row range per fold;
- no test rows in scaler fit, class weights, early stopping or epoch selection;
- no checkpoint is copied to `backend/models/patron/`;
- no strategy, Qwen, risk, planning or execution code is touched.

## 9. Reproduction

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe scripts/patron_predictive_edge.py \
  --out ../docs/AI_TRADING_UPGRADE/PATRON_PREDICTIVE_EDGE_RESULTS.json
```

The results document must cite this protocol version and report every fold
separately, including failures and low-sample regime slices.
