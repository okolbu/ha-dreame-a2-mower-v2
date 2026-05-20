# B2b — `reconcile_from_telemetry` Refactor (Design)

**Date:** 2026-05-20
**Status:** spec
**Parent (Block 2):** `docs/superpowers/specs/2026-05-19-integration-audit-meta.md` § 5 ([B2] state_machine item).
**Sibling:** B2a (`2026-05-20-b2a-domain-protocol-design.md`) shipped the other 6 Block-2 items as `v1.0.17a8`.

## What this is

Second and final Block-2 sub-cycle. Shortens
`mower/state_machine.py` `MowerStateMachine.reconcile_from_telemetry`
(121 LOC) by splitting its two independent inference sections into named
private helpers, leaving a thin driver. Behavior-preserving, isolated to
one method, behind strong existing test coverage.

## Reality note (backlog framing corrected)

The meta backlog phrased this as "`(phase, state)` if/elif table → convert
to `(phase, state)→transition_fn` dispatch." That shape does **not** fit:
`reconcile_from_telemetry` is a **guard-based rules engine**, not a 2D
state table. Its guards depend on telemetry (`area_mowed_m2 > 0`,
`live_map_active`, off-dock distance) and on multiple snapshot fields at
once — a tuple-keyed dispatch dict cannot express them. So the chosen
refactor is a two-section extraction, not a dispatch table.

## Current structure

`reconcile_from_telemetry` has two independent inference sections sharing
an `updates` dict and a `freshness` dict (a copy of
`self._snapshot.field_freshness`):

1. **Mow-session / activity inference** — a mutually-exclusive `if/elif`
   chain of 5 rules, each gated on `(mow_session, current_activity,
   location)` + telemetry:
   - R1 BETWEEN_SESSIONS + live_map + area>0 → IN_SESSION / MOWING
   - R2 IN_SESSION + not live_map → BETWEEN_SESSIONS / IDLE
   - R3 IN_SESSION + CHARGE_RESUME + not AT_DOCK + area>0 → MOWING
   - R4 BETWEEN_SESSIONS + CHARGE_RESUME → IDLE
   - R5 IN_SESSION + MOWING + AT_DOCK → CHARGE_RESUME
2. **Location inference** — a separate, independent `if` (R6): AT_DOCK +
   position clearly off-dock (`dist_m > OFF_DOCK_THRESHOLD_M`) → ON_LAWN.

Tail: `if not updates: return self._snapshot` (unchanged-snapshot
short-circuit); else `updates["field_freshness"] = freshness; return
self._replace(**updates)`.

## Decisions (user, 2026-05-20)

- **Two-section split** (not per-rule helpers, not skip).
- **Derive freshness centrally** in the driver (the verified-equivalent
  simplification — see below), rather than threading the freshness dict
  through the helpers.

## Target shape

```python
def reconcile_from_telemetry(self, *, live_map_active, area_mowed_m2,
                             position_x_m, position_y_m, dock_x_mm, dock_y_mm,
                             now_unix) -> StateSnapshot:
    updates: dict[str, Any] = {
        **self._reconcile_mow_activity(
            live_map_active=live_map_active, area_mowed_m2=area_mowed_m2),
        **self._reconcile_location(
            position_x_m=position_x_m, position_y_m=position_y_m,
            dock_x_mm=dock_x_mm, dock_y_mm=dock_y_mm),
    }
    if not updates:
        return self._snapshot
    freshness = dict(self._snapshot.field_freshness)
    for field in updates:
        freshness[field] = now_unix
    updates["field_freshness"] = freshness
    return self._replace(**updates)
```

- `_reconcile_mow_activity(self, *, live_map_active, area_mowed_m2) -> dict[str, Any]`
  — the R1-R5 elif-chain, moved VERBATIM, building and returning a local
  `updates` dict (the `mow_session` / `current_activity` field changes).
  Mutual exclusivity preserved (single `if/elif` chain; returns its dict).
  The per-rule `freshness[...] = now_unix` lines are dropped (centralized).
- `_reconcile_location(self, *, position_x_m, position_y_m, dock_x_mm, dock_y_mm) -> dict[str, Any]`
  — the R6 location `if`, moved VERBATIM, returning `{"location": Location.ON_LAWN}`
  or `{}`. Its `freshness["location"]` line dropped (centralized). The
  distance math, the mm→m conversion, and `OFF_DOCK_THRESHOLD_M` are unchanged.
- Each helper keeps the existing local `from .state_snapshot import ...`
  pattern (import only the enums it references).

## The freshness-derivation equivalence (the one judgment call)

Today each rule sets `freshness[k] = now_unix` for **exactly** the fields
`k` it writes into `updates`. Verified rule-by-rule:

| Rule | updates fields | freshness bumped |
|---|---|---|
| R1 | mow_session, current_activity | same two |
| R2 | mow_session, current_activity | same two |
| R3 | current_activity | same |
| R4 | current_activity | same |
| R5 | current_activity | same |
| R6 | location | same |

So `for field in updates: freshness[field] = now_unix` produces an
**identical** `field_freshness` to the original per-rule bumps, for any
combination of fired rules. Unchanged fields keep their copied value; the
`if not updates` short-circuit still returns the original snapshot
untouched (no freshness write). This removes 11 repetitive lines.

## Testing (characterization-first — sensitive code)

`tests/state_machine/test_state_machine_reconcile.py` (~13 tests) already
covers all 6 rules and their gates. BEFORE refactoring:
- Add a test that asserts `field_freshness` values on the returned snapshot
  (e.g. after a mow-start, `field_freshness["mow_session"] == now_unix` and
  `field_freshness["current_activity"] == now_unix`, and an unchanged field's
  freshness is preserved) — so the derived-freshness equivalence is PINNED,
  not assumed.
- Confirm R2 (IN_SESSION + not live_map → BETWEEN_SESSIONS / IDLE) is
  covered; add a focused test if it isn't.
Run the reconcile test file green, THEN refactor; the full suite
(`python -m pytest tests -q`, baseline 1589 passed / 4 skipped + the new
tests) must stay green.

## Scope

Only `custom_components/dreame_a2_mower/mower/state_machine.py`
(`reconcile_from_telemetry` + the two new private helpers) and
`tests/state_machine/test_state_machine_reconcile.py` (added
characterization tests). Behavior-preserving. One commit (after the
characterization tests, which may be a separate prior commit).

## Out of scope
- No other `state_machine.py` method changes. No per-rule helper extraction
  (rejected for indirection/precedence risk). This is the last Block-2 item;
  Blocks 3 and 4 follow.

## Push discipline
Behavior-preserving, suite green. Commit on `main` with `audit-b2b:` prefix;
ship (push + `release.sh` → next alpha) at the user's discretion after the
cycle, no separate live smoke-gate required.
