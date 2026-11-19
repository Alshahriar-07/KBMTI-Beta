# 04 — Dataset and Labeling Specification

## 1. Objective

Create high-quality examples for trading-context interpretation and strategy selection. The dataset must teach disciplined decision-making, not hindsight storytelling.

## 2. Required fields

Every case should include:
- unique case ID;
- symbol and timeframe;
- event timestamp and timezone;
- market-data source and data version;
- OHLCV snapshot reference;
- indicator/structure feature version;
- PATRON forecast reference and model version, if used;
- strategy-rule version;
- decision timestamp;
- decision label: LONG, SHORT, WAIT or NO_TRADE;
- entry/stop/target plan reference, if applicable;
- confirmation and invalidation conditions;
- label source and reviewer;
- train/validation/test assignment;
- synthetic/real flag;
- quality and leakage checks.

## 3. Labeling policy

- Label what was knowable at the decision timestamp.
- Do not include future candles, future returns, or final outcome in model input.
- Store future outcome separately for evaluation.
- A losing trade can still be a valid setup if it followed its rules and respected risk.
- A winning trade can still be invalid if it relied on leakage, rule violation or excessive risk.
- Ambiguous examples should be marked `unresolved` and excluded from supervised targets until reviewed.
- Store disagreement between reviewers; do not silently force consensus.

## 4. Time-series split

Use chronological splits, not random row splits:
- training: oldest period;
- validation: later period for model/strategy selection;
- final test: latest untouched period.

Use purging/embargo around overlapping label horizons where needed. Group related windows so near-duplicate candles cannot leak across splits.

## 5. Class balance

Measure LONG, SHORT, WAIT and NO_TRADE proportions. Do not artificially balance by duplicating cases without documenting it. Consider weighted sampling only after measuring its effect on calibration and real-world action frequency.

## 6. Dataset quality gates

Reject or quarantine:
- missing timestamps;
- duplicate snapshots;
- inconsistent symbol/timeframe;
- invalid OHLCV;
- future-derived features in input;
- labels without provenance;
- synthetic samples not marked synthetic;
- inconsistent price units;
- impossible trade levels;
- examples whose strategy version is unknown.

## 7. Dataset manifest

Each dataset release must include:
- dataset version;
- source hashes;
- row counts by split and label;
- date ranges;
- excluded-case count and reasons;
- leakage audit;
- reviewer/approval record;
- transformation code version.

Keep the final test set sealed until the candidate is frozen.
