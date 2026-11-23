# Phase 2 gate closure — human-review packets and proposed policies

**Date:** 2026-11-23
**Strategy:** `trend_pullback` 1.0.0
**Frozen config:** `trend-pullback-config-1.0.0`
**Gate status:** **PENDING** — this document prepares review material; it does not approve anything
**Automated review:** 60/60 reviewed, 58 PASS, 2 PASS_WITH_MANUAL_FLAG, 0 disagreements
**Human review:** 0/60 recorded
**Production/planning effect:** none; execution remains disabled

**Review workspace:** [`HUMAN_APPROVAL_WORKSPACE.md`](HUMAN_APPROVAL_WORKSPACE.md)  
**Policy status:** [`PHASE_2_ACCEPTANCE_POLICY.md`](PHASE_2_ACCEPTANCE_POLICY.md) (`PROPOSED_NOT_APPLIED`)  
**Rule specs:** [`R-001_NO_SUPPORT_REFERENCE_SPEC.md`](R-001_NO_SUPPORT_REFERENCE_SPEC.md), [`R-002_ADVERSE_CHOCH_SPEC.md`](R-002_ADVERSE_CHOCH_SPEC.md)

This document does **not** decide cases 40 or 53, does not introduce an aggregate
threshold, and does not change a frozen rule. The two case packets give a human
reviewer the exact inputs and the literal rule interpretation, then list the
questions that require a human disposition.

---

## 1. Case 40 — SHORT with no support level

**Identity**

| Field | Value |
|---|---|
| Case | 40 |
| Candle | 2025-12-13 02:00 UTC |
| Evaluation ID | `evl_057e128d506dde4129e10166` |
| Snapshot ID | `mkt_317c6d3f8621e049cd048508c9b6` |
| Recorded decision | `SHORT` |
| Automated reviewed decision | `SHORT` |
| Review result | `PASS_WITH_MANUAL_FLAG` |
| Evidence | `PHASE_2_REVIEW_EVIDENCE.json#case-40` |

**Reconstructed inputs**

- Reference close: `90,290.45`; ATR14: `158.796`.
- Trend: `STRONG_BEARISH`; structure: `DOWNTREND`; regime: `TRENDING_DOWN`;
  volatility: `LOW`.
- Fast EMA distance: `-0.116 ATR`; slow EMA distance: `-1.959 ATR`;
  short retracement depth: `0.524 ATR`.
- RSI14: `47.3441`; MACD histogram change: `-17.9941`; ROC: `-0.0774%`.
- Closed-bar confirmation: passed.
- Confirmed adverse sweep within `0.75 ATR` / 8 bars: none.
- Nearest resistance: `90,376.23`, `0.540 ATR` away.
- **Nearest support: `null`.** The listed support levels are all above the
  reference price, so the implementation finds no support below price.

**Frozen-rule interpretation**

The implementation computes the room check only when a level of the relevant kind
exists:

```python
# short branch, app/strategies/trend_pullback.py
supports = [level for level in snapshot.structure.levels if level.price < close]
if supports:
    nearest = max(supports, key=lambda level: level.price)
    room = (close - nearest.price) / atr
    ...
```

There is no `else` branch that rejects, waits, or flags a missing support. Under the
literal frozen code, a missing support leaves `room_to_support` **not applicable**
and does not block the short. The recorded `SHORT` is therefore valid conformance
to the implemented 1.0.0 rule.

The written description only requires “room to support ≥ 1.0 ATR” for a short; it
does not say what to do when no support exists. That is a **rule-coverage gap**, not
a case-evidence gap: all inputs needed to evaluate the rest of the decision are
present.

**What is not in dispute**

- Every applicable gate passed under the frozen thresholds.
- The decision was independently re-derived from the reconstructed snapshot as
  `SHORT`; it was not copied from the recorded decision.
- The hindsight label is a small miss (`-0.0229%`, `0.13 ATR` over the label
  horizon). It is a measurement, not a review criterion and not trade PnL.

**Questions for the human reviewer**

1. Is the intended meaning “if a support exists, require ≥ 1.0 ATR; if none exists,
   the short may proceed”?
2. Or is a missing support intended to mean “cannot prove room” and therefore
   `NO_TRADE`/`WAIT`?
3. If the latter, is the correct fallback the nearest confirmed swing low, or a new
   rejection code for an absent structural level?
4. Does the answer apply only to shorts, or symmetrically to longs with no
   resistance?

**Possible dispositions (reviewer chooses one; none is applied here)**

- **A. Valid as implemented:** mark case 40 PASS; the literal rule is the intended
  behavior. No rule change.
- **B. Valid but under-specified:** mark case 40 PASS_WITH_MANUAL_FLAG and require a
  versioned rule clarification before the next packet; do not retroactively change
  this decision.
- **C. Invalid under intended policy:** mark case 40 FAIL; the frozen rule needs a
  version bump and the packet must be regenerated after approval.
- **D. Requires clarification:** keep the case unresolved and the gate PENDING.

No option above has been selected by the automated agent.

---

## 2. Case 53 — adverse CHOCH exactly on the lookback boundary

**Identity**

| Field | Value |
|---|---|
| Case | 53 |
| Candle | 2026-07-30 14:00 UTC |
| Evaluation ID | `evl_f0351448b9ba1e002f788686` |
| Snapshot ID | `mkt_cce30eee6d3812742ca5f3269ec5` |
| Recorded decision | `NO_TRADE` |
| Automated reviewed decision | `NO_TRADE` |
| Review result | `PASS_WITH_MANUAL_FLAG` |
| Evidence | `PHASE_2_REVIEW_EVIDENCE.json#case-53` |

**Reconstructed inputs**

- Reference close: `64,733.99`; ATR14: `156.833`.
- Trend: `STRONG_BULLISH`; structure: `UPTREND`; regime: `TRENDING_UP`;
  volatility: `NORMAL`.
- The snapshot timestamp (`data_as_of`) is 14:15 UTC.
- Blocking event: `CHOCH_DOWN` at 04:15 UTC, `age_bars = 40.0`.
- Frozen lookback: `structure_lookback_bars = 40`.
- Later opposite events: `CHOCH_UP` at 08:15 (24 bars old) and 08:30 (23 bars old).
- Rejection code: `STRUCTURE_INVALIDATED`.

**Frozen-rule interpretation**

```python
def _age_bars(snapshot, at):
    return (snapshot.data_as_of - at).total_seconds() / 900

def _recent_events(snapshot, event_type, bars):
    return [
        event for event in snapshot.structure.events
        if event.type is event_type and 0 <= _age_bars(snapshot, event.candle_time) <= bars
    ]
```

The boundary is **inclusive** (`<= bars`). `40.0 <= 40` is true, so the 04:15
`CHOCH_DOWN` is inside the window and blocks the long. The result conforms to the
literal 1.0.0 rule.

The rule searches only for the adverse event type. It has **no code that removes,
supersedes or expires an adverse CHoCH when a later opposite CHoCH occurs**. The
08:15 and 08:30 `CHOCH_UP` events are irrelevant to this check. Thus the
implementation intentionally preserves the old adverse event until it ages out at
more than 40 bars; whether that preservation is the intended market-structure
semantics is not documented.

**Questions for the human reviewer**

1. Is the 40-bar lookback inclusive by design, or should the boundary be strictly
   `< 40`? (The implementation is inclusive; changing it is a behavior change.)
2. Should a later opposite CHoCH clear the old adverse event immediately, or only
   after a confirming break of structure / higher high?
3. Should clearing require both a CHoCH and a structural BOS, or a close beyond the
   prior swing?
4. Is the current behavior intentionally conservative (“one adverse CHoCH poisons
   the window for 40 bars”), or an unintended consequence of the event-list filter?
5. If changed, should case 53 be re-reviewed under the new version rather than
   retroactively marked PASS/FAIL under 1.0.0?

**Possible dispositions (reviewer chooses one; none is applied here)**

- **A. Valid as implemented:** mark case 53 PASS; inclusive 40-bar preservation is
  intended.
- **B. Valid but under-specified:** mark PASS_WITH_MANUAL_FLAG and require a
  versioned rule clarification; do not alter this packet.
- **C. Invalid under intended policy:** mark FAIL; propose a version bump and
  regenerate/re-review the packet after approval.
- **D. Requires clarification:** keep unresolved and the gate PENDING.

No option above has been selected by the automated agent.

---

## 3. Aggregate acceptance criteria — inspection result

The repository **does not define a numeric aggregate acceptance threshold**.

Evidence:

- `IMPLEMENTATION_TASKS.md` P2-07 requires “60 labelled snapshots … report exact
  confusion matrix” but states no minimum accuracy, agreement rate or candidate
  count.
- `PHASE_2_RESULTS.md` §10 and `PHASE_2_EVALUATION.md` §3 explicitly record that the
  documented gate requires independent human review and has no aggregate
  minimum-agreement or candidate-performance threshold.
- `aggregate_review()` counts reviewed cases and sets `COMPLETE` at 60; it does not
  approve them and has no threshold parameter.

Because no threshold exists, **none is applied**. The policy below is a proposal
only, kept separate from the frozen criteria.

### 3.1 Proposed acceptance policy `phase2-acceptance-proposal-1.0`

**Gate type.** This is a **rule-conformance gate**, not a profitability or
expectancy gate. Passing means the frozen rules and reasons are reproduced and
independently accepted, not that the strategy is profitable.

**Required review coverage.**

- 60/60 cases must have a named human reviewer, review timestamp and disposition.
- The reviewer must see the frozen rule version and the evidence packet hash.
- Automated reviews cannot be counted as human reviews.
- Any unresolved `NEEDS_CLARIFICATION` or manual flag blocks acceptance.

**Disposition accounting.**

- Every case resolves to `PASS` or `FAIL` after human review; flags cannot remain
  open at gate closure.
- A `FAIL` means the decision or the decisive reason contradicts the frozen rules.
  A `PASS` means both the decision and the recorded reason are accepted.
- The packet must report the exact 60-row confusion matrix and every FAIL with its
  rule citation.

**Proposed numeric rule.**

- **0 FAIL** across all 60 cases for PASS.
- If any case FAILs: gate = **FAILED**, fix the rule or the case evidence under a
  new version, regenerate the packet, and re-review. Do not waive individual cases.
- A single candidate cannot satisfy a performance gate; **no minimum win rate,
  expectancy or hit rate is proposed for this packet**.

**Why 0 FAIL rather than 58/60 or 59/60.**

The 60 cases are a deterministic conformance sample, not a random performance
sample. A single reproducible contradiction is a rule bug; averaging it against 59
agreements would hide a deterministic defect. The packet intentionally contains
only one candidate, so a “95% pass rate” would be statistically meaningless and
would create false confidence.

**Operational controls.**

- Two-key closure: independent reviewer disposition + strategy owner approval,
  both recorded.
- Freeze the packet SHA-256 at review time; any case, rule or dataset change
  invalidates the signature.
- Keep `strategy_validation_status = PENDING` until both keys are present.
- A PASS does **not** enable trade plans, position sizing or execution; a separate
  performance/risk gate must pass first.

**Statistical reasoning.**

With one candidate, the 95% confidence interval for a hit rate spans almost the
entire [0, 1] range. Conformance accuracy across 60 mostly non-candidate decisions
also says little about candidate expectancy. The packet can detect rule
contradictions; it cannot establish an edge. Reporting a performance threshold here
would be a category error.

**Status:** `PROPOSED_NOT_APPLIED`. The current gate remains PENDING and no threshold
has been introduced into code or configuration.

---

## 4. Versioned rule-change proposals (not applied)

Both proposals are behavior changes. Under the repository’s versioning policy they
require a new strategy/config version, new tests, a regenerated evidence packet and
a fresh human review. They must **not** be applied to the frozen 1.0.0 packet.

### R-001 — Short candidates with no identifiable support

**Current behavior.** The short branch checks room only if at least one support
level is below price. If none exists, the check is omitted and the short can
proceed (case 40).

**Risk.** “No support exists” is not the same as “sufficient room exists.” The
strategy cannot demonstrate a structural target/downside reference, so the
room safeguard silently disappears. The long branch has the symmetric issue when
no resistance exists.

**Options**

| Option | Behavior | Trade-off |
|---|---|---|
| A. Reject | `NO_TRADE` with `NO_ROOM_REFERENCE` when no relevant level exists | Safest; may reject valid trend continuations |
| B. Swing fallback | Use nearest confirmed swing low (short) / high (long) as the room reference; reject if none | More structural; requires swing confirmation semantics |
| C. Wait | `WAIT` until a level forms | Preserves optionality; may never resolve |
| D. Config flag | `require_room_reference: true` default; explicit opt-out | Backward-compatible only with a version bump; risk of misuse |

**Proposed version:** `trend-pullback-config-1.1.0`, strategy `1.1.0` (minor
behavior change). **Proposed default:** option A or B only after human decision.
**Required tests:** case 40 replay; short with no support; long with no resistance;
nearest support exactly 1.0 ATR; nearest support below entry; missing-level
evidence shape. **Packet impact:** all 60 cases must be re-run; case 40's disposition
must not be edited in place.

### R-002 — Adverse CHoCH expiry and opposite-structure invalidation

**Current behavior.** `_recent_events` includes adverse CHoCH events with
`0 <= age <= 40`; a later opposite CHoCH does not clear the adverse event. Case 53
is blocked at exactly 40.0 bars.

**Risk.** A stale adverse event can suppress a valid setup after structure has
already repaired; conversely, clearing too early can enter before confirmation. The
current behavior is conservative but under-documented.

**Options**

| Option | Behavior | Trade-off |
|---|---|---|
| A. Keep fixed window | Document inclusive 40-bar expiry; no clearing | No behavior change; may be overly restrictive |
| B. Clear on opposite CHoCH | Remove adverse event when a later opposite CHoCH prints | Responsive; may clear on noise |
| C. Clear on opposite BOS | Require a later opposite break of structure | Stronger confirmation; slower |
| D. State machine | Track structure regime; adverse event valid until state realigns + BOS | Most explicit; largest implementation change |
| E. Change boundary | Strict `< 40` instead of `<= 40` | Tiny behavior change; does not address clearing semantics |

**Proposed version:** `trend-pullback-config-1.1.0`, strategy `1.1.0` if any option
other than A is chosen. **Required tests:** case 53; age 39/40/41; adverse CHoCH
followed by opposite CHoCH with and without BOS; opposite event older than adverse
event; duplicate-event handling. **Packet impact:** full regeneration and human
re-review; no in-place edits.

### Versioning and approval sequence

1. Human reviewer dispositions cases 40 and 53 and confirms or rejects the proposed
   aggregate policy.
2. Strategy owner chooses R-001/R-002 options (or rejects them).
3. If changed: bump strategy/config versions, add deterministic tests, update the
   rule documentation.
4. Regenerate all 60 case snapshots and the evidence packet under the new version.
5. Obtain a new independent human review; do not reuse this packet’s signatures.
6. Only then consider Phase 2 acceptance. Trade plans and execution remain disabled
   until a separate performance/risk gate passes.

---

## 5. Current gate state (unchanged)

```text
reviewed_cases          60
human_reviews            0
PASS                    58
PASS_WITH_MANUAL_FLAG    2
FAIL                     0
open manual flags        2   (cases 40, 53)
aggregate threshold      none
gate status              COMPLETE (review packet only)
acceptance status        PENDING
strategy_validation      PENDING
```

**Packet integrity at review time**

```text
PHASE_2_EVALUATION.json        a5c38f02c8bd1b5c1ac880a0a4419f8e5bd871423e484a84e3e892792bda08c5
PHASE_2_REVIEW_EVIDENCE.json   0b324aa6783f06ccbea958a867fc857e12ed9c371fc0c1e3d752d65681e1d233
PHASE_2_REVIEW_RESULTS.json    24347093509158782adb9d4b8f5e3571d684afbbc3ae6f9d34947155d63ce0c0
```

No case was decided on behalf of a human. No frozen rule, threshold, dataset, case
or original decision was changed. No packet was regenerated. No production planning
or execution behavior was enabled.
