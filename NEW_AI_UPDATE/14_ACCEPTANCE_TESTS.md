# 14 — Acceptance Tests and Definition of Done

## 1. Compatibility

- Existing chat endpoints remain compatible.
- Existing deterministic chat works when Qwen is unavailable.
- PATRON forecasting behavior, model, training and chart data contract remain unchanged.
- Existing forecast chart remains visually distinguishable from actual candles.
- No Ollama, cloud inference or external inference server is introduced.

## 2. Market context

- Every snapshot has symbol, timeframe, timestamp, source and feature version.
- Stale/missing data is detected.
- Indicator and structure calculations have deterministic fixtures.
- Invalid OHLCV is rejected.

## 3. Strategy engine

- LONG/SHORT candidates require all configured conditions.
- Missing confirmation returns WAIT.
- No eligible setup returns NO_TRADE.
- Every candidate has strategy version, expiry and evidence references.
- Conflicting strategies do not silently produce a forced signal.

## 4. Risk engine

- LONG/SHORT stop and target ordering is correct.
- Tick/lot rounding is tested.
- Zero stop distance is rejected.
- Missing account/instrument inputs do not produce fabricated size.
- Configured risk cap is never exceeded.
- Stale data and failed risk validation block actionable plans.

## 5. Qwen

- Structured output validates against schema.
- Unsupported numeric claims are rejected.
- Missing context causes a tool request or WAIT, not guessing.
- Model cannot override deterministic risk output.
- No-trade behavior is evaluated.
- Base model and candidate adapter are compared on held-out cases.

## 6. UI

- Decision card shows LONG/SHORT/WAIT/NO_TRADE.
- Evidence for and against is visible.
- Entry, SL, TP and invalidation are independently toggleable chart layers.
- PATRON forecast remains a separate layer.
- Stale, unavailable, rejected and expired states are visible.
- No old setup is presented as current without a stale indicator.

## 7. Trade journal and outcomes

- Every setup is immutable and traceable.
- User accept/reject/edit actions are recorded.
- Untriggered setups are not counted as losing trades.
- Fees/slippage are included when known.
- R, MFE and MAE calculations have fixtures.
- Failure analysis distinguishes confirmed/probable/possible/unknown.

## 8. Learning pipeline

- Training examples have provenance and split metadata.
- Leakage audit blocks invalid datasets.
- Candidate training cannot overwrite production weights.
- Candidate evaluation includes old-task regression checks.
- Promotion requires explicit approval.
- Rollback restores the previous known-good version.
- PATRON training is not triggered or modified.

## 9. Release report

Every phase must produce a report with:
- scope completed;
- files changed;
- tests run and exact results;
- benchmark methodology and raw results;
- limitations and known defects;
- compatibility findings;
- pass/fail against acceptance criteria;
- next phase recommendation.

Never report “all tests pass” unless the complete relevant suite actually ran.
