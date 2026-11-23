# Phase 2 acceptance policy — proposal status and closure rules

**Proposal:** `phase2-acceptance-proposal-1.0`
**Status:** **`PROPOSED_NOT_APPLIED`**
**Current gate:** `PENDING`
**Current acceptance:** `PENDING`
**Execution:** `DISABLED`

This policy is a proposal for human approval. It has not been inserted into code,
configuration or the gate evaluator. No acceptance threshold has been silently
applied. The detailed decision record is in
[`HUMAN_APPROVAL_WORKSPACE.md`](HUMAN_APPROVAL_WORKSPACE.md); the original packet is
[`PHASE_2_GATE_CLOSURE.md`](PHASE_2_GATE_CLOSURE.md).

## Why a proposal was needed

The repository requires independent human review but defines no numeric aggregate
acceptance threshold. The existing `aggregate_review()` helper counts reviews and
sets `COMPLETE` at 60; it does **not** approve the strategy. Treating
“60/60 automated reviews” as acceptance would fabricate human approval, so this
separate proposal records the missing closure rule without changing the gate.

## The 60/60 human-review requirement

- All **60/60** cases require a named human reviewer, a review timestamp and a
  disposition.
- The automated LLM review is **0/60 human reviews** and can never be counted as one,
  even when its result is `PASS`.
- A human must see the frozen rule version and packet hash used for the decision.
- Every manual flag must be explicitly resolved before closure; a flag cannot be
  left open and called a pass.
- A single reproducible `FAIL` fails the gate. A deterministic contradiction is not
  averaged against 59 agreements.

## The two-key closure requirement

Closure requires **two distinct recorded approvals**:

1. **Reviewer key:** the independent human reviewer's per-case dispositions and
   overall recommendation.
2. **Strategy-owner key:** the owner's explicit acceptance of the packet and policy.

One person cannot supply both keys. The keys must reference the same frozen packet
hashes and the same policy version. Any change to a rule, case, threshold, dataset
or packet invalidates both keys and requires a new review.

## What this policy does and does not mean

- It is a **rule-conformance** gate, not a profitability or expectancy gate.
- It does not enable trade plans, position sizing or execution.
- It does not change `strategy_validation_status`; that remains `PENDING` until all
  conditions are actually satisfied.
- It does not claim PATRON edge. PATRON remains `NO_DEMONSTRATED_EDGE`.
- WAIT and NO_TRADE remain valid outcomes.

## Current state

```text
proposal status          PROPOSED_NOT_APPLIED
automated reviews        60/60 (LLM; not human)
human reviews             0/60
PASS                     58
PASS_WITH_MANUAL_FLAG     2
FAIL                      0
open flags               cases 40, 53
acceptance               PENDING
strategy_validation      PENDING
execution                DISABLED
```

No human decision, reviewer identity, timestamp or approval is populated by this
document.
