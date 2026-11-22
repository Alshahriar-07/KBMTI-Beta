# PATRON forecast accuracy audit

**Date:** 2026-11-22
**Scope:** the deployed local checkpoint at `backend/models/patron/best.pt` before the
candidate promotion, its data pipeline and its chart derivation.
**Evidence:** [`PATRON_AUDIT_METRICS.json`](PATRON_AUDIT_METRICS.json),
[`PATRON_DATASET_QUALITY.json`](PATRON_DATASET_QUALITY.json), and the checkpoint's own
`MODEL_PROVENANCE.json`. All numbers below are measured; none are estimates.

## 1. Existing architecture

PATRON is a CPU PyTorch multi-head forecaster, not a chat model.

- Input: 96 closed BTC/USDT 15m candles plus 384 warm-up bars.
- Features: 12 causal features (`open_rel`, `high_rel`, `low_rel`, `close_rel`,
  `volume_log_rel`, `body_to_range`, `atr14_pct`, `rsi14_scaled`, `ema9_gap`,
  `ema21_gap`, `volume_spike`, `htf_trend`).
- Network: 1D projection → three residual CNN blocks → BiLSTM → 4-head self-attention →
  attention pooling → four heads (12 pattern tags, 3 barrier classes, 6×3×3 range
  quantiles, 5 momentum classes).
- Parameters: **272,618**, all CPU.
- Output contract: immutable relative-return quantiles, barrier probabilities and momentum
  class probabilities. The backend derives display candles from `reference_close × (1 + q50)`.

## 2. Dataset quality

Measured by `backend/scripts/validate_patron_data.py`:

| Check | Result |
|---|---|
| Rows | 100,930 closed 15m bars |
| Range | 2024-01-01 00:00 UTC → 2026-11-17 08:15 UTC |
| Duplicate timestamps | 0 |
| Non-15m steps / gaps | 0 / 0 |
| Invalid OHLC rows | 0 |
| Negative volume | 0 |
| Null cells | 0 |
| Abnormal-volume rows (median + 25×MAD) | 430, flagged only; genuine spikes retained |
| Timestamps timezone-aware | Yes |
| Target alignment (`tgt_*` vs recomputed future candles) | All 18 columns match to <1e-12 |
| Causal feature check (delete all data after bar *k*) | Passed at rows 5,000 / 50,000 / 90,000 |

The dataset is **not** the cause of the bad forecasts. The raw data is clean, chronologically
ordered and target-aligned, and no future information enters the 12 features.

Chronological split (purge 6, embargo 6):

| Split | Windows | First bar | Last bar |
|---|---:|---|---|
| Train | 70,417 | 2024-01-04 07:45 | 2026-01-06 19:45 |
| Validation | 15,079 | 2026-01-06 23:00 | 2026-06-13 00:30 |
| Test | 15,085 | 2026-06-13 03:45 | 2026-11-17 06:45 |

## 3. Root causes discovered

### 3.1 The quantile head was initialised at a scale 40× larger than its targets

`nn.Linear(64, 54)` uses PyTorch's default bias `U(-1/√64, +1/√64)`, i.e. roughly **±0.125**.
PATRON's range targets are relative returns of roughly **±0.003** at the six-bar horizon.
The random initial bias therefore dominated the forecast long before the optimiser could
correct it.

Measured consequences on held-out windows:

- Mean test bias by step (actual − predicted): step 1 `+9.1 bp`, step 2 **`+166.6 bp`**,
  step 3 `+8.0 bp`, step 4 `−41.8 bp`, step 5 `+104.7 bp`, step 6 `+59.2 bp`.
- These are nearly constant offsets across train, validation and test, not conditional
  market signal. A correctly fitted model cannot predict a fixed −1.7% at step 2.
- The softplus spread channels were likewise random, producing an 80% band about
  **1,260 bp** wide and **99.99%** empirical coverage.

### 3.2 Training stopped after four epochs

The promoted checkpoints were trained for only 4 epochs. At the last epoch:

- validation barrier accuracy **0.325** (three-class chance 0.333),
- validation momentum accuracy **0.223** (five-class chance 0.200),
- validation loss **1.4394**, still falling slowly.

The classification heads never left their priors, and the quantile head did not have time to
undo its initial bias. This is under-training, not overfitting.

### 3.3 No baseline or calibration gate

The previous evaluation looked at stored runs and charts, but did not compare against
last-close persistence, previous-candle persistence or a rolling-mean drift. It also did not
check nominal interval coverage. The deployed model was therefore allowed to be much worse
than a one-line baseline without anyone seeing it.

### 3.4 The chart derivation is not the root cause

The forecast provider preserves raw quantiles in `output.meta` and derives display candles
from the q50 median. Because the q50 high/low are relative to the reference close, the
derived high is below `max(open, close)` for **67.2%** of champion candles (low above
`min(open, close)` for **66.8%**). The provider clamps the displayed wick to the candle body
and records a warning; the underlying model numbers are not rewritten. This cosmetic
adjustment amplifies the visual impression of bad candles but did not cause the numerical
error.

## 4. Training and evaluation limitations

- CPU-only PyTorch; no CUDA. Training is feasible but slow (about 45 s per epoch at 17.5k
  training windows and batch 256 with five threads).
- One local checkpoint; no multi-seed distribution.
- Barrier and momentum heads remain near chance even after the fix; the model is a
  short-horizon quantile estimator, not a validated directional strategy.
- The test period includes a regime not represented in training; any apparent edge must be
  rechecked walk-forward.
- The Phase 2 strategy gate is still PENDING (0/60 reviewed). A better forecast does not
  create a validated trade.

## 5. Recommended improvements (implemented in the candidate)

1. Initialise the quantile head at persistence with a realistic interval
   (`median=0`, spread→0.2%) before training.
2. Train long enough for early stopping, with a lower validation-loss plateau.
3. Compare against persistence, previous-candle and rolling-mean baselines on untouched
   test data, per horizon.
4. Require nominal 80% interval coverage near 80%, not 99.99%.
5. Keep the previous checkpoint and promote only after a reproducible evaluation.
6. Add a dataset/leakage audit script and a forecast audit script to the repository.

## 6. Risks and compatibility

- The inference contract (96×12 input, 6-step quantiles, feature order) is unchanged.
- Old checkpoints still load; only the *scale* of their outputs differs. No schema migration
  is needed.
- The previous champion is retained as `backend/models/patron/CHAMPION_V1_ROLLBACK.pt`.
- Raw forecast values remain immutable source evidence. Qwen and the frontend may interpret
  them but cannot replace them.
- Even after the fix the model has no demonstrated directional edge and is not a validated
  trading signal. This limitation is carried into
  [`PATRON_IMPROVEMENT_RESULTS.md`](PATRON_IMPROVEMENT_RESULTS.md).
