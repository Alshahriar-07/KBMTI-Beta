# Phase 2 — Evidence-based review of the 60 exported cases

**Date:** 2026-11-23
**Strategy:** `trend_pullback` 1.0.0, frozen config `trend-pullback-config-1.0.0`
**Review progress:** **60 / 60**
**Review outcome:** **58 PASS, 2 PASS_WITH_MANUAL_FLAG, 0 disagreements**
**Acceptance:** **PENDING — automated review is not independent human approval**
**Artifacts:** [`PHASE_2_EVALUATION.json`](PHASE_2_EVALUATION.json),
[`PHASE_2_REVIEW_EVIDENCE.json`](PHASE_2_REVIEW_EVIDENCE.json),
[`PHASE_2_REVIEW_RESULTS.json`](PHASE_2_REVIEW_RESULTS.json)

---

## 1. Scope and frozen inputs

The review used the original exported packet unchanged:

- 60 cases, 30 `NO_TRADE`, 29 `WAIT`, 1 `SHORT`; no `LONG` case was selected.
- BTCUSDT M15, 100,930 closed bars, 2024-01-01 → 2026-11-17.
- Dataset SHA-256 `5eb3289b32b5980d47f5af20be99484e16d9be8aa32b5f4bec12c965aa22458b`.
- Strategy version `1.0.0`; config version `trend-pullback-config-1.0.0`.
- No threshold, rule ordering, case, label or original decision was changed.

The compact exported cases do not contain the rule inputs. `PHASE_2_REVIEW_EVIDENCE.json`
replays each case from the same parquet bar and records the actual snapshot values
(EMAs, ATR, RSI, MACD histogram change, ROC, trend/structure/regime, swings, events,
sweeps, levels and all strategy checks). Replay reproduced **60/60 evaluation IDs,
60/60 snapshot IDs and 60/60 original decisions exactly**.

## 2. Review method and provenance

**Reviewer:** `Freebuff automated coding agent (LLM); not a human`.

This review is **not** independent human approval and must not be represented as
such. The method was:

1. Reconstruct the closed-bar snapshot for each case from the frozen dataset.
2. Re-apply the documented gate order and numeric thresholds independently:
   validation/freshness → features → established trend → regime → extreme
   volatility → opposite structure → adverse CHoCH (40 bars) → structure alignment
   → pullback location/extensions → momentum deterioration → closed-bar
   confirmation → room (1.0 ATR) → confirmed adverse sweep (0.75 ATR / 8 bars).
3. Derive a reviewed decision from those inputs **without reading the original
   decision first**. The original decision was compared only afterwards.
4. Record PASS / PASS_WITH_MANUAL_FLAG / FAIL and, for flagged cases, the exact
   reason.

Decisions were counted only after being derived; they were not copied from the
exported `decision` field. All 60 derivations happened to agree with the original
outcome, which is reported as a 60/60 conformance result, not as independent alpha
evidence.

## 3. Aggregate validation

```text
exported cases                    60
unique case IDs                   60
unique evaluation IDs             60
reviewed cases                    60
missing reviews                    0
invalid reviewed decisions         0
disagreements                      0
PASS                              58
PASS_WITH_MANUAL_FLAG              2   (cases 40, 53)
review-packet status          COMPLETE
acceptance status              PENDING
strategy_validation_status     PENDING
```

The documented helper `aggregate_review()` was run and reports the completed
packet. The gate was **not** marked PASSED:

1. The original Phase 2 requirement calls for independent **human** review; this
   review was performed by an automated agent.
2. The repository does not define an aggregate minimum-agreement or
   candidate-performance acceptance threshold. Inventing one would weaken or
   rewrite the gate.
3. The packet contains a single candidate. That cannot establish a statistically
   meaningful edge or failure rate.
4. Two cases require manual disposition (below).

Consequently `strategy_validation_status` remains **PENDING**, trade plans remain
**UNAVAILABLE**, and execution remains **DISABLED**. No gate was bypassed.

## 4. Cases requiring manual review

**Case 40 — 2025-12-13 02:00 UTC — SHORT (the only candidate).**
All applicable frozen gates passed: trend `STRONG_BEARISH`, structure `DOWNTREND`,
regime `TRENDING_DOWN`, volatility `LOW`, fast EMA distance `-0.12 ATR`, depth
`0.52 ATR`, RSI `47.34`, histogram change `-17.99`, confirmation true, and no
confirmed adverse sweep within `0.75 ATR` / 8 bars. However, there was **no support
level below price**, so the frozen "room to support ≥ 1.0 ATR" check was not
applicable rather than passed. Manual review should confirm that a missing support
level is intended to allow a short candidate. Hindsight label: miss,
`-0.0229%`, `0.13 ATR` move over 16 bars — a measurement, not a trade result.

**Case 53 — 2026-07-30 14:00 UTC — NO_TRADE.**
The blocking `CHOCH_DOWN` at 04:15 was exactly **40 bars** old, the inclusive
lookback limit. Two later `CHOCH_UP` events (24 and 23 bars old) do not clear it
under the frozen rule. The rejection conforms to the written rule, but the boundary
is borderline and the "later opposing CHOCH" semantics should be confirmed
manually.

No case was marked `NEEDS_CLARIFICATION`: all required rule inputs were present.
The missing support in case 40 is a rule-coverage gap, not absent case evidence.

## 5. Individual case results

`Result` means conformance to the frozen rules, not profitability. Hindsight
forward moves are deliberately not used as a review criterion.

| Case | Candle (UTC) | Recorded | Reviewed | Result | Decisive gate / evidence |
|---:|---|---|---|---|---|
| 1 | 2024-01-03 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_UP |
| 2 | 2024-01-07 14:00 | WAIT | WAIT | PASS | fast +2.20 ATR, depth -2.57 ATR, extended=True |
| 3 | 2024-02-08 02:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_UP |
| 4 | 2024-02-15 02:00 | WAIT | WAIT | PASS | fast +0.87 ATR, depth 2.03 ATR, extended=True |
| 5 | 2024-03-15 14:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_UP |
| 6 | 2024-03-24 02:00 | WAIT | WAIT | PASS | fast -0.62 ATR, depth 2.47 ATR, extended=True |
| 7 | 2024-04-18 02:00 | WAIT | WAIT | PASS | fast +0.94 ATR, depth -0.18 ATR, extended=True |
| 8 | 2024-04-22 02:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_DOWN |
| 9 | 2024-05-27 14:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_UP |
| 10 | 2024-05-30 14:00 | WAIT | WAIT | PASS | fast +1.74 ATR, depth -1.66 ATR, extended=True |
| 11 | 2024-07-02 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_DOWN |
| 12 | 2024-07-07 02:00 | WAIT | WAIT | PASS | fast +1.39 ATR, depth 1.06 ATR, extended=True |
| 13 | 2024-08-03 02:00 | WAIT | WAIT | PASS | short: fast -0.43 ATR means -fast 0.43 > 0.35 upper zone; depth 2.33 ATR; not extended |
| 14 | 2024-08-09 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_UP |
| 15 | 2024-09-13 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_DOWN |
| 16 | 2024-09-15 02:00 | WAIT | WAIT | PASS | fast +1.21 ATR, depth 1.20 ATR, extended=True |
| 17 | 2024-10-19 14:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_DOWN |
| 18 | 2024-10-24 02:00 | WAIT | WAIT | PASS | fast +1.77 ATR, depth 1.48 ATR, extended=True |
| 19 | 2024-11-24 02:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_UP |
| 20 | 2024-11-29 14:00 | WAIT | WAIT | PASS | fast +0.89 ATR, depth 1.80 ATR, extended=True |
| 21 | 2024-12-31 14:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_UP |
| 22 | 2025-01-01 14:00 | WAIT | WAIT | PASS | fast +2.37 ATR, depth -1.18 ATR, extended=True |
| 23 | 2025-01-17 14:00 | WAIT | WAIT | PASS | fast +0.66 ATR, depth 1.51 ATR, extended=True |
| 24 | 2025-02-09 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_UP |
| 25 | 2025-02-28 14:00 | WAIT | WAIT | PASS | fast +2.12 ATR, depth -1.78 ATR, extended=True |
| 26 | 2025-03-16 14:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_DOWN |
| 27 | 2025-04-02 02:00 | WAIT | WAIT | PASS | fast -1.21 ATR, depth -0.42 ATR, extended=True |
| 28 | 2025-04-21 02:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_UP |
| 29 | 2025-05-24 02:00 | WAIT | WAIT | PASS | short: -fast 0.50 > 0.35 upper zone; depth 2.17 ATR; not extended |
| 30 | 2025-05-26 14:00 | NO_TRADE | NO_TRADE | PASS | trend NEUTRAL |
| 31 | 2025-06-29 14:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_UP |
| 32 | 2025-07-19 02:00 | WAIT | WAIT | PASS | fast +0.80 ATR, depth -0.02 ATR, extended=True |
| 33 | 2025-08-02 02:00 | NO_TRADE | NO_TRADE | PASS | trend NEUTRAL |
| 34 | 2025-09-06 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_DOWN |
| 35 | 2025-09-10 02:00 | WAIT | WAIT | PASS | pullback valid (depth 1.88 ATR); close above EMA21, so short confirmation awaits reclaim; nearest support 0.03 ATR (would reject if confirmed) |
| 36 | 2025-10-11 14:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_UP |
| 37 | 2025-10-20 02:00 | WAIT | WAIT | PASS | fast -1.17 ATR, depth 1.96 ATR, extended=True |
| 38 | 2025-11-17 02:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_UP |
| 39 | 2025-11-28 02:00 | WAIT | WAIT | PASS | fast -1.37 ATR, depth -0.83 ATR, extended=True |
| 40 | 2025-12-13 02:00 | SHORT | SHORT | PASS_WITH_MANUAL_FLAG | all gates pass; fast -0.12 ATR, depth 0.52 ATR, confirmation true, no adverse sweep; room N/A (no support) — manual review |
| 41 | 2025-12-24 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_DOWN |
| 42 | 2025-12-28 14:00 | WAIT | WAIT | PASS | fast +1.47 ATR, depth 0.44 ATR, extended=True |
| 43 | 2026-01-28 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_UP |
| 44 | 2026-02-06 14:00 | WAIT | WAIT | PASS | fast +1.61 ATR, depth -0.88 ATR, extended=True |
| 45 | 2026-03-03 14:00 | WAIT | WAIT | PASS | pullback valid (depth 2.54 ATR); histogram -34.68 but RSI change +2.67, so momentum confirmation incomplete |
| 46 | 2026-03-09 02:00 | NO_TRADE | NO_TRADE | PASS | regime HIGH_VOLATILITY vs required TRENDING_DOWN |
| 47 | 2026-03-23 14:00 | WAIT | WAIT | PASS | fast +2.70 ATR, depth -0.05 ATR, extended=True |
| 48 | 2026-04-16 02:00 | NO_TRADE | NO_TRADE | PASS | trend NEUTRAL |
| 49 | 2026-05-09 14:00 | WAIT | WAIT | PASS | fast +0.53 ATR > 0.35 upper zone; depth -0.29 ATR; not extended |
| 50 | 2026-05-22 02:00 | NO_TRADE | NO_TRADE | PASS | trend NEUTRAL |
| 51 | 2026-06-05 14:00 | WAIT | WAIT | PASS | fast -2.37 ATR, depth -1.53 ATR, extended=True |
| 52 | 2026-06-26 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_DOWN |
| 53 | 2026-07-30 14:00 | NO_TRADE | NO_TRADE | PASS_WITH_MANUAL_FLAG | CHOCH_DOWN exactly 40 bars old (inclusive limit); later CHOCH_UP does not clear it — manual review |
| 54 | 2026-08-06 02:00 | WAIT | WAIT | PASS | fast -0.81 ATR, depth 0.60 ATR, extended=True |
| 55 | 2026-08-31 14:00 | WAIT | WAIT | PASS | fast -1.03 ATR, depth 0.90 ATR, extended=True |
| 56 | 2026-09-05 14:00 | NO_TRADE | NO_TRADE | PASS | trend NEUTRAL |
| 57 | 2026-09-29 02:00 | WAIT | WAIT | PASS | fast -1.40 ATR, depth 1.25 ATR, extended=True |
| 58 | 2026-10-13 02:00 | NO_TRADE | NO_TRADE | PASS | trend NEUTRAL |
| 59 | 2026-11-13 02:00 | WAIT | WAIT | PASS | fast -2.23 ATR, depth -0.28 ATR, extended=True |
| 60 | 2026-11-17 02:00 | NO_TRADE | NO_TRADE | PASS | regime UNCERTAIN vs required TRENDING_DOWN |

## 6. Observations

- **30 `NO_TRADE`:** 23 incompatible regime (mostly `UNCERTAIN` or
  `HIGH_VOLATILITY`), 6 neutral trend, 1 recent adverse `CHOCH_DOWN` (case 53).
- **29 `WAIT`:** 27 price outside the frozen pullback zone or beyond the 0.60 ATR
  extension; case 35 awaiting EMA21 reclaim; case 45 awaiting momentum
  confirmation.
- **1 candidate:** case 40 only. Its hindsight label is a small miss
  (`-0.0229%`, `0.13 ATR`). That does not by itself invalidate the rules, but the
  packet provides no evidence of a trading edge.
- **Rule coverage gap:** for a short with no support level, the room check is
  skipped. This is a frozen-rule design gap surfaced by case 40, not a threshold
  to change during review.
- **Rule-order note:** case 35 had only 0.03 ATR to support, but it correctly
  returned `WAIT` before the room gate because confirmation was incomplete. If it
  had confirmed, room would have rejected it.
- **Selection bias:** the packet intentionally oversamples candidates and WAIT
  decisions; it is not a random sample of all 2,099 evaluations.

## 7. What this does not prove

- It is **not** human approval and does not satisfy the human-review condition.
- It does not establish a positive expectancy, win rate or acceptable drawdown.
- One candidate cannot establish statistical significance.
- The dataset is the local parquet used across the project, not a live broker
  sample; its timestamps extend to late 2026. Algorithmic labels are
  close-to-close over 16 bars with no fees, funding, slippage or fills.
- No trade plan, position size or execution is enabled by this review.

## 8. Reproduction

```bash
cd backend
# Rebuild full snapshot evidence for all 60 cases (read-only)
PYTHONPATH=. .venv/Scripts/python.exe scripts/build_phase2_review_evidence.py

# Show the review without writing it
PYTHONPATH=. .venv/Scripts/python.exe scripts/review_phase2_cases.py --dry-run

# Record reviews, run aggregate_review(), and validate counts/IDs/decisions
PYTHONPATH=. .venv/Scripts/python.exe scripts/review_phase2_cases.py
```

The review tool refuses to write a completed packet if any decision disagrees
with the independently derived outcome, if any case is unreviewed, if IDs are
duplicated, or if a reviewed decision is not one of
`LONG`/`SHORT`/`WAIT`/`NO_TRADE`.

## 9. Preservation and next action

- No strategy rule, threshold, config version, dataset, case or original decision
  was changed.
- The only code change is a non-behavioral evidence-wording correction: short
  confirmations now say "lost EMA21 with weakening MACD histogram and RSI" instead
  of the long-only "reclaimed EMA21 with improving" text. Decision logic is
  unchanged.
- `strategy_validation_status` remains **PENDING**; trade plan readiness and
  execution eligibility are unchanged.
- **Next action:** a human reviewer must disposition cases 40 and 53, review the
  packet, and define (or confirm) the aggregate acceptance threshold. Only then can
  the Phase 2 gate be marked PASSED. Prepared review material, the separate
  proposed acceptance policy and versioned rule-gap proposals are in
  [`PHASE_2_GATE_CLOSURE.md`](PHASE_2_GATE_CLOSURE.md) and the blank decision
  records in [`HUMAN_APPROVAL_WORKSPACE.md`](HUMAN_APPROVAL_WORKSPACE.md).
