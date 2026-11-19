# 05 — Strategy Engine Specification

## 1. Purpose

The Strategy Engine evaluates explicit, versioned strategies against a validated market snapshot. It produces candidate setups and rejection reasons. Qwen may explain and compare candidates but must not silently rewrite strategy rules.

## 2. Strategy registry

Each strategy definition should contain:
- stable strategy ID and semantic version;
- supported symbols/timeframes;
- market regimes where it is allowed;
- required inputs and feature versions;
- entry conditions;
- confirmation conditions;
- invalidation conditions;
- stop methodology;
- target methodology;
- max holding horizon;
- cooldown and duplicate-signal rules;
- risk constraints;
- known failure modes;
- backtest and paper-trade status.

## 3. Initial strategy research candidates

Do not activate all strategies at once. Research and test individually:
1. Trend pullback with confirmation.
2. Breakout and retest.
3. Range support/resistance rejection.
4. Liquidity sweep followed by structure confirmation.
5. Momentum continuation.

Each strategy must have objective definitions. Terms such as “strong momentum” must map to measurable feature rules or be explicitly marked as qualitative.

## 4. Candidate decision states

- `LONG`: validated long candidate exists.
- `SHORT`: validated short candidate exists.
- `WAIT`: a setup is developing but confirmation is missing.
- `NO_TRADE`: no valid setup, data is stale, conditions conflict, or risk constraints fail.

A directional market bias is not itself a trade signal.

## 5. Candidate output

```json
{
  "candidate_id": "stable-id",
  "strategy_id": "strategy-name",
  "strategy_version": "1.0.0",
  "action": "WAIT",
  "market_regime": "unknown",
  "conditions_met": [],
  "conditions_missing": [],
  "rejection_reasons": [],
  "evidence_refs": [],
  "expires_at": "timestamp"
}
```

## 6. Strategy selection

Use deterministic eligibility filters first. Rank eligible strategies using documented criteria. If two strategies conflict or data quality is inadequate, return WAIT/NO_TRADE and explain the conflict.

## 7. PATRON integration boundary

PATRON forecast is one optional evidence input, never a mandatory vote and never a replacement for confirmation. Store its forecast reference and horizon. Show forecast uncertainty. Do not label PATRON forecast direction as a calibrated probability unless separately validated.

## 8. Strategy change control

Every strategy change creates a new version. Re-run unit tests, historical backtest, walk-forward evaluation and paper-trading checks. Never modify a strategy in place while preserving its old performance record.
