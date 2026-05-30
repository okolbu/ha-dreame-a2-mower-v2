# Entity-inventory comprehensive port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `custom_components/dreame_a2_mower/entity-inventory.yaml` the comprehensive entity source-of-truth — one code-verified entry per entity class (~97, currently 22) — then retire the stale `docs/research/entity-validation-matrix.md`.

**Architecture:** A coverage-gate audit (`tools/entity_inventory_audit.py`) enumerates entity classes from the platform files and asserts each has an `entity-inventory.yaml` entry; it starts RED (~75 missing) and each platform-batch task drives it toward green. Entries are derived by **reading the current code**, never by transcribing the 3-week-stale matrix (the matrix is a *hint* for write-outcome history only; every read-source / write-path claim is re-checked against code). The gate then becomes a permanent CI guard enforcing the CLAUDE.md "new entity → inventory it" rule.

**Tech Stack:** Python 3.13 (`.venv-vanilla`), pytest, PyYAML, GitHub Actions (`inventory-touch-gate`).

---

## Methodology (read before any task)

**The anti-staleness rule (load-bearing).** The matrix (`entity-validation-matrix.md`) is frozen at 2026-05-11 and its own banner admits many rows were first-pass hypotheses. Treat it as a *lead*, not truth:
- **read source / state_path / write_path** → derive from the CURRENT platform file + the coordinator/state code it reads. Never copy these from the matrix.
- **write-outcome history** (e.g. "setDeviceData accepts but device ignores; cloud-cache-only") → the matrix may hold a hard-won finding worth preserving; port it only as a `verifications:` entry with `status: presumed` UNLESS you can re-confirm it against `inventory.yaml` / a probe log / code, in which case cite that evidence.
- When code and matrix disagree, **code wins** and you note the correction.

**Status-tier rule** (matches CLAUDE.md fact-discipline):
- `verified` — you can cite live evidence (a test, a probe log, a screenshot, or code that unambiguously wires the source).
- `presumed` — the wiring is read from code but never confirmed end-to-end on a live device. **Most ported entries will be `presumed`** — that is correct and honest. Do NOT mark `verified` without evidence.
- `seen_working:` in `status:` is `true` ONLY for entities with a live-confirmed verification; default `false`.

**Per entry, derive each field from code:**
- `id`: `<platform>.<unique_id_suffix>`. For per-map entities use the `_N_` convention (e.g. `switch.dreame_a2_mower_map_N_edgemaster`) — read the suffix from `_attr_unique_id` / `map_unique_id(coordinator, map_id, "<key>")`.
- `platform`: the HA domain.
- `class` / `class_file`: the Python class name + `path:line`.
- `device`: `parent` (uses `mower_device_info`), `per-map` (uses `map_device_info` / loops `maps_by_id`), or `sub-device`.
- `source.wire`: the `inventory.yaml` surface-key the value comes from (siid/piid, CFG key, SETTINGS field, OSS summary field, or "rendered from …"). Cross-cite the `inventory.yaml` id in `references.wire_entry`.
- `source.state_path`: the runtime read path (e.g. `MowerState.<field>`, `coordinator.cloud_state.settings.by_map_id_canonical[map_id]["<field>"]`, `state_machine.snapshot.<field>`).
- `write_path`: `read-only`, or the write surface (`coordinator.write_settings(..., "<field>")`, `set_cfg`, routed-action op, `dispatch_action`, etc.) read from the entity's `async_turn_on`/`set_*`/`async_select_option` methods.
- `references.code`: `path:line`.
- `notes`: only when something non-obvious needs saying.

**Worked example** (port of an existing switch — use as the template shape):

```yaml
  - id: "switch.dreame_a2_mower_map_N_edgemaster"
    platform: switch
    class: "DreameA2EdgeMasterSwitch"
    class_file: "custom_components/dreame_a2_mower/switch_global.py:<line>"
    device: per-map
    source:
      wire: "SETTINGS.entry0.<map>.edgeMaster"
      state_path: "coordinator.cloud_state.settings.by_map_id_canonical[map_id]['edgeMaster'] → MowerState via property_mapping"
    write_path: "coordinator.write_settings(map_id, field='edgeMaster', value=int) → setDeviceData chunked-batch"
    status:
      seen_working: false
      last_verified: "2026-05-31"
    verifications:
      - date: "2026-05-31"
        status: presumed
        claim: "Reads edgeMaster from per-map SETTINGS; writes via write_settings→setDeviceData. Wiring read from switch_global.py + coordinator/_writes.py; not re-confirmed live this pass."
        evidence: "custom_components/dreame_a2_mower/switch_global.py (async_turn_on/off → write_settings 'edgeMaster')"
    references:
      wire_entry: "SETTINGS_edgeMaster"
      code: "custom_components/dreame_a2_mower/switch_global.py:<line>"
```

**Process per task:** read the platform file(s) → for each entity class, read its read-property + write-method → write the entry → run the audit (Task 1 tool) filtered to that platform → confirm those classes are no longer "missing" → run the full test suite → commit. Batch-commit per platform (one commit per task).

**Test command:** `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest` (system python is broken). **Commit by explicit path** (a 2nd process commits concurrently — never `git add -A`).

---

### Task 1: Coverage-gate audit + test (the red→green target)

**Files:**
- Create: `tools/entity_inventory_audit.py`
- Test: `tests/inventory/test_entity_inventory_coverage.py`
- Modify: `.github/workflows/ci.yml` (add the audit to the inventory gate)

- [ ] **Step 1: Write the audit tool**

`tools/entity_inventory_audit.py` — enumerate entity classes from the platform files, compare to `class:` values in `entity-inventory.yaml`, print + exit non-zero on any gap.

```python
#!/usr/bin/env python3
"""Entity-inventory coverage gate.

Every concrete HA entity class in the platform files must have an entry in
entity-inventory.yaml (matched by `class:`). Base/mixin classes are exempt via
_EXEMPT. Exits non-zero (and prints the missing classes) when coverage is
incomplete — wired into CI so a new entity can't ship un-inventoried.
"""
from __future__ import annotations
import ast
import pathlib
import sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components" / "dreame_a2_mower"
INV = CC / "entity-inventory.yaml"

# Platform files whose DreameA2* entity classes are user-facing entities.
PLATFORM_GLOBS = [
    "switch*.py", "sensor*.py", "select*.py", "number*.py",
    "binary_sensor*.py", "button*.py", "device_tracker*.py", "event*.py",
    "lawn_mower*.py", "calendar*.py", "camera*.py", "_camera_*.py",
    "_sensor_*.py",
]

# Base/mixin/abstract classes that are never instantiated as their own entity.
_EXEMPT: set[str] = {
    # fill during Task 1 as the audit surfaces non-entity base classes,
    # e.g. "DreameA2MapSettingSelectBase", "_DreameA2BaseEntity"
}

# HA entity base-class name fragments — a class is an "entity" if any of its
# bases (by simple name) contains one of these.
_ENTITY_BASE_HINTS = (
    "Entity", "SwitchEntity", "SensorEntity", "SelectEntity", "NumberEntity",
    "BinarySensorEntity", "ButtonEntity", "Camera", "TrackerEntity",
    "EventEntity", "LawnMowerEntity", "CalendarEntity",
)


def _entity_classes() -> dict[str, str]:
    """class name -> 'relpath:line' for every concrete entity class."""
    found: dict[str, str] = {}
    seen: set[pathlib.Path] = set()
    for glob in PLATFORM_GLOBS:
        for path in CC.glob(glob):
            if path in seen:
                continue
            seen.add(path)
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not node.name.startswith("DreameA2"):
                    continue
                base_names = " ".join(
                    b.id if isinstance(b, ast.Name)
                    else (b.attr if isinstance(b, ast.Attribute) else "")
                    for b in node.bases
                )
                if not any(h in base_names for h in _ENTITY_BASE_HINTS):
                    # Not obviously an entity (e.g. a dataclass/helper) — skip.
                    # If a real entity is missed here, add its base hint above.
                    continue
                if node.name in _EXEMPT:
                    continue
                found[node.name] = f"{path.relative_to(ROOT)}:{node.lineno}"
    return found


def _inventoried_classes() -> set[str]:
    data = yaml.safe_load(INV.read_text())
    out: set[str] = set()
    for e in (data.get("entities") or []):
        c = e.get("class")
        if c:
            out.add(c)
    return out


def main() -> int:
    classes = _entity_classes()
    inv = _inventoried_classes()
    missing = sorted(c for c in classes if c not in inv)
    extra = sorted(c for c in inv if c not in classes)
    print(f"entity classes in code: {len(classes)}")
    print(f"classes inventoried:    {len(inv)}")
    print(f"missing from inventory:  {len(missing)}")
    for c in missing:
        print(f"  MISSING  {c}  ({classes[c]})")
    for c in extra:
        print(f"  STALE    {c}  (in inventory, not in code)")
    return 1 if (missing or extra) else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it — expect RED with the missing list**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python tools/entity_inventory_audit.py`
Expected: non-zero exit, "missing from inventory: ~75", a printed MISSING list. **Capture this list — it is the work-list for Tasks 2-9.** If any base/mixin class shows up as MISSING, add it to `_EXEMPT` and re-run until only real entities remain.

- [ ] **Step 3: Write the coverage test**

`tests/inventory/test_entity_inventory_coverage.py`:

```python
"""entity-inventory.yaml must cover every concrete entity class in code."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_entity_inventory_is_complete():
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "entity_inventory_audit.py")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        "entity-inventory.yaml is missing entries:\n" + r.stdout
    )
```

- [ ] **Step 4: Run the test — expect FAIL (xfail-mark until the port completes)**

Run: `/data/claude/homeassistant/.venv-vanilla/bin/python -m pytest tests/inventory/test_entity_inventory_coverage.py -v`
Expected: FAIL. Mark it `@pytest.mark.xfail(reason="entity-inventory port in progress — Task 10 flips this", strict=True)` so the suite stays green during the port; **remove the xfail in Task 10** when coverage hits 100%.

- [ ] **Step 5: Commit**

```bash
git add tools/entity_inventory_audit.py tests/inventory/test_entity_inventory_coverage.py
git commit -m "feat(audit): entity-inventory coverage gate (xfail until port done)"
```

(CI wiring is added in Task 10 once the gate is green, to avoid breaking CI mid-port.)

---

### Tasks 2-9: per-platform port batches

Each task ports all the MISSING classes for one platform (from Task 1's list). Same step shape; the per-entity YAML content is produced by reading the code per the Methodology. **Do not transcribe matrix rows.**

For every batch task, the steps are:

- [ ] **Step 1: List the platform's missing classes**
  Run: `… tools/entity_inventory_audit.py | grep -iE "<platform>"` — this is the batch's checklist.
- [ ] **Step 2: For each missing class, read its code and append an entry**
  Read the entity class (read-property + write-method) and the coordinator/state read path it uses; append a schema-complete entry to `entity-inventory.yaml` under the right section, following the worked example. Status `presumed`, `seen_working: false`, `last_verified: "2026-05-31"`, with a `verifications:` line citing the code wiring. Promote to `verified` only with real evidence.
- [ ] **Step 3: Re-run the audit — those classes no longer MISSING**
  Run: `… tools/entity_inventory_audit.py | grep -c MISSING` — count drops by the batch size.
- [ ] **Step 4: YAML + suite still parse/pass**
  Run: `… -c "import yaml; yaml.safe_load(open('custom_components/dreame_a2_mower/entity-inventory.yaml'))"` then `… -m pytest -q`.
- [ ] **Step 5: Commit** (`git add custom_components/dreame_a2_mower/entity-inventory.yaml && git commit -m "docs(entity-inventory): port <platform> entities (code-verified)"`)

Batches (sized so each fits one subagent context; split sensor if needed):

- **Task 2 — switch** (`switch.py`, `switch_global.py`, `switch_map.py`; ~9 classes). Reads/writes: per-map SETTINGS via `write_settings`, CFG keys via `set_cfg`, AI bits. Cross-ref `inventory.yaml` SETTINGS_* / CFG.* ids.
- **Task 3 — number** (`number.py`; ~12). VOL/CFG ints + SETTINGS numbers (mowing height, cutter position, sensitivity, distance, trail render width).
- **Task 4 — binary_sensor** (`binary_sensor.py`; ~2 + the human-presence scenario set already partly present). s1p1 bits / REC / state_machine.
- **Task 5 — button** (`button.py`; ~11). Each maps to a routed-action / dispatch_action op; record the op + whether it's confirmed-working (e.g. start/pause/dock) vs returns-error (e.g. request_wifi_map 80001, lock op=12).
- **Task 6 — select** (`select.py`, `select_global.py`, `select_map_settings.py`; ~14). Action-mode picker, work-log picker, wifi-archive picker, per-map SETTINGS selects.
- **Task 7 — sensor (device + global)** (`sensor.py`, `sensor_device.py`; subset). Battery/charging/state/diagnostic/picked-session sensors.
- **Task 8 — sensor (map + session)** (`sensor_map.py`, `sensor_session.py`; subset). Per-map area/zone/spot/maintenance-point + per-session totals.
- **Task 9 — camera + device_tracker + event + lawn_mower + calendar** (`_camera_*.py`, `device_tracker.py`, `event.py`, `lawn_mower.py`, `calendar.py`; ~10). Cameras render-only; device_tracker LOCN sentinel (cite the GPS gap); event entities (lifecycle + notification — already partly present); lawn_mower projection from state_machine; calendar from session archive.

---

### Task 10: Retire the matrix + flip the gate green

**Files:**
- Delete (move to OLD): `docs/research/entity-validation-matrix.md`
- Modify: `tests/inventory/test_entity_inventory_coverage.py` (remove xfail)
- Modify: `.github/workflows/ci.yml` (add the audit to the gate)
- Modify: `docs/research/README.md`, `README.md`, `docs/TODO.md` (repoint the matrix refs)

- [ ] **Step 1: Confirm the gate is green**
  Run: `… tools/entity_inventory_audit.py; echo $?` → `0`, "missing: 0", "STALE: 0". Fix any STALE (a `class:` in inventory not in code = a removed entity left behind → delete that entry).
- [ ] **Step 2: Remove the xfail mark** from `test_entity_inventory_coverage.py`; run it → PASS.
- [ ] **Step 3: Archive the matrix**
  ```bash
  OLD=/data/claude/homeassistant/OLD/ha-dreame-a2-mower-docs/research
  cp -a docs/research/entity-validation-matrix.md "$OLD/entity-validation-matrix.md"
  git rm -q docs/research/entity-validation-matrix.md
  ```
- [ ] **Step 4: Repoint references** — in `docs/research/README.md` drop the "AUTHORITATIVE" matrix row and point entity questions at `entity-inventory.yaml`; in `README.md` and `docs/TODO.md` change the matrix cross-refs to `entity-inventory.yaml` (or the OLD path for pure provenance). Re-grep: `grep -rn "entity-validation-matrix" --include=*.md --include=*.py . | grep -v OLD/` should return only mirror-resolvable code breadcrumbs.
- [ ] **Step 5: Wire CI gate** — add to `.github/workflows/ci.yml` inventory job:
  ```yaml
        - name: Entity-inventory coverage
          run: python tools/entity_inventory_audit.py
  ```
- [ ] **Step 6: Full suite + commit**
  Run: `… -m pytest -q` (expect baseline + the now-passing coverage test).
  ```bash
  git add custom_components/dreame_a2_mower/entity-inventory.yaml tools/entity_inventory_audit.py tests/inventory/test_entity_inventory_coverage.py .github/workflows/ci.yml docs/research/README.md README.md docs/TODO.md
  git commit -m "docs(entity-inventory): complete the port; retire entity-validation-matrix"
  ```

---

## Self-review notes

- **Coverage:** Tasks 2-9 cover every platform glob the audit scans (switch/sensor/select/number/binary_sensor/button/camera/device_tracker/event/lawn_mower/calendar). Task 1's MISSING list is the authoritative work-list; if a class isn't in any batch, it still shows MISSING and Task 10's gate blocks completion — so nothing can be silently dropped.
- **Anti-staleness:** every task's Step 2 says derive-from-code, status `presumed` unless evidenced; the matrix is hint-only. This is the whole point of the port.
- **Per-map ids:** use the `_N_` convention (one entry per class, not per expanded map entity).
- **No new wire facts:** this is an entity-handling port; it touches `entity-inventory.yaml`, not `inventory.yaml`. If a port step uncovers a *wire* correction, record it in `inventory.yaml` per fact-discipline (separate concern).
