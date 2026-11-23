# R-001 implementation specification — no confirmed support reference

**Status:** proposal only; **not applied**
**Current strategy:** `trend_pullback` 1.0.0 / `trend-pullback-config-1.0.0`
**Proposed version if changed:** `trend-pullback-config-1.1.0`, strategy `1.1.0`
**Human decision:** `D-R001` in [`HUMAN_APPROVAL_WORKSPACE.md`](HUMAN_APPROVAL_WORKSPACE.md) — blank

## 1. Current frozen behavior

`backend/app/strategies/trend_pullback.py:874-890`:

```python
supports = [level for level in snapshot.structure.levels if level.price < close]
if supports:
    nearest = max(supports, key=lambda level: level.price)
    room = (close - nearest.price) / atr
    checks.append(CheckResult(name="room_to_support", ...))
    if room < config.min_room_atr:
        # SUPPORT_TOO_CLOSE, NO_TRADE
```

The long branch at `:839-849` mirrors this with resistances above price and
`room_to_resistance`.

**Frozen facts:**

- `min_room_atr = 1.0` (`backend/app/strategies/config.py:42`).
- The check is skipped entirely when the relevant level list is empty.
- There is no rejection, wait, warning or check result for the missing-reference case.
- Case 40 (`evl_057e128d506dde4129e10166`) is a `SHORT` with no support below
  price; literal 1.0.0 allows it.

## 2. Identified ambiguity

“No level exists” is not evidence of “enough room exists.” The frozen rule only
prevents a candidate when a *near* level proves insufficient room. It does not
require a structural target/downside reference. The same gap exists symmetrically
for longs with no resistance. Whether the omission is intended conservative
behavior, an oversight, or an undocumented “allow” is not stated in the rule text.

## 3. Alternative designs (human chooses; none is selected here)

### Option A — Reject without a reference

- If the relevant list is empty, add a check `room_reference_available=false` and
  reject with `NO_ROOM_REFERENCE`.
- Decision: `NO_TRADE`, direction `NONE`.
- Pros: safest; no unmeasured downside/upside.
- Cons: rejects trend continuations where structure has no level in the direction
  of travel; may materially reduce candidate count.

### Option B — Confirmed-swing fallback

- If no horizontal level exists, use the nearest confirmed swing low (short) or
  swing high (long) below/above entry; compute room in ATR.
- If no confirmed swing exists, reject with `NO_ROOM_REFERENCE`.
- Pros: structural, not arbitrary; uses evidence already in the snapshot.
- Cons: requires an explicit definition of “confirmed swing” and ordering; may
  choose a very distant swing that overstates room.

### Option C — Wait for a reference

- If no level exists, return `WAIT` with `ROOM_REFERENCE_MISSING`.
- Pros: preserves optionality; no candidate without evidence.
- Cons: may wait indefinitely; adds a new wait state and lifetime semantics.

### Option D — Versioned config flag

- Add `require_room_reference: bool = True`; when true, missing reference rejects
  as in A; when false, preserve 1.0.0 behavior with an explicit check note.
- Pros: explicit migration path; replayable config.
- Cons: two behaviors to test and document; a flag can be misused to bypass the
  safeguard.

### Option E — No change

- Document that a missing level permits the candidate and disposition case 40 as
  intentional under `D-40 A`.
- Pros: no behavior change.
- Cons: ambiguity persists; the strategy still cannot demonstrate room.

## 4. Expected behavior changes per option

| Situation | 1.0.0 | A | B | C | D (default true) |
|---|---|---|---|---|---|
| Support 1.4 ATR below, short | PASS room | PASS | PASS | PASS | PASS |
| Support 0.8 ATR below, short | `SUPPORT_TOO_CLOSE` | same | same | same | same |
| No support below, short | **candidate allowed** | `NO_ROOM_REFERENCE` | swing room or reject | `WAIT` | reject |
| No resistance above, long | **candidate allowed** | `NO_ROOM_REFERENCE` | swing room or reject | `WAIT` | reject |
| Missing snapshot levels | candidate allowed | reject | reject if no swing | wait | reject |

No option changes risk authority, position sizing, plan eligibility, the strategy
gate or execution. A `NO_TRADE`/`WAIT` result is not a trade instruction.

## 5. Edge cases

- Empty `structure.levels` versus levels only on the wrong side of price.
- A level exactly at the reference close (strict `<`/`>` excludes it).
- Duplicate levels at the same price; deterministic ordering required.
- Multiple candidate swings; nearest confirmed swing must be selected by a
  documented rule, not dict order.
- `atr <= 0` or missing ATR; the existing contract requires valid ATR, but the new
  branch must not divide by zero.
- Long/short symmetry; a rule that only fixes shorts is incomplete.
- Stale snapshot or unsupported symbol/timeframe; existing gates still run first.
- Replay must produce the same decision for the same config version and snapshot.

## 6. Required regression tests

At minimum:

1. Case 40 replay under the chosen option (expected decision and reason code).
2. Short with no support: chosen behavior.
3. Long with no resistance: symmetric behavior.
4. Nearest support exactly `1.0 ATR` away: passes room check.
5. Nearest support `0.99 ATR` away: `SUPPORT_TOO_CLOSE`.
6. Confirmed-swing fallback (if B): nearest swing selected; no swing rejects.
7. Duplicate levels: deterministic nearest selection.
8. Missing/zero ATR: no divide-by-zero; explicit missing-input result.
9. All existing trend-pullback tests remain green.
10. A new case packet is generated from the same frozen dataset and reviewed; the
    1.0.0 packet is not edited in place.

## 7. Versioning and approval impact

- Any behavior change requires a new config version and strategy version.
- `STRATEGY_VERSION`/`CONFIG_VERSION` must be reported in every evaluation and plan.
- The 60-case packet must be regenerated; old signatures are invalid.
- A new independent human review is required.
- If Option E is chosen, no code change and no packet regeneration; case 40 must be
  explicitly dispositioned as intentional.
- This document does not select an option or apply a rule.
