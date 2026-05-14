# State Machine Audit Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the three follow-up items from the post-remediation review: (A) resolve the 6 audit yellows by giving the audit eval scope access to private module helpers, (B) extend audit discovery to find class-attribute entities (`DreameA2CurrentActivitySensor` etc.) currently invisible to the AST walker, (C) prune the genuinely-unused fields from MowerState's orphan list. Target end state: `audit shows N+M green / 0 yellow / 0 red` with fewer (truly) orphan MowerState fields.

**Architecture:** All work touches the audit tool (`tools/state_machine_audit*.py`) and the integration's entity / MowerState definitions. The audit verifier is the regression gate — each task ends with a run that confirms the change.

**Tech Stack:** Python 3.13, dataclasses, `ast`, pytest. No new external dependencies.

**Spec:** Implicit — three follow-up items named in the prior plan's final review:
1. Yellow cleanup (audit harness extension)
2. Class-attribute entity discovery (audit walker extension)
3. Orphan field pruning (MowerState cleanup)

**Baseline (post-remediation):** `300 green / 6 yellow / 0 red + 54 orphan MowerState fields`. Release `v1.0.9a5` cut + verified live.

**Per `feedback_no_migration_overengineering`:** Pruning MowerState fields is a clean deletion — no migration / orphan-handling code. If a field is genuinely unused (no readers anywhere), delete; otherwise leave with a `# noqa-orphan-audit` comment + entry in `docs/research/state-machines/` explaining why.

---

## File Structure

**Phase A — Yellow cleanup:**
- Modify: `tools/state_machine_audit_fake_coord.py` — extend `_eval_globals()` to import private helpers from `sensor.py` / `binary_sensor.py`.
- Modify: `tools/state_machine_audit_expectations.yaml` — refine 4 helper-based entries to `idle: unavailable` + `reboot: unavailable_ok` if still yellow after the fix.

**Phase B — Class-attribute discovery:**
- Modify: `tools/state_machine_audit_discover.py` — add walker for `class Foo(base):` definitions with `_SNAPSHOT_FIELD` / `_attr_translation_key` class attributes; synthesize `EntityDescriptor` from each.
- Modify: `tools/state_machine_audit_expectations.yaml` — add entries for the ~10-15 newly-discovered class-attribute entities.
- Test: `tests/audit/test_discover_class_entities.py` (new) — verify the walker picks up known class-attribute entities.

**Phase C — Orphan pruning:**
- Investigate: walk MowerState orphans, grep coordinator + mower/ + tests for each.
- Modify: `custom_components/dreame_a2_mower/mower/state.py` — delete fields with zero references.
- Add: `docs/research/state-machines/orphan-fields.md` — document remaining orphans with categorization (used internally / surfaced via DeviceInfo / archive-only / etc.).

**Phase D — Release:**
- Modify: `custom_components/dreame_a2_mower/manifest.json` (bumped by `release.sh`).
- New tag + GitHub Release (`release.sh` handles).

**Untouched:**
- Integration's runtime behaviour. All work is audit-tool + dead-field cleanup.

---

## Working environment

Working dir: `/data/claude/homeassistant/ha-dreame-a2-mower`. Branch: `main`. Audit baseline: `300 green / 6 yellow / 0 red + 54 orphan`. Release `v1.0.9a5` is live.

Every task ends with a re-run of `python3 -m tools.state_machine_audit` to confirm the target metric (yellow / orphan count) moved in the right direction.

---

## Phase A — Yellow cleanup (3 tasks)

## Task 1: Inject private helpers into audit eval scope

The 4 yellow entities raise `NameError` because their `value_fn` lambdas reference module-level helpers (`_describe_error_or_none`, `_format_active_selection`, `_api_endpoints_value`, `_freshness_value`) defined in `sensor.py` but not in the audit's eval globals.

**Files:**
- Modify: `tools/state_machine_audit_fake_coord.py:_eval_globals` — import + add helpers
- Test: append to `tests/audit/test_fake_coord.py`

- [ ] **Step 1: Read the current `_eval_globals`**

```bash
sed -n '95,145p' tools/state_machine_audit_fake_coord.py
```

You'll see it currently injects only the StateSnapshot enums. We need to add 4 private helpers.

- [ ] **Step 2: Write a failing regression test**

Append to `tests/audit/test_fake_coord.py`:

```python
def test_observe_can_reference_describe_error_helper():
    """sensor.error_description's value_fn must be able to call _describe_error_or_none."""
    src = "lambda coord: _describe_error_or_none(coord.data.error_code)"
    val, exc = observe_cold_value(src)
    # At cold-start, error_code is None → describe_error returns None.
    # Either way, exc must not be NameError.
    assert exc is None or not isinstance(exc, NameError), (
        f"expected no NameError, got {type(exc).__name__}: {exc}"
    )


def test_observe_can_reference_freshness_helper():
    src = "lambda coord: _freshness_value(coord)"
    val, exc = observe_cold_value(src)
    assert exc is None or not isinstance(exc, NameError), (
        f"expected no NameError, got {type(exc).__name__}: {exc}"
    )
```

- [ ] **Step 3: Run, verify failure**

```bash
pytest tests/audit/test_fake_coord.py::test_observe_can_reference_describe_error_helper -v
```

Expected: FAIL with `NameError: name '_describe_error_or_none' is not defined`.

- [ ] **Step 4: Extend `_eval_globals` in `tools/state_machine_audit_fake_coord.py`**

Replace the `_eval_globals()` function body. Add imports for the 4 helpers from `sensor.py`:

```python
def _eval_globals() -> dict[str, Any]:
    """Globals that value_fn lambdas may reference (snapshot enums + private helpers)."""
    _ensure_ha_stubs()
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location,
        MowSession,
        CurrentActivity,
        PositioningHealth,
        Connectivity,
        RpcHealth,
    )
    # Private module-level helpers used in value_fn lambdas.
    # When these names appear in an entity's `value_fn` source, the audit
    # needs them in scope to invoke the lambda at cold-start.
    from custom_components.dreame_a2_mower.sensor import (
        _describe_error_or_none,
        _format_active_selection,
        _api_endpoints_value,
        _freshness_value,
    )

    return {
        "Location": Location,
        "MowSession": MowSession,
        "CurrentActivity": CurrentActivity,
        "PositioningHealth": PositioningHealth,
        "Connectivity": Connectivity,
        "RpcHealth": RpcHealth,
        "_describe_error_or_none": _describe_error_or_none,
        "_format_active_selection": _format_active_selection,
        "_api_endpoints_value": _api_endpoints_value,
        "_freshness_value": _freshness_value,
    }
```

- [ ] **Step 5: Run tests, verify pass**

```bash
pytest tests/audit/ -v 2>&1 | tail -10
```

Expected: all PASS, including the 2 new tests.

- [ ] **Step 6: Run audit, confirm yellow count drops**

```bash
python3 -m tools.state_machine_audit 2>&1 | tail -3
```

Expected: yellow count drops from 6 toward 0 (4 NameError yellows resolved; 2 "unclassified holder" yellows may persist — that's Task 2's concern).

- [ ] **Step 7: Commit**

```bash
git add tools/state_machine_audit_fake_coord.py tests/audit/test_fake_coord.py
git commit -m "feat(audit): inject sensor.py private helpers into value_fn eval scope"
```

---

## Task 2: Resolve remaining "unclassified holder" yellows

After Task 1, the NameError yellows clear, but 2 entities may still show `[YELLO] ... reboot   unclassified holder (other); manual review`. These have value_fns like `lambda coord: _api_endpoints_value(coord)` — `classify_holder()` sees no `.snapshot`, `.data`, or `cloud_state` markers and returns `"other"`, which `check_reboot` reports as YELLOW.

Two approaches:
- **A**: Extend `classify_holder` to inspect the helper function body (e.g. `_api_endpoints_value` reads `coord.cloud_client.*` → classify as cloud).
- **B**: Refine the entity's expectation to `idle: unavailable` + `reboot: unavailable_ok`, which forces GREEN in `check_reboot` regardless of holder. Accepts that helper-based entities are briefly Unknown post-boot.

**Pick approach B.** Approach A is more code; the entities in question are diagnostics whose brief-Unknown-after-boot is acceptable.

**Files:**
- Modify: `tools/state_machine_audit_expectations.yaml`

- [ ] **Step 1: Re-run audit, get the remaining yellow list**

```bash
python3 -m tools.state_machine_audit 2>&1 | grep "YELLO" | sort -u
```

You'll see remaining YELLOW rows. The 2 "unclassified holder" rows correspond to entities whose expectations are still `idle: persisted_value` + `reboot: required` (or similar) with a helper-based value_fn that `classify_holder` can't categorize.

- [ ] **Step 2: For each remaining YELLOW entity, refine YAML expectation**

Open `tools/state_machine_audit_expectations.yaml`. Find each affected entity (`sensor.active_selection`, `sensor.api_endpoints_supported`, plus any others showing yellow on reboot). Update to:

```yaml
sensor.api_endpoints_supported:
  holder: other
  idle: unavailable
  reboot: unavailable_ok
  note: "Diagnostic; value derived via _api_endpoints_value helper. Briefly Unknown after boot until cloud-client is ready."

sensor.active_selection:
  holder: other
  idle: unavailable
  reboot: unavailable_ok
  note: "Diagnostic; formats active_selection_{zones,spots,edge_contours} from MowerState. Briefly Unknown after boot."

# Add similar entries for any others
```

- [ ] **Step 3: Run audit, confirm 0 yellows**

```bash
python3 -m tools.state_machine_audit 2>&1 | tail -3
```

Expected: `0 yellow / 0 red`. Some YELLOW row may surface from entities whose `_idle:` literal expectation no longer matches the now-resolved value_fn output (i.e. the helper actually returns a non-None value at cold-start). Inspect each and decide:
- If the helper returns a stable cold-start value (like `0` or `False`), update YAML `idle:` to that literal
- If it returns None, leave as `unavailable`

- [ ] **Step 4: Run tests**

```bash
pytest tests/audit/ -v 2>&1 | tail -5
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add tools/state_machine_audit_expectations.yaml
git commit -m "data(audit): refine expectations for helper-based diagnostic entities"
```

---

## Task 3: Phase A verification

- [ ] **Step 1: Confirm 0 yellows**

```bash
python3 -m tools.state_machine_audit 2>&1 | tail -3
```

Expected line: `Summary: <X> green / 0 yellow / 0 red` (where X grew by ~6 from the prior 300 because each of the 6 previously-yellow check rows now resolves to GREEN).

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/integration 2>&1 | tail -5
```

Expected: green.

No commit — this is just verification. If any anomaly surfaces, fix before continuing to Phase B.

---

## Phase B — Class-attribute entity discovery (4 tasks)

## Task 4: Inventory class-attribute entities

Before changing code, build a manifest of class-attribute entities the audit currently misses.

- [ ] **Step 1: Grep for snapshot-reading entity classes**

```bash
grep -nE 'class.*Sensor.*\(_SnapshotEnumSensorBase|class.*Sensor.*\(_DreameA2PerMapSensorBase|_SNAPSHOT_FIELD|_attr_translation_key' custom_components/dreame_a2_mower/sensor.py | head -60
```

You'll find class definitions like:
- `DreameA2CurrentActivitySensor(_SnapshotEnumSensorBase)` with `_SNAPSHOT_FIELD = "current_activity"`, `_attr_translation_key = "current_activity"`
- `DreameA2LocationSensor(_SnapshotEnumSensorBase)`
- `DreameA2PositioningHealthSensor`
- `DreameA2MqttConnectivitySensor`
- `DreameA2MapNameSensor`, `MapAreaSensor`, etc. (per-map sensors via `_DreameA2PerMapSensorBase`)
- `DreameA2MapSessionAreaTotalSensor` etc.

- [ ] **Step 2: Identify all base classes that derive their value from class attributes**

Look for:
- `_SnapshotEnumSensorBase` — reads `getattr(snap, self._SNAPSHOT_FIELD)`
- `_DreameA2PerMapSensorBase` — reads per-map data via `_attr_translation_key`
- Any other class-attribute-driven base in `sensor.py`, `select.py`, `switch.py`

Check `select.py`:
```bash
grep -nE 'class.*Select|_SNAPSHOT_FIELD|_attr_translation_key' custom_components/dreame_a2_mower/select.py | head -20
```

- [ ] **Step 3: Write your findings as a quick inventory in the task report**

For each class-attribute entity, note:
- Class name (e.g. `DreameA2CurrentActivitySensor`)
- Base class (e.g. `_SnapshotEnumSensorBase`)
- `_attr_translation_key` (e.g. `"current_activity"`)
- `_SNAPSHOT_FIELD` (e.g. `"current_activity"`)
- File:line

This inventory drives Task 5.

No commit — this is investigation. Report findings.

---

## Task 5: Extend `discover_entities()` to find class-attribute entities

Now that the manifest is built, add an AST walker that finds class definitions matching the patterns and synthesizes `EntityDescriptor` entries.

**Files:**
- Modify: `tools/state_machine_audit_discover.py` — add `_discover_class_entities()` helper, fold into `discover_entities()`
- Test: `tests/audit/test_discover_class_entities.py`

- [ ] **Step 1: Write the failing test**

Create `tests/audit/test_discover_class_entities.py`:

```python
"""Tests for class-attribute entity discovery."""
from __future__ import annotations

from tools.state_machine_audit_discover import discover_entities


def test_discover_finds_current_activity():
    """The DreameA2CurrentActivitySensor class is keyed off _SNAPSHOT_FIELD; the
    audit must surface it as sensor.current_activity."""
    entities = discover_entities()
    keys = [(e.platform, e.key) for e in entities]
    assert ("sensor", "current_activity") in keys


def test_discover_finds_mower_location():
    entities = discover_entities()
    keys = [(e.platform, e.key) for e in entities]
    assert ("sensor", "mower_location") in keys


def test_discover_finds_positioning_health():
    entities = discover_entities()
    keys = [(e.platform, e.key) for e in entities]
    assert ("sensor", "positioning_health") in keys


def test_class_entity_has_synthetic_value_fn_src():
    """Class-attribute entities get a synthetic `value_fn_src` so check_idle
    can invoke them like any tuple-described entity."""
    entities = discover_entities()
    current = next(e for e in entities if e.platform == "sensor" and e.key == "current_activity")
    assert current.value_fn_src
    # Synthetic source should read coord.state_machine.snapshot().current_activity
    assert "state_machine.snapshot" in current.value_fn_src
    assert "current_activity" in current.value_fn_src
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/audit/test_discover_class_entities.py -v
```

Expected: tests fail because `discover_entities()` doesn't walk class definitions yet.

- [ ] **Step 3: Implement the class walker**

Add to `tools/state_machine_audit_discover.py`:

```python
# Bases that derive their entity value from class attributes:
_SNAPSHOT_FIELD_BASES = frozenset({
    "_SnapshotEnumSensorBase",
    # Add more when sensor.py grows new snapshot-attribute bases.
})


def _discover_class_attribute_entities(
    platform: str, tree: ast.Module, source: str
) -> list[EntityDescriptor]:
    """Find class-attribute-driven entities (e.g. _SnapshotEnumSensorBase subclasses)."""
    out: list[EntityDescriptor] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Match classes that subclass a known class-attribute base.
        base_names = {
            (b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else "")
            for b in node.bases
        }
        if not (base_names & _SNAPSHOT_FIELD_BASES):
            continue
        # Extract _SNAPSHOT_FIELD and _attr_translation_key class assignments.
        snapshot_field: str | None = None
        translation_key: str | None = None
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                    continue
                target = stmt.targets[0].id
                if not isinstance(stmt.value, ast.Constant) or not isinstance(stmt.value.value, str):
                    continue
                if target == "_SNAPSHOT_FIELD":
                    snapshot_field = stmt.value.value
                elif target == "_attr_translation_key":
                    translation_key = stmt.value.value
        if not snapshot_field or not translation_key:
            continue
        synthetic_src = (
            f"lambda coord: coord.state_machine.snapshot().{snapshot_field}"
        )
        out.append(
            EntityDescriptor(
                platform=platform,
                key=translation_key,
                name=None,
                value_fn_src=synthetic_src,
                source_file=f"custom_components/dreame_a2_mower/{platform}.py",
                line=node.lineno,
            )
        )
    return out
```

Now fold into `discover_entities()`. Find the existing function body and modify it:

```python
def discover_entities() -> list[EntityDescriptor]:
    """Discover all EntityDescription instances across platform modules."""
    out: list[EntityDescriptor] = []
    for platform in PLATFORMS:
        path = CCDIR / f"{platform}.py"
        source = path.read_text()
        tree = ast.parse(source)
        # Existing tuple discovery loop (preserved as-is)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # ... (existing logic that extracts EntityDescription tuples)
        # NEW: class-attribute discovery
        out.extend(_discover_class_attribute_entities(platform, tree, source))
    return out
```

Make sure the existing tuple-discovery loop is preserved exactly.

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/audit/test_discover_class_entities.py -v
```

Expected: 4 PASS.

Also run the broader audit test suite:
```bash
pytest tests/audit/ -v 2>&1 | tail -5
```

Expected: all PASS (existing tests should still work — the new walker is additive).

- [ ] **Step 5: Run audit, observe new entities surface**

```bash
python3 -m tools.state_machine_audit 2>&1 | grep -E "current_activity|mower_location|positioning_health|mqtt_connectivity"
```

Expected: 4 new entities appear. They'll likely have YELLOW rows because their expectations don't exist in YAML yet — that's Task 6's concern.

- [ ] **Step 6: Commit**

```bash
git add tools/state_machine_audit_discover.py tests/audit/test_discover_class_entities.py
git commit -m "feat(audit): discover class-attribute entities (_SnapshotEnumSensorBase subclasses)"
```

---

## Task 6: Add YAML expectations for newly-discovered entities

Class-attribute entities discovered in Task 5 lack expectations. Add them.

**Files:**
- Modify: `tools/state_machine_audit_expectations.yaml`

- [ ] **Step 1: Get the list of "no expectation declared" yellows after Task 5**

```bash
python3 -m tools.state_machine_audit 2>&1 | grep "no expectation declared" | head -30
```

You'll see entries like `sensor.current_activity`, `sensor.mower_location`, etc.

- [ ] **Step 2: Add expectations**

Open `tools/state_machine_audit_expectations.yaml` and add entries for each. The rubric:

- `sensor.current_activity`: snapshot-backed, idle is `"idle"` (the cold-start CurrentActivity), reboot required:
  ```yaml
  sensor.current_activity:
    holder: snapshot
    idle: "idle"
    reboot: required
    note: "Snapshot.current_activity starts at IDLE (initial); persisted via Store."
  ```

- `sensor.mower_location`: snapshot-backed, idle is `"at_dock"`:
  ```yaml
  sensor.mower_location:
    holder: snapshot
    idle: "at_dock"
    reboot: required
    note: "Snapshot.location starts at AT_DOCK (initial); persisted via Store."
  ```

- `sensor.positioning_health`: snapshot-backed, idle is `"localized"`:
  ```yaml
  sensor.positioning_health:
    holder: snapshot
    idle: "localized"
    reboot: required
    note: "Snapshot.positioning_health starts at LOCALIZED (initial)."
  ```

- `sensor.mqtt_connectivity`: snapshot-backed, idle is `"stale"` + reboot `unavailable_ok` (correct initial is STALE):
  ```yaml
  sensor.mqtt_connectivity:
    holder: snapshot
    idle: "stale"
    reboot: unavailable_ok
    note: "Initial state is STALE until first heartbeat; that's correct."
  ```

For per-map entities (`map_name`, `map_area`, etc., if Task 5 picks them up): these are per-map-keyed and probably need `holder: cloud_state` or `holder: other` since they read from cloud data. Use `idle: unavailable` + `reboot: unavailable_ok`.

If Task 5's discovery surfaces more class-attribute entities than expected, add expectations for each per the same rubric.

- [ ] **Step 3: Run audit, confirm all newly-discovered entities GREEN**

```bash
python3 -m tools.state_machine_audit 2>&1 | tail -3
```

Expected: yellow count = 0; red count = 0; green count grew by however many entities Task 5 added.

If any of the new entities show RED idle (because the synthetic value_fn returns something different from the literal expectation), inspect — the cold-start value of the snapshot field at `StateSnapshot.initial()` is the source of truth. Adjust YAML or accept literal as expected.

- [ ] **Step 4: Run tests**

```bash
pytest tests/audit/ -v 2>&1 | tail -5
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add tools/state_machine_audit_expectations.yaml
git commit -m "data(audit): seed expectations for class-attribute entities"
```

---

## Task 7: Phase B verification

- [ ] **Step 1: Final Phase B audit**

```bash
python3 -m tools.state_machine_audit 2>&1 | tail -3
```

Expected: 0 yellow, 0 red. Green count higher than baseline.

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/integration 2>&1 | tail -5
```

Expected: green.

---

## Phase C — Orphan field pruning (4 tasks)

## Task 8: Recount orphans after Phase B

Class-attribute discovery in Phase B should reduce the orphan count because newly-discovered entities reference fields like `current_activity`. Re-run orphan detection.

- [ ] **Step 1: List remaining orphans**

```bash
python3 -m tools.state_machine_audit 2>&1 | grep -A 100 "^Orphan MowerState" | head -60
```

OR equivalently:

```bash
python3 -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests'); import conftest
from tools.state_machine_audit_discover import discover_entities
from tools.state_machine_audit_checks import find_orphan_fields
es = discover_entities()
orphans = find_orphan_fields(es)
print(f'Total: {len(orphans)}')
for f in sorted(orphans): print(f'  {f}')
"
```

Count and list the orphans. Compare against the pre-Phase-B baseline of 54. If the count dropped (e.g. to 45), that's expected; class-attribute entities now reference some previously-orphan fields.

Report the new orphan count and list.

No commit — investigation only.

---

## Task 9: Investigate each orphan; categorize

For each orphan field, determine whether it's truly unused or read by code the audit can't see.

- [ ] **Step 1: For each orphan, run a targeted grep**

```bash
for field in <list-of-orphans>; do
  count=$(grep -rE "\\b${field}\\b" custom_components/dreame_a2_mower/ --include='*.py' | grep -v '__pycache__' | wc -l)
  echo "${count}: ${field}"
done
```

Save the output. Fields with `count <= 2` (just the dataclass declaration + initialization) are strong prune candidates. Fields with `count > 5` are likely actively used internally.

- [ ] **Step 2: Categorize the orphans into three buckets**

Manually walk the grep output and categorize:

- **Bucket P (prune)** — fields with zero non-declaration readers. Safe to delete.
- **Bucket I (internal)** — fields read by coordinator / mower / archive / live_map code but no entity tuple. Keep + document.
- **Bucket D (DeviceInfo / future)** — fields surfaced via DeviceInfo or kept for upcoming work. Keep + document.

Record each orphan into one of the buckets. The output of this task is a categorized list, used by Task 10.

No commit — investigation only.

---

## Task 10: Prune Bucket P; document Buckets I and D

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py` — delete fields in Bucket P
- Create: `docs/research/state-machines/orphan-fields.md` — categorized doc

- [ ] **Step 1: Delete Bucket P fields**

For each field in Bucket P, delete its declaration in `state.py`. Use Edit. The field declarations are lines like:

```python
    pending_session_attempt_count: int = 0
```

Delete the whole line. After all deletions, run:

```bash
grep -nE 'pending_session_attempt_count' custom_components/dreame_a2_mower/ -r --include='*.py' | grep -v __pycache__
```

Expected: no references remain (or only in commented-out code).

- [ ] **Step 2: Create `docs/research/state-machines/orphan-fields.md`**

Document the remaining orphans (Buckets I and D). Structure:

```markdown
# MowerState orphan fields

Fields declared in `MowerState` (`custom_components/dreame_a2_mower/mower/state.py`) that are not read by any audit-discovered entity. After pruning the truly-unused fields, the remaining orphans fall into two categories.

## Bucket I — Read internally (no entity surface)

These fields are written or read by coordinator code, archive code, live_map code, or other internal modules but never surfaced as an HA entity.

| Field | Used by |
|---|---|
| `cloud_connected` | `coordinator.py` — status reporting |
| `firmware_version` | `_devices.py` — DeviceInfo |
| `hardware_serial` | `_devices.py` — DeviceInfo |
| `pending_session_*` | `coordinator._restore_in_progress`, archive code |
| `session_started_unix` | `live_map`, archive code |
| `settings_*` | `switch.py` / `number.py` / `select.py` — CFG-backed setting writes |
| `wifi_map_data` | `wifi_archive_store.py` — heatmap archive |
| ... | ... |

Each entry should name the consumer file. The audit verifier may still list these as "orphan" because its detection is entity-tuple-only.

## Bucket D — DeviceInfo / future

Fields surfaced via HA's `DeviceInfo` (not as entities) or kept for upcoming features.

| Field | Reason |
|---|---|
| `firmware_version`, `hardware_serial`, `manufacturer`, ... | Surfaced via `DeviceInfo`; populated on first cloud-info fetch. |
| `position_north_m`, `position_east_m` | No live writer yet — kept for GPS-frame extension. |
| ... | ... |
```

Fill in actual entries from your Task 9 categorization.

- [ ] **Step 3: Run audit, confirm orphan count dropped**

```bash
python3 -m tools.state_machine_audit 2>&1 | tail -5
```

Expected: orphan count drops by the size of Bucket P. The remaining orphans (Buckets I + D) are documented and acceptable.

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/integration 2>&1 | tail -10
```

Expected: green. If anything fails, the field you deleted was actually read by some test or internal code — restore it and move that field to Bucket I.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state.py docs/research/state-machines/orphan-fields.md
git commit -m "chore(state): prune unused MowerState fields; document remaining orphans"
```

---

## Task 11: Phase C verification

- [ ] **Step 1: Final audit**

```bash
python3 -m tools.state_machine_audit 2>&1 | tail -5
```

Expected: 0 yellow, 0 red, orphan count = size(Bucket I) + size(Bucket D).

- [ ] **Step 2: Run full tests**

```bash
pytest tests/ -v --ignore=tests/integration 2>&1 | tail -5
```

- [ ] **Step 3: Update `docs/research/state-machines/initial-audit.txt`**

```bash
python3 -m tools.state_machine_audit \
  --write-doc3 docs/research/state-machines/entity-sources.md \
  > docs/research/state-machines/initial-audit.txt
echo "exit=$?"
```

Expected: exit=0 (all green).

- [ ] **Step 4: Update README post-remediation section**

In `docs/research/state-machines/README.md`, update the post-remediation section with the new numbers:

```markdown
## Post-remediation + follow-ups (2026-05-14)

After the remediation plan + follow-up plan landed:

- Summary: <NEW>  green / 0 yellow / 0 red + <NEW>  orphan MowerState fields (documented in [`orphan-fields.md`](orphan-fields.md))
- Yellow cleanup: audit eval scope extended to resolve private module helpers
- Class-attribute discovery: `_SnapshotEnumSensorBase` subclasses (current_activity, mower_location, etc.) now in audit
- Orphan pruning: <N>  fields deleted from `MowerState`; remaining orphans categorized as internal-use or DeviceInfo-only
```

Fill in the actual numbers.

- [ ] **Step 5: Commit**

```bash
git add docs/research/state-machines/initial-audit.txt \
        docs/research/state-machines/entity-sources.md \
        docs/research/state-machines/README.md
git commit -m "docs(state): all-green post-follow-ups baseline"
```

---

## Phase D — Release (1 task)

## Task 12: Cut release

- [ ] **Step 1: Run the release script**

```bash
./tools/release.sh --notes "$(cat <<'EOF'
State machine audit follow-ups: audit verifier now fully green.

- Yellow cleanup: eval scope extended to private module helpers (_describe_error_or_none, _format_active_selection, _api_endpoints_value, _freshness_value) — resolves the 4 NameError yellows
- Class-attribute entity discovery: audit now walks _SnapshotEnumSensorBase subclasses, surfacing sensor.current_activity, sensor.mower_location, sensor.positioning_health, sensor.mqtt_connectivity, and per-map entities
- Orphan field cleanup: unused MowerState fields pruned; remaining orphans documented in docs/research/state-machines/orphan-fields.md as internal-use or DeviceInfo-only

No functional changes to integration runtime; this is audit-tool + dead-code cleanup. Verifier now serves as a clean regression gate (exit 0 on all-green).
EOF
)"
```

Expected: tag pushed, GitHub Release created, HACS refresh triggered.

- [ ] **Step 2: Verify the release**

```bash
gh release view --json tagName,isLatest,isPrerelease,isDraft
```

Expected: `isLatest=true, isPrerelease=false, isDraft=false`.

- [ ] **Step 3: Report back**

Include release URL, version, audit summary, orphan count.

---

## Self-review

Mapped each follow-up to tasks:
- **Yellow cleanup** → Tasks 1, 2, 3 (Phase A)
- **Class-attribute discovery** → Tasks 4, 5, 6, 7 (Phase B)
- **Orphan pruning** → Tasks 8, 9, 10, 11 (Phase C)
- **Release** → Task 12 (Phase D)

Type consistency: `_discover_class_attribute_entities` returns `list[EntityDescriptor]` consistent with the existing `discover_entities`. `_SNAPSHOT_FIELD_BASES` is a frozenset and extensible if new bases appear.

No placeholders. Tasks 4, 8, 9 are exploration tasks (no code changes); they output information used by subsequent tasks. Tasks 1, 5, 10 are code TDD tasks. Tasks 2, 6 are YAML data entry. Tasks 3, 7, 11 are verification. Task 12 is release.

Open items NOT in this plan (deferred):
- **Audit harness load_persisted fixture** — would let snapshot-backed entities use `idle: persisted_value` instead of `idle: unavailable`. Cosmetic; current YAML notes document the workaround.
- **Additional class-attribute base classes** — if `select.py`, `switch.py`, or `number.py` have similar `_attr_translation_key`-based bases, Task 5's `_SNAPSHOT_FIELD_BASES` set can grow. Discoverable via grep; defer until they actually exist.
