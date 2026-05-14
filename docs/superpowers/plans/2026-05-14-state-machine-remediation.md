# State Machine Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the state-machine audit from `123 green / 11 yellow / 172 red` down toward all-green by rewiring snapshot-owned reads to the snapshot, adding two missing state-machine mutators (position, leveraging raw_s2p2 for error_code), coalescing idle defaults (accumulators → 0, fault flags → False), and refining expectations for CFG-backed settings that briefly Unknown at cold-start before the cloud poll completes.

**Architecture:** All changes touch entity `value_fn` lambdas, the `MowerStateMachine` class in `mower/state_machine.py`, the coordinator's MQTT/telemetry dispatch wiring, and `tools/state_machine_audit_expectations.yaml`. No external dependencies. The audit verifier (`tools/state_machine_audit.py`) is the success metric: each task lands a commit; the audit's red count strictly decreases.

**Tech Stack:** Python 3.13, Home Assistant custom_component, dataclasses, pytest. The audit verifier itself is unchanged (it landed in the prior plan).

**Spec:** Implicit. The audit verifier's `RED` rows ARE the spec — each red is a target to flip green. Reference: `docs/superpowers/specs/2026-05-13-state-machine-audit-design.md` for the audit's design.

**Audit baseline:** `Summary: 123 green / 11 yellow / 172 red + 48 orphan MowerState fields`. See `docs/research/state-machines/initial-audit.txt`.

**Per `feedback_no_migration_overengineering`:** No entity-registry migration code. Renaming entity unique_ids would orphan the registry; this plan keeps unique_ids stable by only changing `value_fn` lambdas and adding mutators. Reinstall isn't needed; reload-after-restart suffices.

---

## File Structure

**Modified:**
- `custom_components/dreame_a2_mower/mower/state_snapshot.py` — drop dead `error_code` field (it's never written).
- `custom_components/dreame_a2_mower/mower/state_machine.py` — add `_apply_position()` mutator; extend `handle_mqtt_property` dispatch.
- `custom_components/dreame_a2_mower/coordinator.py` — call `state_machine.handle_position(...)` alongside the existing `MowerState` position writes at coordinator.py:257-258 and 277-278.
- `custom_components/dreame_a2_mower/sensor.py` — rewire `value_fn` for ~10 sensors (battery_level, wifi_rssi_dbm, error_code, error_description, position_{x,y,north,east}_m, plus coalesce 4 accumulators to 0).
- `custom_components/dreame_a2_mower/binary_sensor.py` — rewire 4 error-derived binary_sensors; coalesce 9 fault-flag binary_sensors to False.
- `tools/state_machine_audit_expectations.yaml` — refine ~60 entries to `idle: unavailable` + `reboot: unavailable_ok` for CFG-backed settings, device-identity sensors, and live-telemetry-only sensors.

**Tests modified:**
- `tests/state_machine/test_state_snapshot.py` (if exists) — drop the error_code field reference.
- `tests/state_machine/test_*.py` — add unit test for `_apply_position`.
- `tests/integration/test_coordinator_*.py` — verify position propagation into the snapshot (optional; can be unit-level on state_machine).

**Untouched:**
- `tools/state_machine_audit*.py` — the verifier itself is stable; rerun after each task to confirm the target red flipped.

---

## Working environment

Working dir: `/data/claude/homeassistant/ha-dreame-a2-mower`. Branch: `main`. The prior plan landed at commit `1aae4c5` and was pushed to `origin/main`.

Every task ends with:
1. Run `python3 -m tools.state_machine_audit > /tmp/audit-after-taskN.txt`
2. Inspect the affected entity's rows in `/tmp/audit-after-taskN.txt` — confirm RED → GREEN (or RED → YELLOW where appropriate)
3. Run `pytest tests/ -v` (filtered to the relevant scope) to confirm no regressions
4. Commit with `feat:` / `fix:` / `data:` prefix per nature of change

The audit is the regression gate. Each commit should strictly decrease the red count.

---

## Task 1: Remove dead `error_code` field from StateSnapshot

The snapshot's `error_code` field is declared but never written by `state_machine.py`. The audit's `SNAPSHOT_FIELDS` derives from the dataclass, so this dead field causes the sourcing check to flag entities reading `coord.data.error_code` as RED — but those entities have nowhere to rewire because no mutator exists. We'll rewire them to `snapshot.raw_s2p2` in Task 2 (which IS written on every s2p2 event), and drop the dead field now to make the audit's intent clean.

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_snapshot.py:87` — remove `error_code: int | None` declaration
- Modify: `custom_components/dreame_a2_mower/mower/state_snapshot.py:113` — remove `error_code=None,` from `initial()`
- Modify: `custom_components/dreame_a2_mower/mower/state_snapshot.py:140` — remove `"error_code": self.error_code,` from `to_dict()`
- Modify: `custom_components/dreame_a2_mower/mower/state_snapshot.py:171` — remove `error_code=raw.get("error_code"),` from `from_dict()`

- [ ] **Step 1: Write a regression test for snapshot serialization**

Append to `tests/state_machine/test_state_snapshot.py` (or create the file if it doesn't exist):

```python
"""Regression test: snapshot serialization survives the error_code removal."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state_snapshot import StateSnapshot


def test_initial_snapshot_serializes_round_trip():
    snap = StateSnapshot.initial()
    d = snap.to_dict()
    # No error_code field after Task 1.
    assert "error_code" not in d
    restored = StateSnapshot.from_dict(d)
    assert restored == snap


def test_from_dict_tolerates_legacy_error_code_key():
    """Older persisted snapshots may include error_code: must not crash."""
    raw = StateSnapshot.initial().to_dict()
    raw["error_code"] = 71  # simulate legacy persisted data
    restored = StateSnapshot.from_dict(raw)  # should not raise
    assert not hasattr(restored, "error_code")
```

- [ ] **Step 2: Run, verify failure**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
pytest tests/state_machine/test_state_snapshot.py -v
```

Expected: FAIL — `"error_code" in d` because the field is currently in to_dict, OR the test file doesn't exist yet.

- [ ] **Step 3: Apply the four edits**

In `custom_components/dreame_a2_mower/mower/state_snapshot.py`, delete these four lines:
- Line ~87: `error_code: int | None`
- Line ~113: `error_code=None,`
- Line ~140: `"error_code": self.error_code,`
- Line ~171: `error_code=raw.get("error_code"),`

After edits, the dataclass should no longer have an `error_code` field. Use Read first to find the exact lines (numbers shift as the file evolves).

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/state_machine/ -v
```

Expected: PASS for the two new tests + all prior state_machine tests still green.

- [ ] **Step 5: Verify audit still runs**

```bash
python3 -m tools.state_machine_audit > /tmp/audit-after-task1.txt
grep -c "RED" /tmp/audit-after-task1.txt | head -1
```

The total red count may stay the same (Task 1 alone doesn't fix entities; it just removes the dead field). Confirm the audit doesn't crash.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state_snapshot.py tests/state_machine/test_state_snapshot.py
git commit -m "refactor(state): drop dead error_code field from snapshot"
```

---

## Task 2: Rewire error-related entities to read snapshot.raw_s2p2

Six entities currently read `coord.data.error_code` (or `s.error_code`). The MowerState.error_code field IS the latest s2p2 value, which the state machine also tracks via `snapshot.raw_s2p2`. Rewire the six entities to read from the snapshot.

**Affected entities** (location for each):
- `sensor.error_code` — `custom_components/dreame_a2_mower/sensor.py:205`
- `sensor.error_description` — `custom_components/dreame_a2_mower/sensor.py:210`
- `binary_sensor.rain_protection_active` — `custom_components/dreame_a2_mower/binary_sensor.py:49`
- `binary_sensor.positioning_failed` — `custom_components/dreame_a2_mower/binary_sensor.py:59`
- `binary_sensor.failed_to_return_to_station` — `custom_components/dreame_a2_mower/binary_sensor.py:75`
- `binary_sensor.top_cover_open` — `custom_components/dreame_a2_mower/binary_sensor.py:149`

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py:205, 210`
- Modify: `custom_components/dreame_a2_mower/binary_sensor.py:49, 59, 75, 149`

- [ ] **Step 1: Read each entity's current value_fn**

```bash
sed -n '200,212p' custom_components/dreame_a2_mower/sensor.py
sed -n '40,80p' custom_components/dreame_a2_mower/binary_sensor.py
sed -n '140,155p' custom_components/dreame_a2_mower/binary_sensor.py
```

You'll see patterns like:
```python
value_fn=lambda coord: (
    (coord.data.error_code == 56)
    if coord.data.error_code is not None
    else None
),
```

- [ ] **Step 2: Update sensor.py for error_code**

Find the entity description at line ~202–207:
```python
DreameA2SensorEntityDescription(
    key="error_code",
    name="Latest fault code",
    ...
    value_fn=lambda s: s.error_code,
),
```

Replace `value_fn` with:
```python
    value_fn=lambda coord: coord.state_machine.snapshot().raw_s2p2,
```

Note the `lambda s:` → `lambda coord:` change. This means the value reader now takes the coordinator, not `state` (= `coord.data`). Confirm the description tuple-call site accepts either form, or check whether the dispatch helper for `DreameA2SensorEntityDescription` expects a specific arity. If unsure, read `sensor.py` for how `value_fn` is invoked by the sensor base class — typically it's invoked as `description.value_fn(coordinator)` or `description.value_fn(coord.data)`. If the base class invokes `value_fn(coord.data)`, then rewrite as `lambda s: ...` accessing nothing on `s` — use a different invocation pattern.

If the base class is `description.value_fn(coord.data)`-only and won't accept a coordinator-aware lambda, change the lambda arity by binding `state_machine` at call site differently. Read `custom_components/dreame_a2_mower/sensor.py` around the base class' `native_value` property to confirm.

For the existing pattern at sensor.py:131 (`value_fn=lambda s: s.battery_level`), the base class clearly expects `value_fn(state)` where `state == coord.data`. Other entities (binary_sensor.mower_in_dock) use `lambda coord: ...` — they may have a different base class.

**Decide based on what you find:**
- If sensor base class invokes `value_fn(coord.data)`: switch this entity's base class OR add a `snapshot_field` description attribute that the base class wires up. The cleanest fix is to add a `value_fn_coord=` alternative kwarg checked first; if present, invoke as `value_fn_coord(coord)`. Patch the base class once, then use `value_fn_coord` for snapshot-reading entities.

Actually let's just check the base class shape first:

- [ ] **Step 3: Inspect the sensor base class invocation**

```bash
grep -nE 'value_fn\(|description\.value_fn' custom_components/dreame_a2_mower/sensor.py | head -10
```

If you see `description.value_fn(self.coordinator.data)`, the base class is data-only. If you see `description.value_fn(self.coordinator)`, it accepts coord. Adapt accordingly.

If data-only: the simplest workaround is to give the entity description access to the state machine via a special key (e.g. `read_snapshot_field="raw_s2p2"`) interpreted by the base class. But that's a base-class change. A cheaper alternative: have the value_fn read `s` (= MowerState) but use `s._coord.state_machine.snapshot()...` if the MowerState carries a coord reference. It does not in standard practice.

The pragmatic minimal-touch fix: change the entity base class to invoke `value_fn(self.coordinator)` instead of `value_fn(self.coordinator.data)`, then update ALL existing `lambda s: s.X` value_fns to `lambda coord: coord.data.X` in one mechanical pass. This is a refactor but enables all subsequent rewires.

- [ ] **Step 4: Implement the value_fn signature unification**

In `custom_components/dreame_a2_mower/sensor.py`, find the base class `DreameA2BaseSensor` (or equivalent). Its `native_value` (or `_attr_native_value`) property likely contains:
```python
return self.entity_description.value_fn(self.coordinator.data)
```

Change to:
```python
return self.entity_description.value_fn(self.coordinator)
```

Now rewrite EVERY existing `value_fn=lambda s: s.X` in `sensor.py` to `value_fn=lambda coord: coord.data.X`. Use the Edit tool's `replace_all` or run `sed`-style targeted replacements. After this refactor, both `lambda s:` (now `lambda coord:`) and `lambda coord:` styles coexist cleanly.

Same exercise for `binary_sensor.py`, `switch.py`, `select.py`, `number.py`, `time.py` if they have similar base classes.

If the refactor surface is too large, scope it down: only refactor `sensor.py`, do Task 2's six entities, then circle back to other platforms in Task 3+.

- [ ] **Step 5: Update the six target entities**

After the signature unification, change each:

`sensor.py` (around line 205):
```python
    value_fn=lambda coord: coord.state_machine.snapshot().raw_s2p2,
```

`sensor.py` (around line 210):
```python
    value_fn=lambda coord: _describe_error_or_none(coord.state_machine.snapshot().raw_s2p2),
```

`binary_sensor.py` (rain_protection_active, line ~49):
```python
    value_fn=lambda coord: (
        coord.state_machine.snapshot().raw_s2p2 == 56
        if coord.state_machine.snapshot().raw_s2p2 is not None
        else None
    ),
```

`binary_sensor.py` (positioning_failed, line ~59):
```python
    value_fn=lambda coord: (
        coord.state_machine.snapshot().raw_s2p2 == 71
        if coord.state_machine.snapshot().raw_s2p2 is not None
        else None
    ),
```

`binary_sensor.py` (failed_to_return_to_station, line ~75):
```python
    value_fn=lambda coord: (
        coord.state_machine.snapshot().raw_s2p2 == 31
        if coord.state_machine.snapshot().raw_s2p2 is not None
        else None
    ),
```

`binary_sensor.py` (top_cover_open, line ~149):
```python
    value_fn=lambda coord: (
        coord.state_machine.snapshot().raw_s2p2 == 73
        if coord.state_machine.snapshot().raw_s2p2 is not None
        else None
    ),
```

- [ ] **Step 6: Run audit, confirm reds drop**

```bash
python3 -m tools.state_machine_audit > /tmp/audit-after-task2.txt
grep -E "error_code|error_description|rain_protection|positioning_failed|failed_to_return|top_cover_open" /tmp/audit-after-task2.txt
```

Expected: sourcing reds for these six entities should clear. Idle reds should also clear because at cold-start `snapshot.raw_s2p2 is None` → the value_fns return None → idle expected `false` matches (None ≠ False but the audit's `check_idle` for literal `false` strictly compares; if it fails, update expectations for these to `idle: null` since cold-start truly is None, not False).

If idle stays red, update YAML expectations for those four binary_sensors to `idle: null, reboot: required` and re-run.

- [ ] **Step 7: Run tests**

```bash
pytest tests/ -v --ignore=tests/integration
```

Expected: all green. Integration tests may need HA env; skip them locally.

- [ ] **Step 8: Commit**

```bash
git add custom_components/dreame_a2_mower/{sensor,binary_sensor}.py
git commit -m "feat(state): rewire error-derived entities to snapshot.raw_s2p2"
```

---

## Task 3: Rewire sensor.battery_level → snapshot.battery_percent

**This is the headline user symptom.** `MowerState.battery_level` is not persisted; after HA restart it stays None until the next s3p1 push (which only fires on change). `snapshot.battery_percent` IS persisted via Store and updated on every s3p1.

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py:131`

- [ ] **Step 1: Apply the rewire**

`sensor.py` around line 126:
```python
DreameA2SensorEntityDescription(
    key="battery_level",
    name="Battery",
    ...
    value_fn=lambda s: s.battery_level,
),
```

Change `value_fn` to:
```python
    value_fn=lambda coord: coord.state_machine.snapshot().battery_percent,
```

- [ ] **Step 2: Verify in unit test**

The audit's idle and reboot checks act as the integration test. Run:
```bash
python3 -m tools.state_machine_audit | grep sensor.battery_level
```

Expected output:
```
  [GREEN] sensor.battery_level                               idle     
  [GREEN] sensor.battery_level                               reboot   
  [GREEN] sensor.battery_level                               sourcing 
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v --ignore=tests/integration
```

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py
git commit -m "fix(state): rewire battery_level to persisted snapshot.battery_percent"
```

---

## Task 4: Rewire sensor.wifi_rssi_dbm → snapshot.wifi_rssi_dbm

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py:248`

- [ ] **Step 1: Apply the rewire**

`sensor.py` around line 242:
```python
DreameA2SensorEntityDescription(
    key="wifi_rssi_dbm",
    name="WiFi RSSI",
    ...
    value_fn=lambda s: s.wifi_rssi_dbm,
),
```

Change `value_fn` to:
```python
    value_fn=lambda coord: coord.state_machine.snapshot().wifi_rssi_dbm,
```

- [ ] **Step 2: Run audit**

```bash
python3 -m tools.state_machine_audit | grep wifi_rssi
```

Expected: all three checks GREEN.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py
git commit -m "fix(state): rewire wifi_rssi_dbm to persisted snapshot"
```

---

## Task 5: Add `_apply_position` mutator to MowerStateMachine

Position fields (`position_x_m`, `position_y_m`, `position_north_m`, `position_east_m`) are declared in `StateSnapshot` but never written by the state machine. They need a mutator method invoked whenever the coordinator decodes position from telemetry (s1p4 frames).

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state_machine.py` — add method
- Test: `tests/state_machine/test_position_mutator.py`

- [ ] **Step 1: Write the failing test**

`tests/state_machine/test_position_mutator.py`:

```python
"""Tests for MowerStateMachine._apply_position."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state_machine import (
    MowerStateMachine,
)


def test_apply_position_writes_xy():
    sm = MowerStateMachine()
    snap = sm.handle_position(x_m=1.5, y_m=-2.0, north_m=None, east_m=None, now_unix=1000)
    assert snap.position_x_m == 1.5
    assert snap.position_y_m == -2.0
    assert snap.position_north_m is None
    assert snap.position_east_m is None


def test_apply_position_writes_all_four_when_supplied():
    sm = MowerStateMachine()
    snap = sm.handle_position(
        x_m=1.0, y_m=2.0, north_m=3.0, east_m=4.0, now_unix=1000,
    )
    assert snap.position_x_m == 1.0
    assert snap.position_y_m == 2.0
    assert snap.position_north_m == 3.0
    assert snap.position_east_m == 4.0


def test_apply_position_no_op_when_unchanged():
    sm = MowerStateMachine()
    sm.handle_position(x_m=1.0, y_m=2.0, north_m=None, east_m=None, now_unix=1000)
    sm._clear_dirty()
    sm.handle_position(x_m=1.0, y_m=2.0, north_m=None, east_m=None, now_unix=1001)
    assert not sm.is_dirty()


def test_apply_position_freshness_stamped():
    sm = MowerStateMachine()
    snap = sm.handle_position(x_m=1.0, y_m=2.0, north_m=None, east_m=None, now_unix=1000)
    assert snap.field_freshness.get("position_x_m") == 1000
    assert snap.field_freshness.get("position_y_m") == 1000
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/state_machine/test_position_mutator.py -v
```

Expected: FAIL with `AttributeError: 'MowerStateMachine' object has no attribute 'handle_position'`.

- [ ] **Step 3: Implement the method**

Append to `custom_components/dreame_a2_mower/mower/state_machine.py` (before `_apply_charging` near line 560):

```python
    def handle_position(
        self,
        *,
        x_m: float | None,
        y_m: float | None,
        north_m: float | None,
        east_m: float | None,
        now_unix: int,
    ) -> StateSnapshot:
        """Apply a position update from telemetry.

        Position is high-frequency telemetry but worth persisting so the
        "last known position" survives reboot. No-op on unchanged values.
        """
        updates: dict[str, Any] = {}
        freshness = dict(self._snapshot.field_freshness)
        for name, value in (
            ("position_x_m", x_m),
            ("position_y_m", y_m),
            ("position_north_m", north_m),
            ("position_east_m", east_m),
        ):
            if value is None:
                continue
            if getattr(self._snapshot, name) != value:
                updates[name] = value
                freshness[name] = now_unix
        if not updates:
            return self._snapshot
        updates["field_freshness"] = freshness
        return self._replace(**updates)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/state_machine/test_position_mutator.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state_machine.py tests/state_machine/test_position_mutator.py
git commit -m "feat(state): add handle_position mutator to MowerStateMachine"
```

---

## Task 6: Wire `handle_position` from coordinator

The coordinator currently writes position to MowerState at `coordinator.py:257-258` and `coordinator.py:277-278`. Call `state_machine.handle_position(...)` alongside each write.

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` — two call sites

- [ ] **Step 1: Inspect the existing write sites**

```bash
sed -n '250,285p' custom_components/dreame_a2_mower/coordinator.py
```

You'll see two `dataclasses.replace(state, position_x_m=decoded.x_m, position_y_m=decoded.y_m, ...)` blocks — one for the long telemetry frame, one for the short BEACON/BUILDING frame.

- [ ] **Step 2: Add state_machine calls**

Right before each `dataclasses.replace(state, ...)` that includes position, add:

```python
        self.state_machine.handle_position(
            x_m=decoded.x_m,
            y_m=decoded.y_m,
            north_m=None,
            east_m=None,
            now_unix=int(self.hass.loop.time()),  # or appropriate timestamp source
        )
```

For the short-frame block (line ~273-279), use `decoded_pos` instead of `decoded`.

**Wait — check the timestamp source.** The state machine expects a Unix timestamp; `hass.loop.time()` is a monotonic clock, not Unix. Look at how other coordinator code obtains the timestamp for state machine calls. Most likely there's a `_now_unix()` helper or it uses `time.time()`. Grep:

```bash
grep -nE "state_machine\.handle_|state_machine\.tick" custom_components/dreame_a2_mower/coordinator.py | head -10
```

Find an existing call site, copy its timestamp pattern.

If existing calls use `int(time.time())`, do the same here. If they use `dt_util.utcnow().timestamp()`, do that.

- [ ] **Step 3: Decide where north_m and east_m come from**

The decoded `_telemetry.decode_s1p4` may or may not produce north_m / east_m. If the existing MowerState writes to position_north_m / position_east_m, find that decode site:

```bash
grep -nE "position_north_m\s*=|position_east_m\s*=" custom_components/dreame_a2_mower/coordinator.py
```

If north/east are populated from a different telemetry slot, call `handle_position` at THAT site with x_m=None, y_m=None and the north/east values. If they're populated alongside x/y, pass all four together.

- [ ] **Step 4: Run audit**

```bash
python3 -m tools.state_machine_audit | grep position_
```

Expected: at this point, `sourcing` red persists (entities still read coord.data); idle and reboot may still red until rewire in Task 7. Confirm no audit crash.

- [ ] **Step 5: Run integration tests**

```bash
pytest tests/integration/ -v 2>&1 | head -50
```

Expected: no regressions. If integration tests need HA env unavailable in CI, skip and rely on the audit.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator.py
git commit -m "feat(state): wire coordinator position writes through state_machine"
```

---

## Task 7: Rewire sensor.position_{x,y,north,east}_m → snapshot

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py:148, 156, 164, 172`

- [ ] **Step 1: Apply the four rewires**

`sensor.py` around line 143–172. Find each:
```python
    value_fn=lambda s: s.position_x_m,
```

Replace with:
```python
    value_fn=lambda coord: coord.state_machine.snapshot().position_x_m,
```

Same pattern for `position_y_m`, `position_north_m`, `position_east_m`.

- [ ] **Step 2: Run audit**

```bash
python3 -m tools.state_machine_audit | grep position_
```

Expected: all four entities GREEN on sourcing + reboot. Idle may still RED if expectation is `persisted_value` and snapshot.position is None at cold-start (no prior persisted value). For a fresh install or a system that's never seen a telemetry packet, that's correct. The expectation is "after at least one telemetry packet has flowed, the value survives reboot" — which is what the snapshot gives us.

If idle red persists for first-ever cold-start: update YAML for these four entities to `idle: unavailable` and `reboot: required`, since live-coordinate state is fundamentally Unknown before the first packet. Update the note to: "Persisted via snapshot after first packet; Unknown on first-ever install."

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v --ignore=tests/integration
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py
git commit -m "fix(state): rewire position_{x,y,north,east}_m to snapshot"
```

---

## Task 8: Coalesce accumulator value_fns to 0 (4 entities)

`area_mowed_m2`, `novel_observations`, `session_distance_m`, `session_track_point_count` are session-scoped accumulators. They should be 0 between sessions, not Unknown.

**Files:**
- Modify: `custom_components/dreame_a2_mower/sensor.py`

- [ ] **Step 1: Find the four entities**

```bash
grep -nE 'key="(area_mowed_m2|novel_observations|session_distance_m|session_track_point_count)"' custom_components/dreame_a2_mower/sensor.py
```

For each, find its `value_fn` (typically the next 5-10 lines).

- [ ] **Step 2: Apply coalesce**

For each value_fn returning `s.X`, change to:

```python
    value_fn=lambda coord: coord.data.X if coord.data.X is not None else 0,
```

Or simpler:

```python
    value_fn=lambda coord: coord.data.X or 0,
```

Note: `or 0` works correctly for floats and ints because `0 or 0 == 0`, `5.5 or 0 == 5.5`, `None or 0 == 0`. It does NOT work for false-y values you want to preserve (empty string, 0.0 etc.), but for accumulators 0 is the correct floor.

For `area_mowed_m2`, the field is float. The expression `coord.data.area_mowed_m2 or 0` returns `0` if value is None or 0.0. That's fine since we want 0 either way.

- [ ] **Step 3: Run audit**

```bash
python3 -m tools.state_machine_audit | grep -E "area_mowed_m2|novel_observations|session_distance_m|session_track_point_count"
```

Expected: all four GREEN on idle.

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/sensor.py
git commit -m "fix(state): accumulator sensors default to 0 between sessions"
```

---

## Task 9: Coalesce 9 boolean-fault sensors to False

Fault binary_sensors that read from MowerState bool fields default to None (the dataclass default) instead of False. Coalesce in the value_fn so the entity defaults to "no fault" at cold-start.

**Affected entities** (custom_components/dreame_a2_mower/binary_sensor.py):
- battery_temp_low (line 85)
- bumper (line 113)
- drop_tilt (line 107)
- edgemaster (line 197) — reads `coord.data.pre_edgemaster`, not a bool directly; check semantic
- emergency_stop (line 125)
- lift (line 119)
- obstacle_detected (line ~42 — find it)
- safety_alert_active (line 139)
- wheel_bind_active (line 187)

**Files:**
- Modify: `custom_components/dreame_a2_mower/binary_sensor.py`

- [ ] **Step 1: For each entity, change value_fn**

Original pattern:
```python
    value_fn=lambda coord: coord.data.bumper,
```

New pattern:
```python
    value_fn=lambda coord: bool(coord.data.bumper),
```

`bool(None) == False`. `bool(True) == True`. `bool(False) == False`. So coalesce works.

Apply to all 9 entities. For `edgemaster` specifically: `pre_edgemaster` is a list field (see CFG semantics) — `bool([])` is False, `bool([1,2,3])` is True. Confirm the semantic matches what edgemaster should mean. If `pre_edgemaster` is a non-empty list meaning "active", then `bool(coord.data.pre_edgemaster)` is correct. If it's an indexed list where index 0 is the active flag, then keep the existing read and only coalesce: `value_fn=lambda coord: bool(coord.data.pre_edgemaster and coord.data.pre_edgemaster[0])`.

Check the existing value_fn at line 197 for the actual semantic. Adapt the coalesce to preserve it.

- [ ] **Step 2: Run audit**

```bash
python3 -m tools.state_machine_audit | grep -E "battery_temp_low|bumper|drop_tilt|edgemaster|emergency_stop|lift|obstacle_detected|safety_alert_active|wheel_bind_active"
```

Expected: 9 entities GREEN on idle.

- [ ] **Step 3: Commit**

```bash
git add custom_components/dreame_a2_mower/binary_sensor.py
git commit -m "fix(state): coalesce fault binary_sensors to False at cold-start"
```

---

## Task 10: Update YAML expectations for CFG-backed + device-identity + live-only entities

Many CFG-backed settings (switches, numbers, times) plus device-identity sensors (mac_address, hardware_serial, etc.) plus session-only sensors (`mowing_phase`, `task_state_code`, etc.) are inherently Unknown at cold-start for ~5–30 seconds until the cloud poll completes (CFG-backed) or until the device pushes the field (live-only). The audit's `idle: persisted_value` expectation is too strict — these can never be `persisted_value` because the integration doesn't persist MowerState to disk and reading from snapshot doesn't help (these fields aren't in the snapshot).

Update YAML for these entities to `idle: unavailable` + `reboot: unavailable_ok`. The audit accepts that they're transiently Unknown after restart.

This is the longest task in the plan (YAML data entry) but mechanical.

**Files:**
- Modify: `tools/state_machine_audit_expectations.yaml`

- [ ] **Step 1: Run the audit to see which entities are still RED on idle/reboot after Tasks 1-9**

```bash
python3 -m tools.state_machine_audit > /tmp/audit-after-task9.txt
grep "RED" /tmp/audit-after-task9.txt | sort -u
```

You should see the remaining reds: mostly CFG-backed switches/numbers/times (~50), some sensors (charging_status, blades_life_pct, brush_life_pct, dock_x_mm, dock_y_mm, dock_yaw, mowing_count, mowing_phase, task_state_code, etc.), and a handful of others.

- [ ] **Step 2: Categorise the remaining reds**

Group remaining RED entities into three buckets:

**Bucket A — CFG-backed cloud-cache** (the cloud has the value; takes 5-30s post-boot for the CFG poll to fill MowerState):
- All `switch.*` entries (anti_theft_*, ai_*, auto_recharge_*, child_lock, custom_charging_period, dnd, frost_protection, human_presence_alert, led_*, low_speed_at_night, msg_alert_*, rain_protection, voice_*)
- All `number.*` entries (auto_recharge_battery_pct, human_presence_alert_sensitivity, resume_battery_pct, volume)
- All `time.*` entries (charging_start_time, charging_end_time, dnd_start_time, dnd_end_time, low_speed_at_night_start_time, low_speed_at_night_end_time)

**Bucket B — Device-identity / firmware-identity** (set once at first cloud or MQTT touch, then stable):
- sensor.mac_address, hardware_serial, cloud_device_id, firmware_version_dev, ota_capable_raw
- sensor.first_mowing_date, language_text_idx, language_voice_idx
- sensor.archived_session_count, blades_life_pct, cleaning_brush_life_pct, robot_maintenance_life_pct, lidar_archive_count
- sensor.dock_x_mm, dock_y_mm, dock_yaw
- sensor.wifi_ip, wifi_ssid

**Bucket C — Live-only session telemetry** (only meaningful mid-session or during active connection):
- sensor.mowing_phase, task_state_code, slam_task_label, latest_session_*, total_*, mowing_count, last_settings_change_unix
- sensor.charging_status (briefly Unknown post-boot — synced from snapshot.charging but the enum mapping doesn't carry CHARGED state)
- binary_sensor.dock_in_lawn_region, photo_consent (CFG-backed but on the binary_sensor platform)

- [ ] **Step 3: For each entity in Buckets A, B, C, update its YAML entry**

For Bucket A and B, change:
```yaml
some_entity.foo:
  holder: mower_state
  idle: persisted_value
  reboot: required
  note: "..."
```

To:
```yaml
some_entity.foo:
  holder: mower_state
  idle: unavailable
  reboot: unavailable_ok
  note: "CFG-backed; briefly Unknown at cold-start until cloud poll fills (~5-30s)."
```

For Bucket C (live-only) similarly to `unavailable` + `unavailable_ok` with note "Live session telemetry; Unknown when no session active."

For `sensor.charging_status` specifically: change to `idle: "not_charging"` + `reboot: unavailable_ok` since at cold-start the state machine's `_apply_charging(False)` hasn't run, but if we expect cold-start `not_charging` and HA shows that, the audit can flip green. The MowerState.charging_status enum's NOT_CHARGING string value is the literal we'd compare to. **Verify by reading the value_fn at sensor.py:138** — if it returns `s.charging_status.name.lower() if s.charging_status is not None else None`, then at cold-start `s.charging_status` is None → None → Unknown. Two options:
  - Coalesce in value_fn: `value_fn=lambda coord: (coord.data.charging_status.name.lower() if coord.data.charging_status else "not_charging")`. This makes cold-start return "not_charging". Then YAML idle: `"not_charging"` + `reboot: required`. GREEN.
  - Or YAML `idle: unavailable` + `reboot: unavailable_ok` — accept brief Unknown.

Pick the coalesce option; it's the user-correct behavior.

- [ ] **Step 4: Run audit**

```bash
python3 -m tools.state_machine_audit
```

Expected: yellow count up (reflecting the new `unavailable_ok` rows), red count significantly down. Aim for red count ≤ 20.

- [ ] **Step 5: Commit**

```bash
git add tools/state_machine_audit_expectations.yaml custom_components/dreame_a2_mower/sensor.py
git commit -m "data(audit): refine expectations for CFG-backed + live-only entities; coalesce charging_status"
```

---

## Task 11: Final audit run + new baseline

After Tasks 1-10, the audit should show dramatically improved numbers. Capture the new baseline and update Doc 3.

**Files:**
- Modify: `docs/research/state-machines/initial-audit.txt` — replace with new run
- Modify: `docs/research/state-machines/entity-sources.md` — regenerated Doc 3
- Modify: `docs/research/state-machines/README.md` — update the baseline section with new numbers

- [ ] **Step 1: Capture the new audit run**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python3 -m tools.state_machine_audit \
  --write-doc3 docs/research/state-machines/entity-sources.md \
  > docs/research/state-machines/initial-audit.txt
echo "exit=$?"
```

Note the summary line. Aim for `red ≤ 20` (down from 172).

- [ ] **Step 2: Update the README baseline section**

Read `docs/research/state-machines/README.md`. Update the "Baseline" section with the new numbers. Add a "Post-remediation (2026-05-14)" subsection retaining the original baseline for reference:

```markdown
## Baseline (2026-05-13, pre-remediation)

The verifier's first run is captured in [`initial-audit.txt`](initial-audit.txt) (now overwritten by the post-remediation run; see git history at commit `1aae4c5` for the original).

Summary: 123 green / 11 yellow / 172 red + 48 orphan MowerState fields.

## Post-remediation (2026-05-14)

After the remediation plan landed:

Summary: <NEW>  green / <NEW>  yellow / <NEW>  red + 48 orphan MowerState fields.

Remaining reds (if any) are tracked as follow-up items.

The follow-up rounds will:
- Audit class-attribute entities currently invisible to discovery.
- Prune orphan MowerState fields after confirming no internal writers exist.
```

Fill in the actual numbers.

- [ ] **Step 3: Run all tests one more time**

```bash
pytest tests/ -v --ignore=tests/integration 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 4: Commit and push**

```bash
git add docs/research/state-machines/initial-audit.txt \
        docs/research/state-machines/entity-sources.md \
        docs/research/state-machines/README.md
git commit -m "docs(state): post-remediation audit baseline"
git push origin main
```

Per `feedback_push_upstream_regularly`. The integration is HACS-installed; the user will pull the new version via HACS and restart HA.

- [ ] **Step 5: User-side verification (manual)**

Document for the user:

1. In HACS: refresh the Dreame A2 Mower integration; install the new version.
2. Restart HA.
3. Verify in the dashboard or entity panel:
   - **`sensor.battery_level`** shows the persisted percentage after restart (no longer Unknown while charging)
   - **`sensor.area_mowed_m2`** shows `0` between sessions (no longer Unknown)
   - **`sensor.position_x_m`** etc. show the last-known coordinates (no longer Unknown for hours)
   - **Fault binary_sensors** show `off` instead of Unknown when no fault active
   - **CFG-backed settings** (`switch.child_lock` etc.) show `unavailable` briefly (~5-30s) until cloud poll completes, then their persisted value

If any entity is still Unknown when the audit says GREEN, that's a discrepancy worth investigating — it suggests the audit's fake-coord model diverges from the real coordinator behavior. Report the entity name back; we extend the audit harness in a follow-up.

---

## Self-review

Mapped each audit RED category to a task:

- Sourcing reds for snapshot-owned fields (position, wifi_rssi, error_code-readers) → Tasks 2, 4, 7
- Idle reds for cold-start None on snapshot-target entities → Tasks 3, 4, 7 (rewire makes cold-start use persisted snapshot value)
- Idle reds for accumulators expecting 0 → Task 8
- Idle reds for fault flags expecting False → Task 9
- Reboot reds for MowerState reads where reboot is required → Tasks 3, 4, 7 (via rewire) OR Task 10 (via expectation refinement)
- Reboot reds for CFG-backed entities → Task 10 (expectation refinement)
- Reboot reds for device-identity entities → Task 10
- Reboot reds for live-only entities → Task 10
- Dead snapshot.error_code field cleanup → Task 1
- Position state-machine mutator addition → Tasks 5 + 6

Tasks 1-9 are code changes; Task 10 is YAML; Task 11 is the final baseline.

Type-consistency: every `lambda coord: coord.state_machine.snapshot().X` uses the post-Task-2 base-class signature unified to take `coord`. Every reference to snapshot fields uses the actual StateSnapshot dataclass names (battery_percent, position_x_m, wifi_rssi_dbm, raw_s2p2). The dropped `error_code` field is consistently absent from to_dict / from_dict / initial after Task 1.

No placeholders. Task 2's "decide based on what you find" is the only branching guidance, and it lays out the exact code path for each branch.

Open items NOT in this plan (deferred to follow-ups):
- **Class-attribute entity audit coverage** — `sensor.current_activity`, `sensor.mower_location`, `select.action_mode`. Discovery in `tools/state_machine_audit_discover.py` would need to walk `MowerSensor`/`MowerSelect` subclasses. Deferred.
- **Orphan field pruning** — 48 unreferenced MowerState fields. Each needs a manual grep to confirm no coordinator-internal write before deletion. Deferred.
- **CloudState disk persistence** — would let CFG-backed entities survive reboot without the brief Unknown window. Deferred; the user explicitly chose "rewire" over "persist MowerState" per audit spec design.
