# 10 — Backtesting, Paper Trading and Release Gates

## 1. Evaluation principle

A strategy or model is not ready because it produces attractive chart examples. It must survive time-separated, cost-aware evaluation.

## 2. Required metrics

At minimum:
- number of eligible setups;
- number of triggered trades;
- win rate;
- average win and average loss;
- expectancy per trade in R;
- profit factor;
- maximum drawdown;
- consecutive loss distribution;
- exposure/time in market;
- MFE and MAE;
- fees, funding and slippage;
- performance by regime and time period;
- calibration where probabilities are emitted.

Report confidence intervals or sample-size limitations. Do not compare tiny samples as if they establish a durable edge.

## 3. Baselines

Compare against:
- no-trade baseline;
- simple deterministic baseline;
- relevant buy-and-hold or market-direction baseline where appropriate;
- current strategy version.

Do not claim improvement without a fair, identical data/cost setup.

## 4. Validation protocol

- Chronological train/validation/test.
- Walk-forward windows.
- Purge overlapping future horizons and apply embargo where needed.
- Freeze strategy rules before final test.
- Include realistic fees, spread, slippage, funding and latency assumptions.
- Test different market regimes.
- Keep final test untouched until candidate selection is complete.

## 5. Release stages

### Gate 0 — Data correctness
No critical timestamp, leakage or market-data defects.

### Gate 1 — Unit and integration tests
Risk math, price ordering, tick/lot rounding, expiry, lifecycle and API contracts pass.

### Gate 2 — Historical evaluation
Predeclared thresholds pass on walk-forward and untouched test data.

### Gate 3 — Paper trading
Observe real-time behavior without placing real orders. Track sufficient duration and sample size as configured before evaluation.

### Gate 4 — Limited assisted release
Display validated plans with clear disclaimers and user confirmation. No automatic execution.

### Gate 5 — Future execution research
Out of scope. Requires separate approval, exchange integration security review, kill switches, reconciliation and legal/compliance review.

## 6. No universal numeric threshold

Thresholds must be selected before looking at the final test results and documented with rationale. Avoid inventing a “good” win-rate target without considering risk/reward, costs and sample size.
