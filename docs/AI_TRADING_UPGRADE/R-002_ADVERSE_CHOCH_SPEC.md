# R-002 implementation specification — adverse CHoCH expiry and opposite invalidation

**Status:** proposal only; **not applied**
**Current strategy:** `trend_pullback` 1.0.0 / `trend-pullback-config-1.0.0`
**Proposed version if changed:** `trend-pullback-config-1.1.0`, strategy `1.1.0`
**Human decision:** `D-R002` in [`HUMAN_APPROVAL_WORKSPACE.md`](HUMAN_APPROVAL_WORKSPACE.md) — blank

## 1. Current frozen behavior

`backend/app/strategies/trend_pullback.py:95-104`:

```python
def _age_bars(snapshot, at):
    return (snapshot.data_as_of - at).total_seconds() / 900

def _recent_events(snapshot, event_type, bars):
    return [
        event for event in snapshot.structure.events
        if event.type is event_type and 0 <= _age_bars(snapshot, event.candle_time) <= bars
    ]
```

`backend/app/strategies/trend_pullback.py:499-505`:

```python
adverse_choch = CHOCH_DOWN if direction is LONG else CHOCH_UP
if _recent_events(snapshot, adverse_choch, config.structure_lookback_bars):
    # STRUCTURE_INVALIDATED, NO_TRADE
```

**Frozen facts:**

- `structure_lookback_bars = 40` (`backend/app/strategies/config.py:45`).
- The upper bound is inclusive (`<= 40`).
- Only the adverse CHoCH type is queried; later opposite CHoCH/BOS events are not
  consulted.
- Case 53 (`evl_f0351448b9ba1e002f788686`) is blocked by `CHOCH_DOWN` at exactly
  `40.0` bars; later `CHOCH_UP` events do not clear it.

## 2. Identified ambiguity

The rule does not state whether the 40-bar window is an expiry clock
(“keep blocking until age > 40”), a maximum search horizon, or whether a later
opposite structure event should repair the state earlier. The current behavior is
conservative: one adverse event can poison the window even after structure has
repaired. Whether that conservatism is intentional market-structure semantics or an
artifact of filtering a single event type is undocumented.

## 3. Alternative designs (human chooses; none is selected here)

### Option A — Keep the fixed inclusive window

- Document that an adverse CHoCH blocks while `0 <= age <= 40`; no opposite-event
  clearing.
- Pros: zero behavior change; easy to audit.
- Cons: may suppress valid setups after repair; the exact-40 boundary stays
  surprising.

### Option B — Clear on later opposite CHoCH

- Remove the adverse event when a later opposite CHoCH exists (at or after the
  adverse event, before `data_as_of`).
- Pros: responsive to structure repair.
- Cons: a CHoCH can be noise; may clear too early.

### Option C — Clear on later opposite BOS

- Clear only when a later opposite break of structure confirms the repair.
- Pros: stronger confirmation than B; matches “structure repaired” more strictly.
- Cons: slower; may miss valid early continuations.

### Option D — Explicit structure state machine

- Track a structure regime with states such as `INTACT`, `ADVERSE_CHOCH`,
  `REPAIRED_CHOCH`, `REPAIRED_BOS`; expire only by the documented transition.
- Pros: explicit and testable; removes event-list ambiguity.
- Cons: largest change; needs new contracts, persistence/replay compatibility and
  more tests.

### Option E — Strict boundary only

- Change `<= 40` to `< 40`.
- Pros: minimal change; case 53's exactly-40 event no longer blocks.
- Cons: does not address opposite-structure invalidation; shifts a boundary rather
  than defining semantics.

## 4. Expected behavior changes per option

| Situation | 1.0.0 | A | B | C | D | E |
|---|---|---|---|---|---|---|
| Adverse CHoCH age 39 | blocked | blocked | blocked unless opposite | blocked unless opposite BOS | state-dependent | blocked |
| Adverse CHoCH age 40 | **blocked** | **blocked** | blocked unless opposite | blocked unless opposite BOS | state-dependent | **not blocked** |
| Age 41 | not blocked | not blocked | not blocked | not blocked | expired | not blocked |
| Adverse + later opposite CHoCH | blocked | blocked | cleared | still blocked | state-dependent | unchanged |
| Adverse + later opposite BOS | blocked | blocked | still blocked | cleared | state-dependent | unchanged |
| Opposite event older than adverse | irrelevant | irrelevant | does not clear | does not clear | invalid transition | irrelevant |

No option changes PATRON, Qwen, risk authority, position sizing, plan eligibility,
the strategy gate or execution.

## 5. Edge cases

- Age exactly `40.0`; floating-point boundary (39.999/40.000/40.001).
- Future event timestamps or events after `data_as_of`; must be ignored.
- Duplicate events at the same candle/time; deterministic selection required.
- Opposite CHoCH before the adverse event must not clear it.
- Same-candle adverse and opposite events; define ordering by event sequence/time.
- Multiple adverse events; does the newest control, or any? Current code uses the
  latest in the filtered list.
- Missing/empty `structure.events`; no crash, no invented event.
- Long and short symmetry (`CHOCH_DOWN` for long, `CHOCH_UP` for short).
- Replay and persisted evaluations must reproduce the same decision for the same
  version and snapshot.

## 6. Required regression tests

At minimum:

1. Case 53 replay under the chosen option (expected decision/reason).
2. Ages `39`, `40`, `41` for adverse CHoCH.
3. Adverse CHoCH followed by opposite CHoCH, with and without a later BOS.
4. Opposite CHoCH only before the adverse event: does not clear.
5. Duplicate/same-candle events: deterministic ordering.
6. Future event after `data_as_of`: ignored.
7. Empty event list and missing structure: no crash.
8. Long/short symmetric event types.
9. All existing trend-pullback tests remain green.
10. New 60-case packet generated under the new version; no in-place edits to 1.0.0.

## 7. Versioning and approval impact

- Any change other than Option A requires a new strategy/config version.
- A boundary-only Option E still requires a version bump because decisions change.
- The packet must be regenerated and independently human-reviewed; old signatures
  are invalid.
- The strategy gate remains PENDING until the full approval policy is satisfied.
- Execution remains DISABLED. This document does not select an option or apply a
  rule.
