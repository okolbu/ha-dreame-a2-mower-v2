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
           print(f'{k}: {counts}  <- FLIP CANDIDATE')
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
