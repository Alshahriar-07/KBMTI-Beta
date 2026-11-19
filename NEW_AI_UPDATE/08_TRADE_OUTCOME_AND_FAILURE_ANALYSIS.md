# 08 — Trade Outcome Tracking and Failure Analysis

## 1. Purpose

Record what the system proposed, what the user actually did, and what the market subsequently did. Separate setup quality from realized outcome.

## 2. Persist immutable records

For each setup:
- setup ID;
- generated timestamp and expiry;
- market snapshot and forecast references;
- strategy ID/version;
- Qwen base/adapter version;
- risk engine version;
- action and all plan levels;
- evidence and missing conditions;
- validation result;
- user action (accepted, ignored, edited, rejected);
- paper/manual trade ID, if any.

For each trade:
- entry/exit fills and timestamps;
- quantity;
- fees, funding and slippage;
- partial exits;
- realized P&L and R multiple;
- MFE (maximum favorable excursion);
- MAE (maximum adverse excursion);
- holding time;
- exit reason;
- rule deviations.

## 3. Outcome categories

- TP hit;
- SL hit;
- manually closed;
- expired/no entry;
- invalidated before entry;
- cancelled;
- data/operational failure.

Do not count a setup that never triggered as a losing trade. Report setup outcomes and executed-trade outcomes separately.

## 4. Failure taxonomy

Possible causes:
- market regime misclassified;
- strategy not suitable for regime;
- false breakout / failed retest;
- liquidity event or volatility shock;
- confirmation rule insufficient;
- entry too early/late;
- stop placement inconsistent with structure;
- target unrealistic;
- fees/slippage erased edge;
- data feed stale/missing/corrupt;
- PATRON forecast conflict or stale forecast;
- Qwen interpretation error;
- risk calculation/configuration error;
- user execution differed from plan;
- outcome within expected stochastic variation;
- unknown / insufficient evidence.

A loss alone does not prove which cause occurred.

## 5. Failure review output

The review engine should return:
- observed outcome;
- expected conditions vs actual market path;
- first condition that failed;
- evidence references;
- likely contributing factors;
- confidence/uncertainty in diagnosis;
- whether the strategy rule was followed;
- recommended investigation;
- whether the case is eligible for training.

Use labels such as `confirmed`, `probable`, `possible`, `unknown`. Do not present speculative diagnosis as fact.

## 6. UI review card

Show:
- Planned vs actual entry/exit;
- planned risk vs realized R;
- MAE/MFE;
- fees/slippage;
- strategy/model versions;
- timeline;
- failure/success analysis;
- “What should we learn?” summary;
- review status: pending, reviewed, approved for dataset, excluded.

## 7. Success analysis

Winning trades should also be reviewed:
- Was the setup valid at decision time?
- Did it obey strategy rules?
- Was risk within limits?
- Was the result driven by expected edge or a one-off event?
- Did execution match the plan?

Never train only on winners. Preserve the full distribution of valid and invalid cases.
