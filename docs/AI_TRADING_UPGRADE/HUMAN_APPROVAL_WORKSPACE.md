# Phase 2 human approval workspace

**Date prepared:** 2026-11-23
**Prepared by:** automated coding agent (not a human reviewer)
**Purpose:** collect auditable human decisions. This document does not make them.
**Strategy:** `trend_pullback` 1.0.0
**Frozen config:** `trend-pullback-config-1.0.0`
**Current gate:** `PENDING`
**Current acceptance:** `PENDING`
**Automated review:** 60/60 (LLM agent); **human review: 0/60**
**Execution:** `DISABLED`; position size `NOT_CALCULATED`

> **Do not treat this file as approval.** Every `HUMAN DECISION`, reviewer,
> timestamp and approval field below is intentionally blank. The automated review
> is not a human review, even when its result is `PASS`.

## 0. Evidence and packet integrity

| Artifact | Reference | SHA-256 |
|---|---|---|
| Evaluation | `docs/AI_TRADING_UPGRADE/PHASE_2_EVALUATION.json` | `a5c38f02c8bd1b5c1ac880a0a4419f8e5bd871423e484a84e3e892792bda08c5` |
| Review evidence | `docs/AI_TRADING_UPGRADE/PHASE_2_REVIEW_EVIDENCE.json` | `0b324aa6783f06ccbea958a867fc857e12ed9c371fc0c1e3d752d65681e1d233` |
| Review results | `docs/AI_TRADING_UPGRADE/PHASE_2_REVIEW_RESULTS.json` | `24347093509158782adb9d4b8f5e3571d684afbbc3ae6f9d34947155d63ce0c0` |
| Gate-closure packet | `docs/AI_TRADING_UPGRADE/PHASE_2_GATE_CLOSURE.md` | see file |
| Frozen rules | `backend/app/strategies/trend_pullback.py` | rule source |
| Frozen config | `backend/app/strategies/config.py` | config source |

The packet hashes above are the review-time hashes. Any rule, case, threshold or
dataset change invalidates them and requires a new packet and new human review.

---

# Decision D-40 — Case 40 disposition

## Identity

| Field | Value |
|---|---|
| Decision ID | `D-40` |
| Case | 40 |
| Candle | 2025-12-13 02:00 UTC |
| Evaluation ID | `evl_057e128d506dde4129e10166` |
| Snapshot ID | `mkt_317c6d3f8621e049cd048508c9b6` |
| Automated review result | `PASS_WITH_MANUAL_FLAG` |
| Evidence | `PHASE_2_REVIEW_EVIDENCE.json#case-40`; `PHASE_2_REVIEW_RESULTS.json` case 40 |
| Source references | `backend/app/strategies/trend_pullback.py:874-890`; `backend/app/strategies/config.py:42` |

## Relevant evidence

- Recorded and independently re-derived decision: **`SHORT`**.
- Reference close: `90,290.45`; ATR14: `158.796`.
- Trend `STRONG_BEARISH`; structure `DOWNTREND`; regime `TRENDING_DOWN`;
  volatility `LOW`.
- Fast EMA distance `-0.116 ATR`; slow EMA distance `-1.959 ATR`; short
  retracement depth `0.524 ATR`.
- RSI14 `47.3441`; MACD histogram change `-17.9941`; ROC `-0.0774%`.
- Closed-bar confirmation passed.
- No confirmed adverse sweep within `0.75 ATR` / 8 bars.
- Nearest resistance `90,376.23`, `0.540 ATR` away.
- **Nearest support: `null`.** All listed supports are above price.
- Hindsight label: small miss, `-0.0229%` / `0.13 ATR`; this is not a review
  criterion or PnL.
- Frozen code computes the room check only `if supports:`. There is no `else`
  rejection. The literal 1.0.0 rule therefore permits the short; the ambiguity is
  whether that omission is intended.

## Available choices

| Choice | Meaning | Consequence |
|---|---|---|
| **A. Valid as implemented** | Mark case 40 `PASS`; missing support intentionally permits the short. | Gate can count the case as conforming. The unguarded room check remains part of 1.0.0 and is documented as intentional. No rule version change. |
| **B. Valid but under-specified** | Mark `PASS_WITH_MANUAL_FLAG`; require a versioned clarification before the next packet; do not rewrite this decision. | Preserves the literal conformance finding while recording the policy gap. Gate remains PENDING until R-001 is decided and the flag is closed under the approved policy. |
| **C. Invalid under intended policy** | Mark `FAIL`; the frozen rule needs a version bump and packet regeneration. | Gate becomes `FAILED` under the proposed 0-FAIL rule. Case 40 cannot be used as a passing case until a new version is implemented and re-reviewed. |
| **D. Requires clarification** | Keep unresolved; no PASS/FAIL disposition now. | Gate remains PENDING by definition. No rule or packet changes. The reviewer must obtain the strategy owner's intended semantics before closure. |

**Recommendation (not a decision):** **B** — record literal conformance, but do not
pretend the missing-room gap is resolved; decide R-001 before gate closure. This is
a recommendation only. The human decision field below is blank.

## Human record

- Human decision (write one choice, A/B/C/D, and rationale):
  `____________________________________________________________________________`
- Reviewer identity: `________________________________________________________`
- Decision timestamp (UTC): `_______________________________________________`
- Approval status: `PENDING_HUMAN_REVIEW`
- Conditions / follow-up: `__________________________________________________`

---

# Decision D-53 — Case 53 disposition

## Identity

| Field | Value |
|---|---|
| Decision ID | `D-53` |
| Case | 53 |
| Candle | 2026-07-30 14:00 UTC |
| Evaluation ID | `evl_f0351448b9ba1e002f788686` |
| Snapshot ID | `mkt_cce30eee6d3812742ca5f3269ec5` |
| Automated review result | `PASS_WITH_MANUAL_FLAG` |
| Evidence | `PHASE_2_REVIEW_EVIDENCE.json#case-53`; `PHASE_2_REVIEW_RESULTS.json` case 53 |
| Source references | `backend/app/strategies/trend_pullback.py:95-104`, `:499-505`; `backend/app/strategies/config.py:45` |

## Relevant evidence

- Recorded and independently re-derived decision: **`NO_TRADE`**.
- Reference close `64,733.99`; ATR14 `156.833`.
- Trend `STRONG_BULLISH`; structure `UPTREND`; regime `TRENDING_UP`;
  volatility `NORMAL`.
- Snapshot `data_as_of`: 14:15 UTC.
- Blocking event: `CHOCH_DOWN` at 04:15 UTC, `age_bars = 40.0`.
- Frozen lookback: `structure_lookback_bars = 40`.
- Later opposite events: `CHOCH_UP` at 08:15 (24 bars) and 08:30 (23 bars).
- Rejection code: `STRUCTURE_INVALIDATED`.
- Frozen `_recent_events` uses inclusive `0 <= age <= bars`, so `40.0 <= 40`
  blocks the long. The code filters only adverse event types and has no
  opposite-structure clearing logic. Literal conformance is established; intended
  expiry semantics are not.

## Available choices

| Choice | Meaning | Consequence |
|---|---|---|
| **A. Valid as implemented** | Mark `PASS`; inclusive 40-bar preservation is intended. | Case 53 counts as conforming. The conservative “one adverse CHoCH blocks for 40 bars” behavior remains documented as intentional. No version bump. |
| **B. Valid but under-specified** | Mark `PASS_WITH_MANUAL_FLAG`; require a versioned rule clarification; do not alter this packet. | Preserves literal conformance and the boundary finding. Gate remains PENDING until R-002 is decided under the approved policy. |
| **C. Invalid under intended policy** | Mark `FAIL`; propose a version bump and regenerate/re-review the packet. | Gate becomes FAILED under 0-FAIL. The 1.0.0 decision is not retroactively changed; a new version and new review are required. |
| **D. Requires clarification** | Keep unresolved; no PASS/FAIL disposition now. | Gate remains PENDING. No rule or packet changes until the strategy owner defines expiry/invalidation semantics. |

**Recommendation (not a decision):** **B** — literal conformance is clear, but the
expiry semantics and the exact-40 boundary must be made explicit before closure.
This is a recommendation only. The human decision field below is blank.

## Human record

- Human decision (write one choice, A/B/C/D, and rationale):
  `____________________________________________________________________________`
- Reviewer identity: `________________________________________________________`
- Decision timestamp (UTC): `_______________________________________________`
- Approval status: `PENDING_HUMAN_REVIEW`
- Conditions / follow-up: `__________________________________________________`

---

# Decision D-AGG-01 — Proposed aggregate policy

## Identity

| Field | Value |
|---|---|
| Decision ID | `D-AGG-01` |
| Proposal | `phase2-acceptance-proposal-1.0` |
| Current status | `PROPOSED_NOT_APPLIED` |
| Source | `PHASE_2_GATE_CLOSURE.md` §3.1 |

## Relevant evidence

- The repository defines **no numeric aggregate acceptance threshold**.
- `aggregate_review()` counts 60 reviews and sets `COMPLETE`; it does not approve.
- Automated review is 60/60: 58 `PASS`, 2 `PASS_WITH_MANUAL_FLAG`, 0 `FAIL`.
- Human review is **0/60**.
- The packet is a deterministic conformance sample, not a profitability sample;
  one candidate cannot support a win-rate or expectancy gate.
- The proposal is a **rule-conformance** policy: 60/60 named human reviews, every
  flag resolved, **0 FAIL**, two-key closure, frozen packet hash, no performance
  claim, execution still disabled.

## Available choices

| Choice | Meaning | Consequence |
|---|---|---|
| **A. Accept as proposed** | Adopt `phase2-acceptance-proposal-1.0` as the Phase 2 closure policy. | Still not a gate PASS: 60 human reviews, both flags closed, and two-key approval are required. No frozen rule changes. |
| **B. Accept with amendments** | Adopt only after recording specific changes (e.g., treatment of manual flags). | The amended policy must be versioned and re-circulated; the current proposal remains PROPOSED until then. |
| **C. Reject** | Keep the existing undocumented gate and make no aggregate policy. | Gate remains PENDING with no closure rule; this is not an approval. |
| **D. Defer** | Take no policy decision now. | Gate remains PENDING; cases 40/53 still need disposition. |

**Recommendation (not a decision):** **A**, because it prevents automated reviews
from being counted as approval and avoids inventing a performance threshold from a
single candidate. This is a recommendation only; the human decision field is blank.

## Human record

- Human decision (write one choice, A/B/C/D, and rationale):
  `____________________________________________________________________________`
- Reviewer identity: `________________________________________________________`
- Decision timestamp (UTC): `_______________________________________________`
- Approval status: `PENDING_HUMAN_REVIEW`
- Two-key owner approval (separate person): `_________________________________`
- Conditions / follow-up: `__________________________________________________`

---

# Decision D-R001 — R-001 implementation choice

## Identity

| Field | Value |
|---|---|
| Decision ID | `D-R001` |
| Proposal | `R-001` — short candidate with no confirmed support reference |
| Current status | not applied; frozen 1.0.0 behavior unchanged |
| Source | `PHASE_2_GATE_CLOSURE.md` §4; `backend/app/strategies/trend_pullback.py:874-890` |

## Relevant evidence

- The short branch computes `supports = [level for level in snapshot.structure.levels if level.price < close]`.
- `if supports:` guards the entire room check; no `else` rejects or waits.
- Case 40 has no support below price and still produced `SHORT`.
- `min_room_atr = 1.0` (`config.py:42`); the check disappears when no reference
  exists, which is not the same as proving sufficient room.

## Available choices

| Choice | Meaning | Consequence |
|---|---|---|
| **A. Reject** | `NO_TRADE` with a new `NO_ROOM_REFERENCE` reason when no relevant level exists. | Safest; may reject valid trend continuations. Requires new reason code, tests, version bump and packet regeneration. |
| **B. Confirmed-swing fallback** | Use the nearest confirmed swing low/high; reject if none exists. | More structural; requires explicit swing-confirmation semantics and tests. Version bump and full re-review. |
| **C. Wait** | `WAIT` until a level forms. | Preserves optionality; may remain unresolved indefinitely. Version bump and tests. |
| **D. Config flag** | Add `require_room_reference`, default true, with explicit opt-out. | Backward-compatible only under a new config version; misuse risk. Tests for both settings and packet regeneration. |
| **E. No change** | Document that missing levels permit the candidate. | No code change, but the ambiguity remains and case 40 must be dispositioned as intentional (A under D-40). |

**Recommendation (not a decision):** **B** — a confirmed-swing fallback preserves
structural room without automatically rejecting every continuation. Option A is the
more conservative alternative. This is a recommendation only; the human decision
field is blank.

## Human record

- Human decision (write one choice, A/B/C/D/E, and rationale):
  `____________________________________________________________________________`
- Reviewer identity: `________________________________________________________`
- Decision timestamp (UTC): `_______________________________________________`
- Approval status: `PENDING_HUMAN_REVIEW`
- Required version if changed: `____________________________________________`
- Conditions / follow-up: `__________________________________________________`

---

# Decision D-R002 — R-002 implementation choice

## Identity

| Field | Value |
|---|---|
| Decision ID | `D-R002` |
| Proposal | `R-002` — adverse CHoCH expiry and opposite-structure invalidation |
| Current status | not applied; frozen 1.0.0 behavior unchanged |
| Source | `PHASE_2_GATE_CLOSURE.md` §4; `backend/app/strategies/trend_pullback.py:95-104`, `:499-505` |

## Relevant evidence

- `_recent_events` includes events with `0 <= age_bars <= bars` (inclusive).
- `structure_lookback_bars` defaults to 40 (`config.py:45`).
- Case 53's blocking `CHOCH_DOWN` is exactly `40.0` bars old.
- Later `CHOCH_UP` events do not clear it; no opposite-invalidation code exists.
- Changing the boundary or clearing behavior is a strategy behavior change and
  requires a version bump and new packet.

## Available choices

| Choice | Meaning | Consequence |
|---|---|---|
| **A. Keep fixed window** | Document inclusive 40-bar expiry; no clearing. | No behavior change; conservative, may suppress repaired structures. Case 53 can be accepted as intentional under D-53 A. |
| **B. Clear on opposite CHoCH** | Remove the adverse event when a later opposite CHoCH prints. | Responsive; may clear on noise. Requires tests, version bump, full re-review. |
| **C. Clear on opposite BOS** | Require a later opposite break of structure. | Stronger confirmation; slower. Requires tests, version bump, full re-review. |
| **D. State machine** | Track structure regime; adverse event valid until state realigns plus BOS. | Most explicit; largest implementation and test change. |
| **E. Strict boundary** | Change `<= 40` to `< 40`. | Small behavior change at exactly 40 bars; does not address clearing semantics. Case 53 would no longer be blocked by this event. |

**Recommendation (not a decision):** **A** — keep the frozen behavior for 1.0.0 and
resolve the semantic documentation before any version bump. If a change is desired,
**C** is the safer of the clearing options because it requires a BOS. This is a
recommendation only; the human decision field is blank.

## Human record

- Human decision (write one choice, A/B/C/D/E, and rationale):
  `____________________________________________________________________________`
- Reviewer identity: `________________________________________________________`
- Decision timestamp (UTC): `_______________________________________________`
- Approval status: `PENDING_HUMAN_REVIEW`
- Required version if changed: `____________________________________________`
- Conditions / follow-up: `__________________________________________________`

---

# Closure rules (not yet satisfied)

1. **60/60 human reviews.** Automated reviews never count. Every case needs a named
   reviewer, timestamp and disposition.
2. **Both flags resolved.** Cases 40 and 53 cannot remain `PASS_WITH_MANUAL_FLAG`
   at gate closure; the chosen dispositions and any conditions must be recorded.
3. **Two-key closure.** Independent reviewer disposition plus strategy-owner
   approval, both recorded. One person cannot supply both keys.
4. **0 FAIL.** A reproducible rule contradiction fails the gate; do not average it
   away or waive a case.
5. **Packet hash freeze.** Any rule, case, threshold or dataset change requires a
   new packet and a new review.
6. **No performance claim.** Passing this gate means rule conformance, not edge,
   profitability or permission to trade.
7. **Execution stays disabled.** `strategy_validation_status` remains `PENDING` and
   no plan is executable after this workspace is completed without the separate
   approvals above.

## Current status

```text
automated_reviews        60/60 (LLM; not human)
human_reviews             0/60
PASS                     58
PASS_WITH_MANUAL_FLAG     2
FAIL                      0
aggregate policy         PROPOSED_NOT_APPLIED
acceptance               PENDING
strategy_validation      PENDING
execution                DISABLED
```
