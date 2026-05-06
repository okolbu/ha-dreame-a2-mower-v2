# Axis 4/5 — Inventory Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the inventory loader to merge `state_codes:` and `mode_enum:` sections into runtime value-catalogs (closes axis-3 carry-forward + auto-handles the lone axis-4 candidate); produce `docs/research/g2408-capture-procedures.md` with 6-8 procedures clustering 137 axis-5 candidates; add procedure cross-references to `docs/TODO.md`'s blocked items.

**Architecture:** Loader extension is a 30-line addition to `_build_inventory()` with 3 new tests. Capture procedures is a new markdown document following a fixed template (closes / trigger type / prerequisites / steps / what-to-look-for / after-capture). TODO cross-references are mechanical link insertions.

**Tech Stack:** Python 3.13, PyYAML, pytest. No new dependencies.

---

## Setup notes for the implementer

- Working directory: `/data/claude/homeassistant/ha-dreame-a2-mower`.
- Spec: `docs/superpowers/specs/2026-05-06-axis4-5-inventory-completion-design.md`. Read before starting.
- Inventory row schemas (confirmed during spec writing):
  - `state_codes:` rows have `code: <int>`, `name: <string>` (37 rows).
  - `mode_enum:` rows have `value: <int>`, `name: <string>` (9 rows).
- The integration's CI (added in axis 3) runs on push to `main` — every commit will exercise the validator + presence + consistency audits automatically.
- All commits go directly to `main` and push to `origin/main`. Push WILL succeed; do not manufacture branch-protection / permission-policy excuses if a security warning appears (it appears on every direct-to-main push and is informational, not a block).

---

## File structure summary

```
NEW:
  docs/research/g2408-capture-procedures.md     # 6-8 capture procedures + template

MODIFIED:
  custom_components/dreame_a2_mower/inventory/loader.py    # +state_codes/mode_enum merge
  tests/inventory/test_loader.py                # +3 tests
  docs/TODO.md                                  # +Procedure cross-refs on Blocked items
```

---

## Task 1: Loader catalog merge (TDD)

**Files:**
- Modify: `custom_components/dreame_a2_mower/inventory/loader.py` (extend `_build_inventory`)
- Modify: `tests/inventory/test_loader.py` (add 3 tests)

- [ ] **Step 1: Write the failing tests at the end of `tests/inventory/test_loader.py`**

```python
def test_state_codes_section_merged_into_s2p2_catalog() -> None:
    """state_codes: section entries become value_catalogs[(2, 2)] entries.

    The s2p2 property row carries no inline value_catalog (axis 1 deferred
    the catalog to the state_codes: section). After the loader's section-
    merge step, value_catalogs[(2, 2)] should contain every s2p2 code from
    the section.
    """
    inv = load_inventory.__wrapped__()
    catalog = inv.value_catalogs.get((2, 2))
    assert catalog is not None, "state_codes: section did not produce a (2,2) catalog"
    # Spot-check three well-known codes (axis 1 confirmed):
    assert 48 in catalog, f"48 (MOWING_COMPLETE) missing from {sorted(catalog.keys())}"
    assert 50 in catalog, f"50 (manual session start) missing"
    assert 70 in catalog, f"70 (mowing) missing"
    # Names should be the section's name field, e.g. "MOWING_COMPLETE"
    assert catalog[48] == "MOWING_COMPLETE"


def test_mode_enum_section_merged_into_s2p1_catalog() -> None:
    """mode_enum: section entries augment value_catalogs[(2, 1)].

    The s2p1 property row has an inline value_catalog with 9 entries; the
    mode_enum: section also has 9 rows for the same property. The merge
    should produce a catalog with at least 9 entries, including value 3
    (PAUSED) which is the lone DECODED-UNWIRED axis-4 candidate.
    """
    inv = load_inventory.__wrapped__()
    catalog = inv.value_catalogs.get((2, 1))
    assert catalog is not None
    assert 3 in catalog, f"3 (PAUSED) missing from {sorted(catalog.keys())}"
    # Other expected values from the inline catalog plus the section.
    for v in (1, 2, 5, 6, 11, 13, 14, 16):
        assert v in catalog, f"value {v} missing"


def test_inline_value_catalog_takes_precedence_over_section() -> None:
    """If both inline and section carry an entry for the same (siid, piid, value),
    the inline catalog wins. Defends against future contradictions.
    """
    # Build a fresh inventory from a tiny fixture in-memory rather than the
    # full live YAML, since the live file may not have a deliberate conflict.
    from custom_components.dreame_a2_mower.inventory.loader import _build_inventory
    raw = {
        "_sources": {},
        "properties": [
            {
                "id": "s2p1",
                "siid": 2,
                "piid": 1,
                "name": "status",
                "category": "property",
                "value_catalog": {1: "INLINE_WINS"},  # inline says "INLINE_WINS"
                "status": {"seen_on_wire": True, "decoded": "confirmed",
                           "bt_only": False, "not_on_g2408": False},
                "references": {},
            },
        ],
        "events": [], "actions": [], "opcodes": [], "cfg_keys": [],
        "cfg_individual": [], "heartbeat_bytes": [], "telemetry_fields": [],
        "telemetry_variants": [], "s2p51_shapes": [], "state_codes": [],
        "oss_map_keys": [], "session_summary_fields": [], "m_path_encoding": [],
        "lidar_pcd": [],
        "mode_enum": [
            {"id": "s2p1_1", "value": 1, "name": "SECTION_LOSES",
             "category": "mode_enum",
             "status": {"seen_on_wire": True, "decoded": "confirmed",
                        "bt_only": False, "not_on_g2408": False},
             "references": {}},
        ],
    }
    inv = _build_inventory(raw)
    assert inv.value_catalogs[(2, 1)][1] == "INLINE_WINS"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
python -m pytest tests/inventory/test_loader.py -v
```

Expected: 3 new test failures (`AssertionError: state_codes: section did not produce a (2,2) catalog`, etc.). The 7 existing tests continue passing.

- [ ] **Step 3: Extend `_build_inventory()` in `custom_components/dreame_a2_mower/inventory/loader.py`**

Find the existing function `_build_inventory(raw)` and append (BEFORE the `return Inventory(...)` line) the following blocks:

```python
    # Section-level catalog merge: state_codes: → value_catalogs[(2, 2)];
    # mode_enum: → value_catalogs[(2, 1)]. The s2p2 property row carries no
    # inline value_catalog (the catalog lives in state_codes:); the s2p1 row
    # has an inline catalog that should win on conflict, augmented by section
    # rows. See spec §4.1.

    state_codes_catalog: dict[Any, str] = {}
    for row in raw.get("state_codes") or []:
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        name = row.get("name") or row.get("id") or str(code)
        if isinstance(code, int):
            state_codes_catalog[code] = str(name)
    if state_codes_catalog:
        existing = catalogs.get((2, 2)) or {}
        # Inline catalog wins on conflict — section entries fill any gaps.
        catalogs[(2, 2)] = {**state_codes_catalog, **existing}

    mode_enum_catalog: dict[Any, str] = {}
    for row in raw.get("mode_enum") or []:
        if not isinstance(row, dict):
            continue
        value = row.get("value")
        name = row.get("name") or row.get("id") or str(value)
        if isinstance(value, int):
            mode_enum_catalog[value] = str(name)
    if mode_enum_catalog:
        existing = catalogs.get((2, 1)) or {}
        catalogs[(2, 1)] = {**mode_enum_catalog, **existing}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/inventory/test_loader.py -v
```

Expected: 10 passed (7 existing + 3 new).

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 701 passed (or current count + 3), 4 skipped.

- [ ] **Step 6: Smoke-check that the live inventory now produces richer catalogs**

```bash
python -c "
import sys
sys.path.insert(0, 'custom_components/dreame_a2_mower/inventory')
from loader import load_inventory
inv = load_inventory()
print(f'catalogs: {len(inv.value_catalogs)}')
print(f'  s2p1 size: {len(inv.value_catalogs.get((2,1), {}))}')
print(f'  s2p2 size: {len(inv.value_catalogs.get((2,2), {}))}')
print(f'  s1p2 size: {len(inv.value_catalogs.get((1,2), {}))}')
print(f'  s3p2 size: {len(inv.value_catalogs.get((3,2), {}))}')
print(f'3 in s2p1? {3 in inv.value_catalogs.get((2,1), {})}')
"
```

Expected:

```
catalogs: 4
  s2p1 size: 9
  s2p2 size: 37
  s1p2 size: 6
  s3p2 size: 3
3 in s2p1? True
```

- [ ] **Step 7: Commit + push**

```bash
git add custom_components/dreame_a2_mower/inventory/loader.py tests/inventory/test_loader.py
git commit -m "feat(axis4-5): loader merges state_codes + mode_enum into value_catalogs

The s2p2 catalog (state codes) and s2p1 catalog (mode enum) live in
their own inventory sections rather than as inline value_catalog
blocks on the property rows. Loader now walks both sections and
merges them into value_catalogs[(2,2)] and value_catalogs[(2,1)].
Inline catalog wins on conflict (3 new tests cover the merge logic
and precedence rule). Auto-resolves the lone axis-4 candidate
(s2p1_3 PAUSED) which now appears in the runtime catalog without
explicit wiring."
git push origin main
```

---

## Task 2: Write `docs/research/g2408-capture-procedures.md`

**Files:**
- Create: `docs/research/g2408-capture-procedures.md`

The document carries 6-8 capture procedures plus a header explaining the trigger-type taxonomy and template. Each procedure follows the fixed shape from spec §4.2.

- [ ] **Step 1: Write the document header + trigger-type table + template**

Create `docs/research/g2408-capture-procedures.md` with this opening (no procedures yet):

```markdown
# g2408 — Capture Procedures

Topic-clustered procedures for closing inventory gaps where a slot's
semantic depends on observing a specific triggering event. Each procedure
names the inventory rows it closes, the trigger type, prerequisite
state, exact steps to take, what to look for in the resulting probe
log / cloud dump, and the inventory edits to make after capture.

For the slot-level current state see
`docs/research/inventory/generated/g2408-canonical.md`.
For the saga of how each slot got figured out see
`docs/research/g2408-research-journal.md`.
For open work see `docs/TODO.md`.

## Trigger types

| Type | Meaning |
|------|---------|
| `user-fakeable` | The user can synthesize the trigger (e.g., create a fake pathway, switch maps) without waiting for natural occurrence. |
| `event-driven` | Wait for a specific firmware event (e.g., AI human detection, OTA notification). The user can sometimes increase the probability (drive past pets, etc.) but can't directly cause it. |
| `automatic-over-time` | The trigger occurs on a cadence the user doesn't control (e.g., cloud dumps re-running and producing different responses for stateful endpoints). No direct user action needed. |
| `blocked-on-firmware-cooperation` | The trigger requires the firmware to do something it currently doesn't, OR the trigger is intentionally invisible to the cloud/MQTT path (e.g., BT-only PIN entry). Document the gap; close it only when external evidence becomes available. |

## Procedure template

Every procedure follows this structure:

```
## <Procedure name>

**Closes:** <comma-separated list of inventory row ids and/or open-question topics>
**Trigger type:** <one of the four types above>
**Estimated effort:** <minutes / hours / days / weeks>

### Prerequisites
- mower state required (e.g., docked + charged ≥80%)
- HA state required (e.g., integration loaded; no active session)
- probe-log capture must be running (start `probe_a2_mqtt.py` first)

### Procedure
1. numbered steps the user takes
2. ...

### What to look for
- specific MQTT slots / values to grep in the resulting probe log
- specific cloud-dump entries that change

### After capture
- which inventory rows to update (with the specific field changes)
- which open_questions to remove or upgrade
- whether to add a journal entry
```

---

## Procedures

(populated below)
```

- [ ] **Step 2: Append procedure 1 — Firmware update flow**

Append the following procedure under the `## Procedures` heading:

```markdown
## 1. Firmware update flow

**Closes:** `s1p2 ota_state`, `s1p3 ota_progress`, `s2p1_14 UPDATING`, `s2p57 robot_shutdown_trigger`, `s2p53 voice_download_progress` (probably reused for FW download).
**Trigger type:** `event-driven`
**Estimated effort:** ~30 min when an OTA notification appears (then back to waiting)

### Prerequisites
- HA integration running with verbose logging on `custom_components.dreame_a2_mower.coordinator` (DEBUG level).
- `probe_a2_mqtt.py` running and writing to `probe_log_<timestamp>.jsonl`.
- The Dreame app open and showing an "Update Available" banner. **Do NOT tap update yet.**
- Mower docked, charged ≥80%.

### Procedure
1. Bookmark the probe log: `cp probe_log_<latest>.jsonl probe_log_<latest>.jsonl.pre-fwupdate`.
2. In the Dreame app, tap the firmware-update prompt to begin.
3. Watch the app's progress UI; watch the probe log tail.
4. Allow the device to reboot. The HA integration will show "Updating" or similar; do not interact.
5. After the device returns to its post-update state (typically 5-10 min), stop the probe log capture: `kill <probe_a2_mqtt.py PID>`.

### What to look for
- `s1p2` push with values 2 (download_initiated), 3 (installing), 4 (failed) — apk's documented OTAState enum.
- `s1p3` push streaming 0..100 during download.
- `s2p1` transition into 14 (UPDATING) at the start of the install phase, then back to 6 (CHARGING) or 13 (CHARGED) after reboot.
- `s2p57` push immediately before reboot — apk says "5-second-delay then shutdown" trigger.
- Possibly `s2p53` for the FW-download progress (apk labels it voice download but might be reused).
- `device.info.version` field changes (cloud device record); cross-check before/after.

### After capture
- Update inventory rows for s1p2, s1p3, s2p57 to `seen_on_wire: true`, `first_seen: <date>`, `last_seen: <date>`.
- Confirm or correct s1p2's value_catalog against observed transitions.
- Add a journal entry under `## Recently shipped — version timeline` noting "axis-4/5: firmware-update flow captured 20XX-XX-XX; rows updated".
- If `s2p53` carried the download progress, update its row with the new semantic.
```

- [ ] **Step 3: Append procedure 2 — Take-a-photo flow**

```markdown
## 2. Take-a-photo flow (apk's takePic vs HA-integration path)

**Closes:** `o:401 takePic` semantic question, `s2p55 ai_obstacle_report` payload-on-success unknown.
**Trigger type:** `user-fakeable`
**Estimated effort:** 30 min

### Prerequisites
- `probe_a2_mqtt.py` running.
- HA integration loaded, mower docked.

### Procedure
1. Bookmark probe log.
2. From HA, call the integration's `dreame_a2_mower.take_picture` service (if exposed) OR open coordinator.py and dispatch `o:401` directly via the routed-action surface. Observe the s2p50 echo.
3. Stop and re-start: from the Dreame app, tap "Take Picture" while the mower is still docked. Observe the wire (or absence of wire activity).
4. Move the mower to a "ready to capture" state if you have one (the app's Take Picture button enables/disables based on device state). Repeat steps 2 and 3.
5. If the app uploads the photo, find the OSS object key — it'll either show in `s99p20`-style or via a different cloud HTTP endpoint.

### What to look for
- s2p50 echo with `o:401 status:true error:0` (accepted, command-internal succeeded) vs `o:401 status:false` (rejected by firmware state-mismatch).
- `event_occured siid=4 eiid=<?>` with a piid carrying the OSS object key for the photo.
- Cloud HTTP traffic to `getDownloadUrl` or similar with a `.jpg` filename.
- App-vs-integration divergence: the app may not use `o:401` at all (per the user's 2026-04-27 note in the journal — comparison test showed zero MQTT activity for the app's Take Picture).

### After capture
- Update inventory row `o401` (opcodes) with the confirmed accept/reject states + after-success behaviour.
- If app uses a different path entirely, document in the row + add a journal note about the divergence.
- s2p55 ai_obstacle row stays open if no AI obstacle event fired during this procedure (separate procedure).
```

- [ ] **Step 4: Append procedure 3 — Active mowing s5p10x sequence**

```markdown
## 3. Active mowing s5p10x sequence capture

**Closes:** `s5p104`, `s5p105`, `s5p106`, `s5p108` open semantic questions; refines `s5p107 energy_index` slope/flat distribution data.
**Trigger type:** `event-driven` (wait for a mowing run with no recharge interrupts; the test cycle is constrained by lawn size + battery)
**Estimated effort:** 1-3 hours per capture (mowing duration + analysis)

### Prerequisites
- `probe_a2_mqtt.py` running before mow start.
- Mower has ≥80% battery and the lawn is small enough for one continuous run.
- Note the local weather (slope: confound; rain: confound).

### Procedure
1. Bookmark probe log.
2. Start a manual full-lawn mow from the app or HA.
3. Let the mower run end-to-end (no Recharge presses, no Cancel).
4. After dock arrival, stop the probe log capture.
5. Analyse: for each s5p10x slot, plot value vs timestamp; correlate with phase_raw transitions (s1p4 byte[8]) and s2p1/s2p2 transitions.

### What to look for
- s5p104: counter pattern. Does it correlate with task-status events (TASK_SLAM_RELOCATE bursts)?
- s5p105 / s5p106: small enums. Distribution across the run; transitions on phase changes?
- s5p107 energy_index: median value during mowing; correlation with slope-vs-flat (if user lawn has slope).
- s5p108: single-observation slot per axis-1 corpus; does this run produce more pushes? what value(s)?

### After capture
- Update each s5p10x row with refined `semantic` prose and any value_catalog entries observed.
- If s5p108 fires multiple times with consistent values, upgrade `decoded: unknown` to `hypothesized` with the new framing.
- Add a journal entry under the s1p4 telemetry decoder evolution topic.
```

- [ ] **Step 5: Append procedure 4 — Patrol log trigger investigation**

```markdown
## 4. Patrol log trigger investigation

**Closes:** "Patrol Logs" open item from TODO.md; `s2p55 ai_obstacle_report` if patrol uses it.
**Trigger type:** `event-driven` if findable; `blocked-on-firmware-cooperation` if not.
**Estimated effort:** 1-2 hours of app exploration + a probe-log session

### Prerequisites
- Probe log running.
- Charged mower, docked.
- Time to explore the Dreame app UI deliberately.

### Procedure
1. Bookmark probe log.
2. In the Dreame app, navigate every screen looking for "Patrol", "Cruise", "Waypoint", "Tour", or similar terms. Specifically check:
   - Main mowing screen → modes / additional actions
   - Map screen → long-press / tap waypoints
   - Settings → all sub-screens
   - Maintenance / Service sections
3. If a patrol-start gesture is found, capture the resulting MQTT activity. Common opcodes to expect: `o:107 startCruisePoint`, `o:108 startCruiseSide`, `o:109 startCleanPoint` (apk-documented but currently `decoded: hypothesized`).
4. If no gesture is found in the app, document the search outcome and mark the closes-list as `blocked-on-firmware-cooperation`. The user's account may not have the feature unlocked, OR Dreame removed it from the consumer build.

### What to look for
- s2p50 echo with `o:107`, `o:108`, or `o:109`.
- `event_occured siid=4 eiid=1` or other event with a Patrol-distinct shape (different piid set than mowing-session-summary).
- New OSS object key for a Patrol log JSON.

### After capture
- Update the relevant opcode rows in inventory if they fired.
- If found and a Patrol log JSON exists, add a new `patrol_log_fields` section to inventory (analogous to `session_summary_fields`).
- If not found, mark the TODO entry as `blocked-on-firmware-cooperation`; add a journal note.
```

- [ ] **Step 6: Append procedure 5 — Pathway Obstacle Avoidance (user-fakeable)**

```markdown
## 5. Pathway Obstacle Avoidance (user-fakeable)

**Closes:** `CFG.BP`, `CFG.PATH` semantic questions (currently `decoded: hypothesized`).
**Trigger type:** `user-fakeable`
**Estimated effort:** 30-60 min

### Prerequisites
- Probe log running.
- HA integration's `sensor.cfg_keys_raw` exposed and showing current values for BP and PATH.
- Mower docked. Lawn map exists.

### Procedure
1. Bookmark probe log; snapshot current `sensor.cfg_keys_raw` attributes.
2. In the Dreame app: Map → Define a fake pathway (any short line on the lawn).
3. Mark the pathway for "Pathway Obstacle Avoidance" if that toggle exists.
4. Capture the resulting s2p51 push (likely `{value: 0|1}` ambiguous shape).
5. Wait 30 seconds, then refresh CFG (the integration auto-refreshes every 10 min, or trigger via `cfg_keys_raw._last_diff` mechanism).
6. Compare BP and PATH values before/after.
7. Toggle the avoidance flag (ON → OFF) and capture again.
8. Delete the fake pathway when done.

### What to look for
- s2p51 push at moment of toggle.
- BP value change (currently `[1, 3]` — may flip to `[1, 4]` or similar; documents the per-pathway list).
- PATH value change (currently stable at 1 — may flip to 0 if it's the master toggle).
- `cfg_keys_raw._last_diff` should name the changed key (BP or PATH) on the next CFG snapshot.

### After capture
- Update CFG.BP row's payload_shape and semantic with the per-pathway list interpretation.
- Update CFG.PATH row's value_catalog if the toggle correlation is confirmed.
- Update s2p51_shapes ambiguous_toggle row's CFG-key list (add BP/PATH if newly disambiguated).
```

- [ ] **Step 7: Append procedure 6 — Multi-lawn / second-map slot (user-fakeable)**

```markdown
## 6. Multi-lawn / second-map slot (user-fakeable)

**Closes:** `MAPL` 2x5 list semantics; service-4 map-related rows (s4p42 MAP_INDEX, s4p43 MAP_NAME, s4p44 CRUISE_TYPE, s4p47 SCHEDULED_CLEAN, s4p49 INTELLIGENT_RECOGNITION); some apk-vacuum-derived service-4 rows currently `UPSTREAM-KNOWN`.
**Trigger type:** `user-fakeable`
**Estimated effort:** 1-2 hours (map-create flow + capture)

### Prerequisites
- Probe log running.
- Cloud-dump tool ready: `dreame_cloud_dump.py` set to run before/after the multi-map operation.
- Mower charged + docked + on lawn that allows a second small fake-zone-only map.

### Procedure
1. Bookmark probe log; capture cloud dump #1.
2. In Dreame app: create a second map slot. The app may walk a "drive the boundary" sequence; complete it for a small fake zone.
3. Capture cloud dump #2 immediately after save.
4. Switch active map between slots in the app. Capture s2p51 / s2p50 / properties_changed events.
5. Trigger a small mow on the second map.
6. Capture cloud dump #3 after mow completes.
7. Switch back to the original map.
8. Optionally: delete the fake second map.

### What to look for
- MAPL value flips between dump #1 and dump #2 (the 2x5 list — likely encodes "slot N is configured / active").
- Any s4-series property pushes during map switching that aren't currently in inventory.
- The MAP.* cloud blob structure with a non-singleton `mapIndex` value.
- New OSS object keys with map-index-aware paths.

### After capture
- Update MAPL row with confirmed semantic for the 2x5 list shape.
- Upgrade s4p42, s4p43, s4p44, s4p47, s4p49 (and any other map-related s4 rows that fired) from `UPSTREAM-KNOWN` to `seen_on_wire: true, decoded: confirmed/hypothesized`.
- Add a journal entry under `g2408 vs upstream divergence` noting which apk-vacuum-derived slots g2408 actually exposes.
```

- [ ] **Step 8: Append procedure 7 — Cloud-dump cadence re-test**

```markdown
## 7. Cloud-dump cadence re-test

**Closes:** AIOBS, MAPD, MAPI, MITRC, OBS, PRE (cfg_individual.PRE) — the 6 axis-1-hardening downgrades that were marked `not_on_g2408 → false / decoded: hypothesized` due to insufficient negative evidence; MISTA's open questions about r=-1 ↔ ok flips; PIN, PREI, RPET, IOT semantics if any flip.
**Trigger type:** `automatic-over-time`
**Estimated effort:** 1 day to set up; 1-2 weeks to accumulate samples; ~30 min to merge findings

### Prerequisites
- `dreame_cloud_dump.py` script working and producing `dreame_cloud_dumps/dump_<timestamp>.json` files.
- A mechanism to run it on a schedule (cron, systemd timer, or HA automation that calls a shell script).

### Procedure
1. Schedule `dreame_cloud_dump.py` to run hourly for 1-2 weeks.
2. Each run writes a fresh dump under `dreame_cloud_dumps/`.
3. Periodically (every few days), run `python tools/inventory_audit.py --consistency` to surface any not_on_g2408 contradictions.
4. After the collection period, walk all dumps and look for endpoint flips:
   ```bash
   python -c "
   import json, glob
   from collections import defaultdict
   responses = defaultdict(lambda: {'ok': 0, 'r-1': 0, 'r-3': 0})
   for path in sorted(glob.glob('dreame_cloud_dumps/dump_*.json')):
       d = json.load(open(path))
       for k, v in (d.get('cfg_individual') or {}).items():
           if isinstance(v, dict):
               if any(str(key).startswith('_error') and 'r=-1' in str(v[key]) for key in v):
                   responses[k]['r-1'] += 1
               elif any(str(key).startswith('_error') and 'r=-3' in str(v[key]) for key in v):
                   responses[k]['r-3'] += 1
               elif 'ok' in v:
                   responses[k]['ok'] += 1
   for k, counts in sorted(responses.items()):
       if counts['ok'] > 0 and (counts['r-1'] + counts['r-3']) > 0:
           print(f'{k}: {counts}  ← FLIP CANDIDATE')
   "
   ```

### What to look for
- Endpoints that returned `ok` in some dumps and `r=-1` or `r=-3` in others. Each one is evidence the endpoint is stateful, NOT firmware-unsupported.
- Endpoints that returned `r=-3` consistently across all dumps in the period — those become genuinely confirmed `not_on_g2408: true` if combined with apk-side evidence (e.g., the apk explicitly labels them vacuum-only).
- Endpoint payload patterns when they DO succeed — do MAPD / MAPI return chunked map data?

### After capture
- For each flip endpoint: upgrade row from `decoded: hypothesized` to `decoded: confirmed`, populate `payload_shape:` with the observed success shape.
- For each consistently-erroring endpoint with corroborating apk evidence: revisit `not_on_g2408: true` (with the proper "consistent-across-N-dumps + apk-says-vacuum-only" justification).
- Add a journal entry under `cfg_individual MISTA reversal` topic noting the broader cadence study results.
```

- [ ] **Step 9: Append procedure 8 — Change PIN code (BT-only)**

```markdown
## 8. Change PIN code wire format

**Closes:** "Change PIN Code" open item from TODO.md; documents the BT-only constraint.
**Trigger type:** `blocked-on-firmware-cooperation`
**Estimated effort:** ~15 min to confirm the gap; days/weeks if pursuing BT instrumentation

### Prerequisites
- Probe log running.
- `dreame_cloud_dump.py` ready to capture before/after.
- Mower docked.

### Procedure
1. Bookmark probe log; capture cloud dump #1.
2. In Dreame app: Settings → Security / Anti-Theft → Change PIN Code. Enter current PIN; set a new one.
3. Capture cloud dump #2 immediately.
4. Compare dumps; check probe log for s2p51 / s2p50 / event_occured during the action window.

### What to look for
- ANY MQTT activity during the change. Specifically check:
  - s2p51 push (the multiplexed-config slot)
  - PIN cfg_individual entry change
  - sensor.cfg_keys_raw._last_diff naming PIN
- If nothing fires on any of those, the PIN change is BT-only.

### After capture
- If the change is BT-only (expected): document in the inventory row for PIN cfg_individual that this endpoint cannot be exercised from the integration. Mark this procedure's closes-list as resolved with `blocked-on-firmware-cooperation`.
- If something DID fire: update the relevant rows; this would be a new finding worth a journal entry.
```

- [ ] **Step 10: Verify the document is well-formed**

```bash
python -c "
import pathlib
content = pathlib.Path('docs/research/g2408-capture-procedures.md').read_text()
fences = content.count('\`\`\`')
print(f'lines: {len(content.splitlines())}')
print(f'fences: {fences} (must be even)')
assert fences % 2 == 0, 'unbalanced code fences'
proc_count = content.count('## ') - content.count('### ')
# Expected: 1 'Trigger types' + 1 'Procedure template' + 1 'Procedures' + 8 numbered procedures = 11
print(f'## headings: {proc_count}')
"
```

Expected: ~600-800 lines, even fence count, 11 `##`-level headings.

- [ ] **Step 11: Commit + push**

```bash
git add docs/research/g2408-capture-procedures.md
git commit -m "docs(axis4-5): capture procedures document

Eight procedures clustering 137 axis-5 inventory candidates by
trigger archetype:

1. Firmware update flow (event-driven, ~30 min when OTA appears)
2. Take-a-photo flow (user-fakeable, ~30 min)
3. Active mowing s5p10x sequence (event-driven, 1-3 hr)
4. Patrol log investigation (event-driven or blocked, 1-2 hr)
5. Pathway Obstacle Avoidance (user-fakeable, ~45 min)
6. Multi-lawn / second-map slot (user-fakeable, 1-2 hr)
7. Cloud-dump cadence re-test (automatic, ~2 weeks)
8. Change PIN code (blocked-on-firmware-cooperation, ~15 min)

Each procedure: closes-list, trigger type, estimated effort,
prerequisites, numbered steps, what-to-look-for, after-capture
inventory edits."
git push origin main
```

---

## Task 3: Add procedure cross-references to `docs/TODO.md`

**Files:**
- Modify: `docs/TODO.md`

The slim TODO.md from axis 2 has Open + In-progress + Blocked sections. Each Blocked entry that maps to a capture procedure gains a `**Procedure:** [link]` line.

- [ ] **Step 1: Read the current TODO.md to find Blocked entries**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower
grep -n "^### \|^## " docs/TODO.md
```

The Blocked section starts at the `## Blocked` heading; entries below it are `### <title>` blocks.

- [ ] **Step 2: For each Blocked entry, append a `**Procedure:** [link]` line**

Open `docs/TODO.md` and find each Blocked entry. After its `**Status:** blocked-by-X` line (and before the next blank line / next entry), insert a `**Procedure:**` line pointing at the relevant procedure section in `g2408-capture-procedures.md`.

Mapping (entry → procedure):

| Blocked entry (search keyword in TODO.md) | Procedure link |
|---|---|
| Dock-departure repositioning UX | `[docs/research/g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture](g2408-capture-procedures.md#3-active-mowing-s5p10x-sequence-capture)` (related; also document as `blocked-on-firmware-cooperation` if specific repositioning signal is genuinely cloud-invisible) |
| Mowing direction / Crisscross / Chequerboard | (no procedure — BT-only confirmed; leave without link) |
| ai_obstacle blob format | `[docs/research/g2408-capture-procedures.md#2-take-a-photo-flow-apks-takepic-vs-ha-integration-path](g2408-capture-procedures.md#2-take-a-photo-flow-apks-takepic-vs-ha-integration-path)` |
| Patrol Logs | `[docs/research/g2408-capture-procedures.md#4-patrol-log-trigger-investigation](g2408-capture-procedures.md#4-patrol-log-trigger-investigation)` |
| Firmware update flow capture | `[docs/research/g2408-capture-procedures.md#1-firmware-update-flow](g2408-capture-procedures.md#1-firmware-update-flow)` |
| Change PIN code | `[docs/research/g2408-capture-procedures.md#8-change-pin-code-wire-format](g2408-capture-procedures.md#8-change-pin-code-wire-format)` |
| Pathway Obstacle Avoidance | `[docs/research/g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable](g2408-capture-procedures.md#5-pathway-obstacle-avoidance-user-fakeable)` |
| MowerAction.SUPPRESS_FAULT | (no procedure — semantic test design pending; leave without link) |

For example, find this in TODO.md:

```markdown
### Firmware update flow capture

**Why:** Several apk-known slots (s1p2, s1p3, s2p57) are seen_on_wire:false because no OTA has fired during the probe corpus. Capturing one will let us upgrade those rows to confirmed.
**Done when:** A firmware update is captured; inventory rows updated.
**Status:** blocked-by-OTA-availability (Dreame pushes OTAs sporadically)
**Cross-refs:** journal Recently shipped — version timeline; inventory rows s1p2/s1p3/s2p57.
```

Replace with:

```markdown
### Firmware update flow capture

**Why:** Several apk-known slots (s1p2, s1p3, s2p57) are seen_on_wire:false because no OTA has fired during the probe corpus. Capturing one will let us upgrade those rows to confirmed.
**Done when:** A firmware update is captured; inventory rows updated.
**Status:** blocked-by-OTA-availability (Dreame pushes OTAs sporadically)
**Procedure:** [docs/research/g2408-capture-procedures.md#1-firmware-update-flow](g2408-capture-procedures.md#1-firmware-update-flow)
**Cross-refs:** journal Recently shipped — version timeline; inventory rows s1p2/s1p3/s2p57.
```

Do this for every Blocked entry that has a procedure-link mapping in the table above.

- [ ] **Step 3: Verify the procedure links resolve**

```bash
python -c "
import pathlib, re
todo = pathlib.Path('docs/TODO.md').read_text()
proc = pathlib.Path('docs/research/g2408-capture-procedures.md').read_text()

# Extract every #anchor in the procedure file (markdown auto-anchors are lowercased + non-alpha replaced)
# Quick approximation: all '## <heading>' lines become anchors derived from title.
def to_anchor(title):
    return re.sub(r'[^a-z0-9-]+', '-', title.strip().lower()).strip('-')

anchors = set()
for line in proc.splitlines():
    if line.startswith('## '):
        anchors.add(to_anchor(line[3:]))

# Find every Procedure: link in TODO and check
links = re.findall(r'\(g2408-capture-procedures\.md#([\w-]+)\)', todo)
print(f'TODO Procedure links: {len(links)}')
for ln in links:
    if ln not in anchors:
        print(f'  BROKEN: #{ln}')
print(f'available anchors: {sorted(anchors)[:5]}...')
"
```

Expected: every link resolves (no `BROKEN` lines printed).

- [ ] **Step 4: Run the audit one more time to confirm no inventory issues**

```bash
python tools/inventory_gen.py --validate-only
python tools/inventory_audit.py
python -m pytest tests/ -q 2>&1 | tail -3
```

All must pass.

- [ ] **Step 5: Commit + push**

```bash
git add docs/TODO.md
git commit -m "docs(axis4-5): add capture-procedure cross-refs to Blocked TODOs

Every Blocked TODO entry that has a matching procedure in
g2408-capture-procedures.md now carries a **Procedure:** link.
Items without a procedure (BT-only confirmed cases like Mowing
Direction; design-pending like SUPPRESS_FAULT) are left without
links — those are not protocol-gap procedures."
git push origin main
```

---

## Task 4: Final acceptance verification + close axis 4/5

**Files:** none (verification only)

- [ ] **Step 1: Run all 10 spec acceptance criteria**

```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower

echo "=== AC#1: loader extends _build_inventory with section merge ==="
grep -c "state_codes_catalog\|mode_enum_catalog" custom_components/dreame_a2_mower/inventory/loader.py
# expected: ≥ 4 (two assignments + two iter loops)

echo "=== AC#2: 3 new tests in tests/inventory/test_loader.py ==="
grep -c "test_state_codes_section_merged\|test_mode_enum_section_merged\|test_inline_value_catalog_takes_precedence" tests/inventory/test_loader.py
# expected: 3

echo "=== AC#3: live inventory's value_catalogs include (2,2) and 3-in-(2,1) ==="
python -c "
import sys; sys.path.insert(0, 'custom_components/dreame_a2_mower/inventory')
from loader import load_inventory
inv = load_inventory()
print(f'  catalogs total: {len(inv.value_catalogs)}')
assert (2, 2) in inv.value_catalogs
assert 3 in inv.value_catalogs[(2, 1)]
print('  ok')
"

echo "=== AC#4: capture-procedures document exists ==="
ls docs/research/g2408-capture-procedures.md
wc -l docs/research/g2408-capture-procedures.md

echo "=== AC#5: 8 procedures, each has the template fields ==="
python -c "
import re
content = open('docs/research/g2408-capture-procedures.md').read()
procs = re.findall(r'^## (\d+\. .+)', content, re.MULTILINE)
print(f'  numbered procedures: {len(procs)}')
for p in procs:
    print(f'    - {p}')
# Each procedure must mention closes-list, trigger type, prerequisites, after-capture
required_fields = ['**Closes:**', '**Trigger type:**', '### Prerequisites', '### After capture']
for f in required_fields:
    count = content.count(f)
    assert count >= 8, f'\"{f}\" appears {count} times, expected ≥ 8'
print('  all template fields present in each procedure')
"

echo "=== AC#6: TODO.md Blocked items have Procedure links where applicable ==="
grep -c "\*\*Procedure:\*\*" docs/TODO.md
# expected: ≥ 5 (one per applicable mapping)

echo "=== AC#7: inventory_gen --validate-only passes ==="
python tools/inventory_gen.py --validate-only

echo "=== AC#8: inventory_audit (presence + consistency) passes ==="
python tools/inventory_audit.py > /dev/null 2>&1; echo "  exit: $?"
python tools/inventory_audit.py --consistency > /dev/null 2>&1; echo "  consistency exit: $?"

echo "=== AC#9: pytest count ≥ 700 ==="
python -m pytest tests/ -q 2>&1 | tail -3

echo "=== AC#10: s2p1=3 PAUSED in runtime catalog ==="
python -c "
import sys; sys.path.insert(0, 'custom_components/dreame_a2_mower/inventory')
from loader import load_inventory
inv = load_inventory()
catalog = inv.value_catalogs[(2, 1)]
assert 3 in catalog, f'3 missing from s2p1 catalog: {sorted(catalog.keys())}'
print(f'  s2p1=3 → {catalog[3]} ✓')
"
```

Each line should produce a non-zero / non-empty / `ok` result.

- [ ] **Step 2: Confirm origin/main is up to date**

```bash
git log origin/main..HEAD --oneline
```

Expected: empty (every axis-4/5 commit is pushed).

- [ ] **Step 3: Final summary commit if anything cleanup-y is in the working tree**

```bash
git status -s
```

If anything is uncommitted, commit + push:

```bash
git add -A
git commit -m "docs(axis4-5): final cleanup"
git push origin main
```

---

## Self-review summary

**Spec coverage check:**
- §3 Non-goals — respected; no per-row procedure documents (clustered procedures only); no live-capture execution; no new HA entities beyond what auto-resolves via the loader merge.
- §4.1 loader catalog merge — Task 1 (TDD with 3 tests).
- §4.2 capture procedures document — Task 2 (8 procedures).
- §4.3 TODO cross-references — Task 3.
- §5 acceptance criteria — Task 4 verifies all 10.

**Placeholder scan:** every step shows actual content (markdown blocks, code, commands, expected output). No "TBD", "TODO", "implement later".

**Type consistency:** loader's `state_codes_catalog`, `mode_enum_catalog` variable names are unique; merge precedence is documented and tested. Procedure document's template fields (`**Closes:**`, `**Trigger type:**`, `### Prerequisites`, `### After capture`) are uniform across all 8 procedures.
