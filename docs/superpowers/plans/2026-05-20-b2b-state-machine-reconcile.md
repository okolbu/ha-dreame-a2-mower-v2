# B2b state_machine reconcile_from_telemetry Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink `MowerStateMachine.reconcile_from_telemetry` (121 LOC) into a thin driver + two named inference helpers (`_reconcile_mow_activity`, `_reconcile_location`), behavior-preserving.

**Architecture:** The method is a guard-based rules engine with two independent sections (a 5-rule mutually-exclusive mow-session/activity elif-chain + one location `if`). Extract each section into a private helper that returns a field-updates dict; the driver merges them and derives `field_freshness` centrally (bump `now_unix` for each changed field — verified equivalent to the per-rule bumps).

**Tech Stack:** Python 3, HA custom integration, pytest. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-20-b2b-state-machine-reconcile-design.md`

**Context:** On branch `main` (HEAD `2691feb`). Commit on `main` with `audit-b2b:` prefix, authored as the user, no co-author trailer. Do NOT push (user ships after). Full suite (`python -m pytest tests -q`) baseline: **1589 passed, 4 skipped**. This is behaviorally sensitive code — characterization tests come FIRST (Task 1), then the refactor (Task 2).

---

## File Structure

| File | Change |
|---|---|
| `tests/state_machine/test_state_machine_reconcile.py` | add characterization tests (T1) |
| `custom_components/dreame_a2_mower/mower/state_machine.py` | split `reconcile_from_telemetry` (T2) |

---

### Task 1: Characterization tests (lock behavior before refactor)

These tests must PASS against the CURRENT (un-refactored) code — they pin the behavior the refactor must preserve, especially the freshness-stamping that the derived-freshness simplification relies on.

**Files:**
- Test: `tests/state_machine/test_state_machine_reconcile.py`

- [ ] **Step 1: Add the freshness-stamping characterization test**

Append to `tests/state_machine/test_state_machine_reconcile.py`:

```python
def test_reconcile_stamps_freshness_only_for_changed_fields():
    """A mow-start inference stamps field_freshness=now_unix for EXACTLY the
    changed fields (mow_session, current_activity) and leaves an unchanged
    field's freshness untouched. Pins the derived-freshness equivalence the
    B2b refactor relies on."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    location_fresh_before = sm.snapshot().field_freshness.get("location")
    sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=42.0,
        position_x_m=0.15, position_y_m=0.01,   # ~near dock → location unchanged
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.IN_SESSION
    assert snap.current_activity == CurrentActivity.MOWING
    # changed fields stamped to now_unix:
    assert snap.field_freshness["mow_session"] == 1000
    assert snap.field_freshness["current_activity"] == 1000
    # unchanged field's freshness preserved (not re-stamped):
    assert snap.field_freshness.get("location") == location_fresh_before
```

- [ ] **Step 2: Run it against current code — must PASS**

Run: `python -m pytest tests/state_machine/test_state_machine_reconcile.py::test_reconcile_stamps_freshness_only_for_changed_fields -v`
Expected: PASS (current code already bumps freshness for exactly the changed fields). If it FAILS, STOP and report — the derived-freshness equivalence assumption is wrong and the spec needs revisiting.

- [ ] **Step 3: Confirm the R2 inverse-inference is covered; add a test if not**

Check for an existing test of R2 (IN_SESSION + live_map no longer active → BETWEEN_SESSIONS / IDLE):
```bash
grep -nE "live_map_active=False|live_map_active = False" tests/state_machine/test_state_machine_reconcile.py
```
If a test already seeds IN_SESSION and calls reconcile with `live_map_active=False` asserting BETWEEN_SESSIONS, skip this step. Otherwise append:

```python
def test_reconcile_in_session_to_between_when_live_map_inactive():
    """R2 inverse inference: IN_SESSION but live_map no longer active →
    fall back to BETWEEN_SESSIONS / IDLE (stuck-session self-heal)."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=500)  # → IN_SESSION
    assert sm.snapshot().mow_session == MowSession.IN_SESSION
    sm.reconcile_from_telemetry(
        live_map_active=False,
        area_mowed_m2=None,
        position_x_m=0.15, position_y_m=0.01,   # near dock → location unchanged
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS
    assert snap.current_activity == CurrentActivity.IDLE
    assert snap.field_freshness["mow_session"] == 1000
```
Run: `python -m pytest tests/state_machine/test_state_machine_reconcile.py -v`
Expected: all pass (the new test(s) + the existing ~13). If `handle_mqtt_property(siid=2, piid=2, value=50, ...)` does not yield IN_SESSION (signature drift), adjust the seed to match how `test_reconcile_does_not_overwrite_authoritative_state` seeds IN_SESSION (it uses the same call at line ~72) — that test is the reference.

- [ ] **Step 4: Commit**

```bash
git add tests/state_machine/test_state_machine_reconcile.py
git commit -m "audit-b2b: characterization tests for reconcile_from_telemetry (freshness stamping + R2)"
```

---

### Task 2: Split `reconcile_from_telemetry` into two helpers + thin driver

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py` (`reconcile_from_telemetry`, currently ~L359-479)

- [ ] **Step 1: Add `_reconcile_mow_activity` helper**

Add a private method to `MowerStateMachine` (place it directly above `reconcile_from_telemetry`). Move the R1-R5 `if/elif` chain VERBATIM, with two mechanical changes only: (a) write into a LOCAL `updates` dict that the method returns; (b) DROP the `freshness[...] = now_unix` lines (freshness is derived in the driver). The guards (`self._snapshot.mow_session`, `self._snapshot.current_activity`, `self._snapshot.location`, `live_map_active`, `area_mowed_m2`) and the `updates[...] = ...` assignments stay byte-identical.

```python
def _reconcile_mow_activity(
    self, *, live_map_active: bool, area_mowed_m2: float | None,
) -> dict[str, Any]:
    """Mow-session / activity inference (R1-R5). Returns field updates (no
    freshness — the driver derives that). Mutually exclusive: first matching
    rule wins."""
    from .state_snapshot import CurrentActivity, MowSession, Location
    updates: dict[str, Any] = {}
    # R1 .. R5 — the existing elif chain, VERBATIM, writing into `updates`,
    # WITHOUT the `freshness[...] = now_unix` lines.
    # (paste the existing if/elif bodies here, dropping only the freshness lines)
    return updates
```

(`Location` is referenced by R3/R5 guards; `CurrentActivity`/`MowSession` throughout — keep all three in the local import.)

- [ ] **Step 2: Add `_reconcile_location` helper**

Add another private method (above `reconcile_from_telemetry`). Move the R6 location `if` VERBATIM, same two mechanical changes (local `updates` returned; drop the `freshness["location"]` line). The distance math, mm→m conversion, and `self.OFF_DOCK_THRESHOLD_M` comparison stay byte-identical.

```python
def _reconcile_location(
    self, *, position_x_m: float | None, position_y_m: float | None,
    dock_x_mm: float | None, dock_y_mm: float | None,
) -> dict[str, Any]:
    """Location inference (R6): AT_DOCK + position clearly off-dock → ON_LAWN.
    Returns field updates (no freshness — driver derives)."""
    from .state_snapshot import Location
    updates: dict[str, Any] = {}
    # R6 — the existing location `if`, VERBATIM, writing into `updates`,
    # WITHOUT the `freshness["location"]` line.
    return updates
```

- [ ] **Step 3: Replace `reconcile_from_telemetry` body with the driver**

Keep the existing signature and docstring of `reconcile_from_telemetry`. Replace its body (the `updates`/`freshness` setup, the R1-R5 chain, the R6 `if`, and the tail) with:

```python
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

The old top-of-method `from .state_snapshot import CurrentActivity, MowSession, Location` line in `reconcile_from_telemetry` is no longer needed there (the helpers import what they use) — remove it. `now_unix` stays a parameter (used by the driver for freshness). The two sections are independent: `_reconcile_mow_activity` and `_reconcile_location` can both contribute updates in one call (the original `if`/`elif` chain and the separate location `if` had the same independence), and dict-merge preserves that.

- [ ] **Step 4: Run the reconcile tests, then the full suite**

Run: `python -m pytest tests/state_machine/test_state_machine_reconcile.py -v`
Expected: all pass (the ~13 existing + the Task-1 characterization tests).
Run: `python -m pytest tests -q`
Expected: **1589 passed, 4 skipped** + the Task-1 test(s) (so 1590 or 1591 passed), no regressions.

- [ ] **Step 5: Confirm the driver shape**

```bash
grep -nE "def reconcile_from_telemetry|def _reconcile_mow_activity|def _reconcile_location" custom_components/dreame_a2_mower/mower/state_machine.py
```
Expected: all three present, with the two helpers defined above `reconcile_from_telemetry`. Eyeball `reconcile_from_telemetry` — it should now be the ~12-line driver (signature + docstring + the merge/short-circuit/freshness/replace block), no inline R1-R6 logic.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state_machine.py
git commit -m "audit-b2b: split reconcile_from_telemetry into _reconcile_mow_activity + _reconcile_location"
```

---

## Self-Review

**Spec coverage:**
- Two-section split (`_reconcile_mow_activity` + `_reconcile_location` + thin driver) → T2. ✓
- Derived freshness in the driver → T2 Step 3. ✓
- Characterization-first: freshness-stamping test + R2 confirmation → T1. ✓
- Behavior-preserving, one method, scope = state_machine.py + the reconcile test file. ✓
- Out of scope (per-rule extraction, other methods) → not in any task. ✓

**Placeholder scan:** The two helper code blocks say "paste the existing if/elif bodies here, dropping only the freshness lines" — this is a VERBATIM-move instruction for a refactor (the source is the current `reconcile_from_telemetry` body at `state_machine.py:393-474`), not a vague placeholder; the mechanical transformation (local `updates`, drop freshness lines) is fully specified. All test code is complete. All commands have expected output.

**Type/name consistency:** Helper names (`_reconcile_mow_activity`, `_reconcile_location`), their keyword-only signatures, and the driver's merge calls are consistent between T2 steps. Test names are unique. The `now_unix` parameter stays on the driver only.
