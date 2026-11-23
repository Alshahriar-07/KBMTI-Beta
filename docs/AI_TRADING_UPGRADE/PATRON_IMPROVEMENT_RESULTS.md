# PATRON improvement results

**Date:** 2026-11-22
**Decision:** candidate `kbmti_patron_candidate_v2` was **promoted as a numerical-sanity
fix**, not as a validated alpha model. The previous champion is retained for rollback.
**Evidence:** [`PATRON_AUDIT_REPORT.md`](PATRON_AUDIT_REPORT.md),
[`PATRON_AUDIT_METRICS.json`](PATRON_AUDIT_METRICS.json),
[`PATRON_CANDIDATE_METRICS.json`](PATRON_CANDIDATE_METRICS.json),
[`PATRON_DATASET_QUALITY.json`](PATRON_DATASET_QUALITY.json),
[`PATRON_ROLLING_STABILITY.json`](PATRON_ROLLING_STABILITY.json),
[`PATRON_PREDICTIVE_EDGE_RESEARCH.md`](PATRON_PREDICTIVE_EDGE_RESEARCH.md).

## 1. Original model architecture

PATRON is unchanged at the architecture level: 96×12 causal input, residual CNN blocks,
BiLSTM, 4-head self-attention, attention pooling, and four heads (patterns, barriers,
6×3×3 range quantiles, momentum). The deployed champion had **272,618** trainable
parameters and ran on CPU.

## 2. Problems discovered

1. **Quantile-head initialisation dominated the forecast.** The final linear layer's default
   bias is about ±0.125 in return units, while six-bar targets are about ±0.003. The champion
   learned near-constant per-step offsets (step 2 ≈ −1.7%) that were almost identical on
   train, validation and test.
2. **Four epochs was not enough.** Validation barrier/momentum accuracy stayed at class
   priors (0.325 / 0.223), and the quantile head never recovered from its initial bias.
3. **No baseline or coverage gate.** The champion's 80% interval averaged 1,260 bp with
   99.99% coverage, yet it was never compared with last-close persistence (23.44 bp MAE).
4. **Data was not the problem.** 100,930 bars had no gaps, duplicates, invalid OHLC, negative
   volume or target misalignment, and the causal feature check passed.

## 3. Changes implemented

- Added `scripts/train_patron_candidate.py`, which reuses PATRON's model, dataset and trainer
  but initialises the quantile head at persistence with a 0.2% half-interval and small random
  weights. It never publishes a checkpoint automatically.
- Added `PATRON/configs/candidate_v2.yaml`: learning rate `5e-4`, max 24 epochs, patience 8,
  quantile loss weight `1.0`, batch 256 via CLI, seed 42.
- Added `backend/scripts/patron_audit.py`: reproducible chronological test evaluation with
  per-horizon MAE/RMSE/bias/correlation, pinball loss, coverage, baselines and candle
  geometry.
- Added `backend/scripts/validate_patron_data.py`: raw-data checks, target alignment,
  causal-feature deletion test, hashes and split boundaries.
- Promoted the candidate checkpoint to `backend/models/patron/best.pt`; the old checkpoint is
  `backend/models/patron/CHAMPION_V1_ROLLBACK.pt`.
- No change to PATRON's inference contract, feature order, training data or chart algebra.

## 4. Dataset version

`btcusdt-15m-v1.0.0`:

- Raw: `backend/data/patron/BTCUSDT_15m.parquet`
- SHA-256: `5eb3289b32b5980d47f5af20be99484e16d9be8aa32b5f4bec12c965aa22458b`
- 100,930 rows, 2024-01-01 00:00 UTC → 2026-11-17 08:15 UTC
- Supervised: `PATRON/data/features/BTCUSDT_dataset.parquet`

Chronological split with purge 6 / embargo 6:

| Split | Windows | First bar | Last bar |
|---|---:|---|---|
| Train | 70,417 | 2024-01-04 07:45 | 2026-01-06 19:45 |
| Validation | 15,079 | 2026-01-06 23:00 | 2026-06-13 00:30 |
| Test | 15,085 | 2026-06-13 03:45 | 2026-11-17 06:45 |

The test split was untouched during candidate selection and promotion.

## 5. Training configuration and resources

| Item | Value |
|---|---|
| Hardware | Windows 11, Intel 6 cores / 6 threads, 15.92 GB RAM, AMD RX 580 (unused) |
| Backend | PyTorch `2.4.1+cpu`, `torch.cuda.is_available() == False` |
| Threads | 5 |
| Train windows used | 17,523 (training stride 4) |
| Validation windows | 15,009 |
| Batch size | 256 |
| Optimizer | AdamW, lr `5e-4`, weight decay `1e-4` |
| Epochs run | 15 (early stopping) |
| Best epoch | 7 |
| Best validation loss | `1.41644` |
| Wall time | 12 min 43 s |

## 6. Champion vs candidate on untouched test windows

2,517 sampled test windows, six horizons, 15,102 candles. MAE/RMSE/bias are in basis points;
bias is `mean(actual − predicted)`, so positive means the forecast was too low.

| Metric | Champion | Candidate | Change |
|---|---:|---:|---:|
| Close MAE | 86.61 | **24.13** | −72.1% |
| Close RMSE | 114.50 | **38.31** | −66.5% |
| Close bias | 50.98 | **1.23** | −97.6% |
| Close correlation | −0.0018 | −0.0025 | no signal |
| Directional accuracy | 49.46% | **50.35%** | +0.89 pp |
| Pinball mean | 0.005646 | **0.000851** | −84.9% |
| 80% coverage | 99.99% | **86.60%** | closer to nominal 80% |
| Mean 80% interval | 1,260.6 bp | **91.0 bp** | −92.8% |
| Predicted close std | 95.23 bp | 5.96 bp | still under-dispersed |
| Actual close std | 37.81 bp | 37.81 bp | reference |

Per-horizon close results:

| Step | Champion MAE | Candidate MAE | Candidate bias | Candidate corr | Candidate coverage |
|---:|---:|---:|---:|---:|---:|
| 1 | 31.3 | **14.1** | +1.8 | −0.0161 | 86.5% |
| 2 | 166.9 | **18.7** | −1.3 | +0.0094 | 87.0% |
| 3 | 50.5 | **25.1** | +10.0 | −0.0033 | 85.7% |
| 4 | 88.2 | **26.1** | +4.5 | +0.0138 | 87.2% |
| 5 | 116.0 | **29.2** | −3.5 | −0.0191 | 86.3% |
| 6 | 66.7 | **31.7** | −4.2 | −0.0068 | 86.9% |

## 7. Baseline comparison

| Baseline | Close MAE | Directional accuracy |
|---|---:|---:|
| Last-close persistence | **23.44 bp** | n/a (zero-return sign) |
| Previous-candle return | 27.05 bp | 49.60% |
| Rolling mean 96 returns | 23.47 bp | 49.18% |
| Candidate PATRON | 24.13 bp | **50.35%** |

The candidate is within **3%** of last-close persistence, but it does **not** beat it on MAE.
It is better than the previous-candle baseline and has a small directional edge over the
rolling-mean baseline, which is not enough to claim a trading edge. This is the central
limitation of the result.

## 8. Quantile calibration

- Nominal 80% coverage: **86.6%** (champion 99.99%).
- Mean interval: **91.0 bp** (champion 1,260.6 bp).
- Pinball q10/q50/q90: **0.000677 / 0.001206 / 0.000670**.
- Quantile-order violations: **0**.
- The median is still under-dispersed: predicted std 5.96 bp vs realised 37.81 bp. The model
  is closer to a cautious persistence forecast than a confident directional forecast.

## 9. Candle geometry

Raw q50 high is below `max(open, close)` for **18.1%** of candidate candles (champion 67.2%);
raw q50 low is above `min(open, close)` for **16.5%** (champion 66.8%). The display provider
clamps these wicks and records a warning; raw quantiles remain immutable in
`output.meta`. Realised high was below the reference close for 27.2% of candles and realised
low above it for 29.3%, so some clamping is inherent to deriving OHLC from a close-relative
forecast.

## 10. Promotion decision

**PROMOTED_AS_NUMERICAL_SANITY_FIX.** The candidate passes the measurable-improvement gate
against the champion (MAE, RMSE, pinball, bias and coverage all improve), passes dataset and
leakage checks, and passes PATRON inference/forecast-contract tests.

It does **not** pass a hypothetical “beat persistence and demonstrate directional alpha”
gate. Promoting it is justified because it removes pathological random biases and produces
usable uncertainty bands; it is not justified as a validated trading model. No order
execution, position sizing or strategy promotion follows from this change.

## 11. Integration with Qwen and the frontend

The promoted checkpoint is served through the unchanged PATRON inference interface. Its full
payload (model/feature version, as-of time, reference close, all six horizon steps with
q10/q50/q90 for high/low/close, barrier probabilities, momentum probabilities and data-quality
warnings) is carried into the unified market-intelligence response as `forecast_source`.

Qwen receives that exact source plus a deterministic `forecast_assessment` (freshness, schema,
conflict, interval width, barrier/momentum margins). It may explain reliability or disagreement
but cannot change a price, action, stop, target or risk result. In the live unified run, PATRON
was bullish while the deterministic market was strongly bearish; the system returned
`CONFLICTING_EVIDENCE`, excluded the forecast from the decision and `NO_TRADE`. That is the
intended behavior, not a contradiction to hide. See
[`QWEN_FRONTEND_PIPELINE.md`](QWEN_FRONTEND_PIPELINE.md).

A better forecast would still not by itself create a trade: the Phase 2 strategy gate remains
PENDING and execution is disabled.

## 12. Rollback instructions

The previous champion is preserved at:

```
backend/models/patron/CHAMPION_V1_ROLLBACK.pt
SHA-256 52346bf3bb29ffcac9bf06cc57d4afc38ffef06626b0ac4d54903b1475dea327
```

To roll back:

```bash
cp backend/models/patron/CHAMPION_V1_ROLLBACK.pt backend/models/patron/best.pt
# restart the backend
```

The promoted checkpoint is:

```
backend/models/patron/best.pt
SHA-256 bd809766fdd76fcd325f55f0092cc93b334d2d08ba6fa84c836624b3d89b26ec
```

## 13. Rolling out-of-sample stability (added 2026-11-23)

A new read-only audit re-evaluates both frozen checkpoints on **every** valid test
window (15,099, not the 2,517-sample audit above) in four chronological blocks. It
also compares last-close persistence, previous-candle repetition and 96-bar drift.
This is stability evidence for fixed checkpoints; it is **not** fold-wise retraining.

| Fold | Period | Candidate close MAE | Champion close MAE | Persistence MAE | Candidate dir. acc. | 80% coverage |
|---|---|---:|---:|---:|---:|---:|
| 1 | 2026-06-13 → 2026-07-22 | 26.34 bp | 87.15 bp | **25.76 bp** | 49.95% | 84.8% |
| 2 | 2026-07-22 → 2026-08-30 | 21.26 bp | 93.08 bp | **20.57 bp** | 50.43% | 89.2% |
| 3 | 2026-08-30 → 2026-10-08 | 22.57 bp | 79.05 bp | **21.91 bp** | 50.30% | 88.2% |
| 4 | 2026-10-08 → 2026-11-17 | 24.84 bp | 85.88 bp | **24.18 bp** | 49.81% | 85.9% |
| **All** | 2026-06-13 → 2026-11-17 | 23.75 bp | 86.29 bp | **23.11 bp** | 50.12% | 87.0% |

The candidate is stable (no fold collapse, coverage 84.8–89.2%) and remains
~63 bp better than the champion, but it is still **0.65 bp worse than persistence
in every fold** and directional accuracy stays at 50%. Regime slices tell the same
story: the candidate trails persistence in sideways (20.66 vs 19.97 bp), bull
(29.38 vs 28.80 bp), bear (27.65 vs 27.06 bp), low-vol (18.75 vs 18.05 bp) and
high-vol (35.38 vs 34.87 bp) windows.

**Conclusion:** the numerical-sanity promotion stands; no new accuracy claim is
made. The subsequent predictive-edge round did train genuine fold-wise absolute
and residual candidates. It found **no candidate that beat persistence** and
recorded `NO_DEMONSTRATED_EDGE`; production remained unchanged. See
[`PATRON_PREDICTIVE_EDGE_RESEARCH.md`](PATRON_PREDICTIVE_EDGE_RESEARCH.md).

## 14. Reproduction

```bash
# 1. Validate data, alignment and causality
cd backend
PYTHONPATH=. .venv/Scripts/python.exe scripts/validate_patron_data.py

# 2. Train the candidate (does not publish it)
cd ..
backend/.venv/Scripts/python.exe scripts/train_patron_candidate.py \
  --config PATRON/configs/candidate_v2.yaml --epochs 24

# 3. Evaluate champion and candidate on the chronological test split
cd backend
PYTHONPATH=. .venv/Scripts/python.exe scripts/patron_audit.py \
  --checkpoint ../PATRON/experiments/kbmti_patron_candidate_v2_20261122-204345/best.pt \
  --out ../docs/AI_TRADING_UPGRADE/PATRON_CANDIDATE_METRICS.json

# 4. Rolling out-of-sample stability for both frozen checkpoints
PYTHONPATH=. .venv/Scripts/python.exe scripts/patron_stability.py \
  --out ../docs/AI_TRADING_UPGRADE/PATRON_ROLLING_STABILITY.json

# 5. Pre-registered fold-wise retraining and residual research (long CPU run)
PYTHONPATH=. .venv/Scripts/python.exe scripts/patron_predictive_edge.py \
  --out ../docs/AI_TRADING_UPGRADE/PATRON_PREDICTIVE_EDGE_RESULTS.json
```

## 15. Known limitations

- No demonstrated directional edge (50.35% accuracy is within noise for this sample).
- Median forecasts are under-dispersed and do not beat a zero-return persistence baseline on
  MAE.
- Barrier and momentum heads remain near chance; only the range head was materially repaired.
- One seed, one local dataset. Four-fold retraining was added later, but it still uses one
  seed, one architecture and an 8-epoch CPU budget; no multi-seed ensemble or production
  promotion exists.
- CPU-only training; no claim of production readiness. The fold-wise round found
  `NO_DEMONSTRATED_EDGE` versus persistence.
- The Phase 2 strategy gate remains **PENDING acceptance**: 60/60 automated evidence reviews
  are complete, independent human sign-off is outstanding. A forecast is not a trade.
