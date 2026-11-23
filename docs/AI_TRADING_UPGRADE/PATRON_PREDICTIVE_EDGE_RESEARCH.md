# PATRON predictive-edge research — results

**Date:** 2026-11-23
**Protocol:** [`PATRON_PREDICTIVE_EDGE_PROTOCOL.md`](PATRON_PREDICTIVE_EDGE_PROTOCOL.md) (`patron-predictive-edge-1.0.0`, frozen before the run)
**Artifact:** [`PATRON_PREDICTIVE_EDGE_RESULTS.json`](PATRON_PREDICTIVE_EDGE_RESULTS.json)
**Harness:** `backend/scripts/patron_predictive_edge.py`
**Protocol-compliant run:** true
**Runtime:** 1,586 s (~26.4 min) on CPU, 6 threads
**Decision:** **`NO_DEMONSTRATED_EDGE`**

**Protocol note:** before the four-fold run, a one-fold/one-epoch debug smoke was
used only to validate tensor shapes and leakage assertions. It did not inform the
fold definitions, metric definitions, thresholds or candidate design. The fixed
8-epoch/patience-3 budget was set before the reported four-fold run; the protocol
text’s “before any experiment results” wording should be read with that debug step
in mind.
**Production model changed:** **no**

---

## 1. Executive result

Four genuine chronological walk-forward folds were trained from scratch. Each fold
refit its scaler on training rows only, used a 24-window purge/embargo gap between
train, validation and test, and evaluated on a later untouched block.

Neither retrained candidate beat last-close persistence:

| Candidate | Pooled close MAE | Persistence | Difference | 97.5% paired CI | Fold wins |
|---|---:|---:|---:|---:|---:|
| PATRON absolute | **29.85 bp** | 27.08 bp | **+2.76 bp worse** | [+2.52, +3.04] | **0/4** |
| PATRON residual | **29.87 bp** | 27.08 bp | **+2.79 bp worse** | [+2.56, +3.04] | **0/4** |
| Statistical drift | 27.99 bp | 27.08 bp | +0.90 bp worse | — | — |
| Deployed PATRON (reference only) | 27.68 bp | 27.08 bp | +0.59 bp worse | — | — |

The confidence intervals exclude zero on the wrong side: both candidates are
reliably **worse** than persistence, not merely indistinguishable from it. The
residual formulation also fails to beat the statistical drift baseline
(+1.88 bp; 97.5% CI [+1.66, +2.10]).

Directional skill is at chance: balanced accuracy 49.91% for absolute and 49.56%
for residual, with 97.5% intervals below 50%. Coverage alone is acceptable for the
residual model, but calibration cannot compensate for worse error and no directional
skill.

**Outcome: keep the current production checkpoint. Do not promote either
candidate. Mark the research result `NO_DEMONSTRATED_EDGE`.**

## 2. What was implemented vs only researched

### Implemented and executed

- A pre-registered protocol with fixed folds, thresholds and statistical method.
- `backend/scripts/patron_predictive_edge.py`, which:
  - rebuilds PATRON targets from the frozen feature dataset;
  - creates four expanding chronological folds;
  - refits `RobustFeatureScaler` on training rows only;
  - trains absolute and persistence-residual PATRON models from scratch;
  - applies purge/embargo gaps and asserts train/validation/test ordering;
  - evaluates persistence, statistical drift, both candidates and the deployed
    checkpoint on identical test rows;
  - computes per-fold, per-horizon and predefined regime metrics;
  - computes paired day-block bootstrap intervals;
  - applies the frozen promotion criteria and writes a machine-readable result.
- All four folds and both candidates were trained and evaluated. The run is
  protocol-compliant (4 folds, 8 epochs max, patience 3, stride 8, 2,000 bootstrap
  replicates).

### Researched, not implemented

- No change to PATRON architecture, features, targets, inference contract or
  production checkpoint.
- No change to strategy rules, thresholds, Qwen/KIE runtime, risk authority,
  planning gates or execution.
- No candidate was promoted. The fold checkpoints remain experimental artifacts
  under `backend/experiments/`; nothing was copied to `backend/models/patron/`.
- Longer training, multi-seed ensembles and alternative architectures were not
  tested. They remain research options, not results.

## 3. Fold design and leakage evidence

The dataset contains 100,139 valid windows (100,930 bars). Four test blocks of
10,014 windows each were used, with earlier data only for training/validation.

| Fold | Train end | Validation | Test | Train windows | Gap checks |
|---|---|---|---|---|---|
| 1 | 2025-07-22 | 2025-07-22 → 2025-09-23 | 2025-09-23 → 2026-01-06 | 54,027 | 24-window gaps; scaler ends before test |
| 2 | 2025-11-04 | 2025-11-04 → 2026-01-06 | 2026-01-06 → 2026-04-21 | 64,041 | same |
| 3 | 2026-02-17 | 2026-02-17 → 2026-04-21 | 2026-04-21 → 2026-08-04 | 74,055 | same |
| 4 | 2026-06-02 | 2026-06-02 → 2026-08-04 | 2026-08-04 → 2026-11-17 | 84,069 | same |

For every fold the harness recorded:

```text
train_last_bar < val_first_bar < val_last_bar < test_first_bar
scaler_fit_ends_before_test = true
```

The index gap is 24 valid windows (25 bar-index difference), covering the 6-bar
target horizon, the 6-bar embargo and an additional 12-window buffer. Scalers were
fit on 54,360 / 64,412 / 74,508 / 84,555 training rows respectively, never on a
validation or test row. Early stopping used validation loss only; no test block was
touched during training.

**Training budget:** at most 8 epochs, early-stopping patience 3, training stride 8.
Absolute models ran 6/8/8/8 epochs; residual models ran 8/8/8/8. Two absolute folds
selected their best epoch at epoch 8, so this CPU budget may under-train the model;
that is a limitation, not a promotion excuse.

## 4. Pooled out-of-sample metrics

40,056 test windows × 6 horizons = 240,336 close-path forecasts.

| Metric | Persistence | Statistical drift | PATRON absolute | PATRON residual | Deployed reference |
|---|---:|---:|---:|---:|---:|
| Close MAE (bp) | **27.08** | 27.99 | 29.85 | 29.87 | 27.68 |
| Close RMSE (bp) | **43.48** | 44.41 | 45.49 | 45.80 | 43.91 |
| Bias (bp) | −0.92 | +0.20 | −2.98 | +3.21 | +0.46 |
| Directional accuracy, all | 47.90% | 48.99% | 49.91% | 49.57% | 50.08% |
| Directional accuracy, non-neutral | 47.98% | 48.93% | 49.90% | 49.56% | 50.09% |
| Balanced accuracy | 50.07% | 48.93% | **49.91%** | **49.56%** | 50.08% |
| 80% coverage | 82.78% | 83.07% | 85.02% | 82.61% | 82.90% |
| Mean 80% interval (bp) | 89.55 | 93.67 | 111.10 | 97.73 | 91.31 |
| Mean pinball | **0.000953** | 0.000978 | 0.001045 | 0.001023 | 0.000968 |

The deployed checkpoint is shown for context only. Its scaler was fit on the full
history and it has seen earlier portions of these fold periods, so it is **not
leakage-safe across folds** and was excluded from every promotion decision. Even so,
it also fails to beat persistence here (+0.59 bp), consistent with the earlier
untouched-test result (+0.65 bp).

### Directional precision / recall (non-neutral realised moves)

| Candidate | Precision up | Recall up | Precision down | Recall down |
|---|---:|---:|---:|---:|
| Absolute | 49.91% | 65.52% | 49.90% | 34.31% |
| Residual | 49.44% | 41.06% | 49.65% | 58.05% |

The absolute model leans toward up calls; the residual model leans down. Neither
produces balanced skill. Persistence's zero forecast makes its precision/recall
degenerate and is therefore not used as a direction-quality benchmark.

### Paired day-block bootstrap (2,000 replicates)

| Candidate | Comparison | Point difference | 95% CI | 97.5% CI |
|---|---|---:|---:|---:|
| Absolute | vs persistence | +2.76 bp | [+2.54, +3.00] | [+2.52, +3.04] |
| Absolute | vs statistical drift | +1.86 bp | [+1.59, +2.12] | [+1.56, +2.16] |
| Residual | vs persistence | +2.79 bp | [+2.59, +3.00] | [+2.56, +3.04] |
| Residual | vs statistical drift | +1.88 bp | [+1.68, +2.08] | [+1.66, +2.10] |

Positive values mean higher (worse) MAE. Both intervals sit entirely above zero.

Balanced-accuracy 97.5% intervals: absolute [49.57%, 50.25%], residual
[49.09%, 50.02%]. The required lower bound above 50% is not met.

## 5. Per-fold results

| Fold | Test period | Persistence | Drift | Absolute | Residual | Deployed |
|---|---|---:|---:|---:|---:|---:|
| 1 | 2025-09-23 → 2026-01-06 | **28.30** | 29.33 | 33.27 | 30.76 | 28.90 |
| 2 | 2026-01-06 → 2026-04-21 | **32.81** | 33.98 | 33.11 | 34.86 | 33.33 |
| 3 | 2026-04-21 → 2026-08-04 | **24.61** | 25.29 | 28.54 | 29.27 | 25.20 |
| 4 | 2026-08-04 → 2026-11-17 | **22.62** | 23.35 | 24.47 | 24.59 | 23.29 |

Values are close MAE in bp. Neither candidate wins a single fold. The absolute
model is closest in fold 2 (33.11 vs 32.81) but still loses.

## 6. Horizon and regime results

### By forecast horizon (close MAE, bp)

| Step | Persistence | Drift | Absolute | Residual |
|---:|---:|---:|---:|---:|
| 1 | **15.10** | 15.23 | 18.07 | 15.74 |
| 2 | **21.32** | 21.68 | 23.84 | 23.05 |
| 3 | **25.96** | 26.61 | 29.97 | 30.04 |
| 4 | **29.98** | 31.01 | 30.67 | 35.09 |
| 5 | **33.48** | 34.90 | 37.05 | 36.45 |
| 6 | **36.68** | 38.49 | 39.47 | 38.86 |

The residual model is closest at step 1 (15.74 vs 15.10) but degrades badly at
step 4 and never wins a horizon. Error grows with horizon for every method, as
expected.

### Predefined regime slices (close MAE, bp)

| Group | n | Persistence | Absolute | Residual |
|---|---:|---:|---:|---:|
| Strong bullish | 8,861 | **28.12** | 30.95 | 30.55 |
| Weak bullish | 7,260 | **24.54** | 27.83 | 27.16 |
| Strong bearish | 8,798 | **32.09** | 34.11 | 35.12 |
| Weak bearish | 6,934 | **25.69** | 28.44 | 28.58 |
| Sideways | 8,203 | **24.03** | 27.04 | 26.99 |
| Low volatility | 14,521 | **18.87** | 22.29 | 22.36 |
| Normal volatility | 16,103 | **26.60** | 29.25 | 29.06 |
| High volatility | 9,432 | **40.55** | 42.50 | 42.82 |

Every predefined group exceeds 100 windows; no slice is low-sample. Persistence
wins **all eight**. No favorable subgroup is being selected after the fact: these
were fixed in the protocol before the run.

## 7. Promotion criteria — all failed

Protocol family-wise gate: 97.5% paired intervals (two candidates), 0.50 bp minimum
MAE improvement, 3/4 fold consistency, balanced-accuracy lower bound > 50%,
coverage 0.75–0.85 pooled and 0.70–0.90 per fold, no RMSE/pinball regression, and
residual improvement versus drift ≥ 0.25 bp.

| Criterion | Absolute | Residual |
|---|---|---|
| MAE at least 0.50 bp better than persistence | FAIL (+2.76) | FAIL (+2.79) |
| 97.5% MAE CI upper below 0 | FAIL | FAIL |
| Beats persistence in ≥3/4 folds | FAIL (0/4) | FAIL (0/4) |
| Balanced accuracy ≥ 50% | FAIL (49.91%) | FAIL (49.56%) |
| Balanced-accuracy 97.5% lower bound > 50% | FAIL | FAIL |
| Pooled coverage 0.75–0.85 | FAIL (85.02%) | PASS (82.61%) |
| Every fold coverage 0.70–0.90 | FAIL (fold 1: 93.64%) | PASS (76.86–86.30%) |
| RMSE not worse than persistence | FAIL | FAIL |
| Pinball not worse than persistence | FAIL | FAIL |
| Residual beats drift by ≥0.25 bp | n/a | FAIL (+1.88) |

**Eligible candidates: 0/2. Status: `NO_DEMONSTRATED_EDGE`.**

The absolute model's per-fold coverage is unstable (93.64% in fold 1, 75.21% in
fold 2), so its pooled coverage is not evidence of reliable calibration. The
residual model's coverage is acceptable, but its point error, RMSE, pinball and
directional skill are all worse than persistence.

## 8. Interpretation

1. **The previous conclusion is confirmed, not overturned.** The deployed
   candidate fixed pathological numerical behavior but has no demonstrated
   predictive superiority over persistence. On the leakage-safe folds it is also
   slightly worse than persistence (though it is not promotion-eligible).
2. **A residual formulation does not create an edge.** Subtracting a causal drift
   baseline and learning the remainder improves over the absolute model only at
   the shortest horizon and still loses to persistence overall.
3. **Directional skill is at chance.** Balanced accuracy near 49–50% with
   intervals spanning the coin-flip boundary means no reliable up/down signal.
4. **The model is likely under-trained.** The 8-epoch CPU budget is small; two
   absolute folds selected epoch 8 as best. This does not excuse the result, but a
   longer-budget or multi-seed study is a legitimate next experiment.
5. **Do not promote.** No production checkpoint was replaced, no threshold was
   relaxed and no favorable slice was used to rescue the result.

## 9. Limitations

- One local BTCUSDT M15 dataset, four folds, one seed. The bootstrap captures
  sampling variability, not model-seed or architecture variability.
- CPU budget: at most 8 epochs, stride 8. Longer training and ensembles were not
  tested; two folds had not converged at the epoch limit.
- No fees, funding, slippage, fills or execution simulation. This is forecast
  accuracy research, not a strategy PnL claim.
- The deployed checkpoint reference is not leakage-safe across folds and is
  descriptive only.
- Regime labels are causal, but the trend-strength thresholds are research
  definitions fixed in the protocol; they are not production regime labels.
- The residual candidate uses a 96-bar compounded drift base. Other statistical
  bases (AR models, cross-fitted regressions) were not tested.

## 10. What requires human approval

- **PATRON promotion:** nothing to approve; no candidate is eligible. Any future
  candidate must pass the same protocol (or a new pre-registered version) and then
  receive separate human approval before production replacement.
- **Phase 2 strategy gate:** still requires independent human disposition of cases
  40 and 53 and confirmation of an aggregate policy. See
  [`PHASE_2_GATE_CLOSURE.md`](PHASE_2_GATE_CLOSURE.md). This research did not
  change it.
- **Rule changes:** R-001 and R-002 in the gate-closure document are proposals
  only; they require version bumps, packet regeneration and new human review.

## 11. Reproduction

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe scripts/patron_predictive_edge.py \
  --out ../docs/AI_TRADING_UPGRADE/PATRON_PREDICTIVE_EDGE_RESULTS.json
```

The run uses the frozen feature dataset:

- SHA-256 `6af006c437384cd06b6012a32b2ae15f6307b956fa66900fce6ad3d19e8dc541`
- 100,930 bars, 2024-01-01 → 2026-11-17 UTC
- 100,139 valid windows; 40,056 evaluated test windows.

Protocol SHA-256: `76812675e381467eff0c55a3cef13c26cc6b08ba8a404dd2277389ce2902ab5a`.

Fold checkpoints are under `backend/experiments/kbmti_edge_f*`; they are
experimental and are not referenced by production code.

## 12. Status summary

| Item | Status |
|---|---|
| Protocol pre-registered before run | Complete |
| Genuine fold-wise retraining | Complete (4 folds, 8 models) |
| Train-only scaling | Complete |
| Purge/embargo + ordering asserts | Passed |
| Persistence-residual candidate | Tested; failed |
| Regime / horizon / directional evaluation | Complete |
| Paired bootstrap inference | Complete |
| Predictive edge versus persistence | **Not demonstrated** |
| Production model changed | **No** |
| Strategy gate | **PENDING** |
| Human approval fabricated | **No** |
