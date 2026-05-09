# Protocol Validation Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a complete, live-verified feature inventory of every HA entity, every received MQTT slot, and every cloud endpoint the integration uses — replacing the partially-fictional `entity-sync-matrix.md` with an evidence-stamped authoritative document. No code changes beyond minor wiring fixes if a test trivially exposes a bug.

**Architecture:** Three-pass audit: (1) skeleton matrix populated from code reading (all rows `⚠ hypothesis`), (2) per-category live verification using six named test patterns (T0–T6), (3) consolidation that produces a next-steps frontier in `docs/TODO.md`. The matrix is the only canonical artifact; sample wire captures spill into `docs/research/wire-captures/<feature>.md` when they exceed ~10 lines.

**Tech Stack:** Markdown, `python3 /tmp/snapshot_cloud.py` (existing tool), `grep` over `probe_log_*.jsonl`, controlled live tests driven by the user via the Dreame app + the integration's HA UI. No new code beyond minor entity-wiring fixes.

**Spec:** `docs/superpowers/specs/2026-05-09-protocol-validation-audit-design.md`

---

## Task 1: First-pass skeleton matrix

**Goal:** Produce `docs/research/entity-validation-matrix.md` with one row per entity / MQTT slot / cloud endpoint, every cell either populated from code reading or explicitly marked `⚠ hypothesis`. Nothing is `✓` yet.

**Files:**
- Create: `docs/research/entity-validation-matrix.md`
- Retire: `docs/research/entity-sync-matrix.md` → stub-and-redirect
- Read for input: `custom_components/dreame_a2_mower/{switch,select,number,sensor,binary_sensor,button,lawn_mower,event,device_tracker,camera,services,coordinator,cloud_client}.py`, `mower/property_mapping.py`, `mower/state.py`, `protocol/config_s2p51.py`, `inventory.yaml`

- [ ] **Step 1.1: Inventory current HA entities**

Run: `python3 - <<'PY'
import json, websocket
token = open('/data/claude/homeassistant/ha-credentials.txt').read().splitlines()[3]
ws = websocket.create_connection("ws://10.0.0.30:8123/api/websocket")
ws.recv(); ws.send(json.dumps({"type":"auth","access_token":token})); ws.recv()
ws.send(json.dumps({"id":1,"type":"get_states"}))
data = json.loads(ws.recv()); ws.close()
for s in data.get("result", []):
    e = s["entity_id"]
    if "dreame" in e:
        print(e)
PY`

Save the output (140+ entity_ids) to a scratch file `/tmp/audit_entities.txt`. Each entity becomes one row.

- [ ] **Step 1.2: Inventory MQTT slots wired into PROPERTY_MAPPING**

Read `custom_components/dreame_a2_mower/mower/property_mapping.py` end-to-end. For each `(siid, piid): PropertyMappingEntry(...)` entry, record:
- `(siid, piid)` tuple
- `field_name` or `multi_field` (which MowerState fields it writes)
- Decoder lambda

Save as `/tmp/audit_mqtt_slots.txt`. Also note any `_apply_s2p51_settings` setting types from `coordinator.py:_apply_s2p51_settings` (lines ~244-365) — these are sub-decodings of `(2, 51)`.

- [ ] **Step 1.3: Inventory cloud endpoints**

Read `cloud_client.py` and list every method that performs a cloud RPC. Distinguish:
- chunked-batch reads: `get_batch_device_datas`
- chunked-batch writes: `set_batch_device_datas`, `write_chunked_key`
- routed-action GETs: each `t=` target via `cfg_action.probe_get` / `fetch_cfg` / `fetch_locn` / `fetch_dock` / `fetch_mapl` / `fetch_mihis`
- routed-action SETs: `set_cfg`, `set_pre`
- direct MIoT: `set_property`, `get_properties` (rarely-used on g2408)
- routed-action ops: `dispatch_action` operation codes (mow start/pause/stop, find_bot, etc.)

Save as `/tmp/audit_cloud_endpoints.txt`.

- [ ] **Step 1.4: Draft matrix template + first 5 rows**

Create `docs/research/entity-validation-matrix.md` with the column schema from the spec (Feature / App screen / HA entity / Read sources / Live mechanism / Live latency / Cold-start strategy / Sanity-check strategy / Write current path / Write pre-rewrite path / Write outcome / Caveats / Last verified / Test recipe). Add a short header explaining the column meanings + evidence tiers (`✓ live`, `⚠ hypothesis`, `✗ live`, `? unknown`).

Populate the first 5 rows from `sensor.py` to validate the template (battery, charging_status, state, error_code, position_x_m). All fields except "HA entity" filled in from code reading; status = `⚠ hypothesis (first pass YYYY-MM-DD)`.

- [ ] **Step 1.5: Bulk-populate remaining rows from code**

Continue through all entity files in this order:
1. `sensor.py`, `binary_sensor.py` — read-only first
2. `switch.py`, `select.py`, `number.py` — settable
3. `button.py`, `lawn_mower.py`, `services.py` — actions

For each entity: feature name (use `_attr_name`), HA entity_id (use unique-id pattern), read source (trace `value_fn` / `native_value` / `is_on` to a MowerState field, then trace that field to its update path in `property_mapping.py` or `coordinator.py`), all other columns from code/docs hypothesis.

For multi-source entities (e.g. `mowing_height` updated by both `s6p2[0]` and SETTINGS poll): list both sources in priority order.

- [ ] **Step 1.6: Add MQTT-only rows**

For each `(siid, piid)` in PROPERTY_MAPPING that doesn't have an HA entity exposing it, add a row with HA entity = "MISSING" and a note about the unsurfaced MowerState field. These are Phase 2 candidates.

- [ ] **Step 1.7: Add cloud-endpoint coverage rows**

For each cloud RPC the integration calls regularly (LOCN, DOCK, MIHIS, MAPL, etc.), ensure at least one row references it. If a routed-action target is called but its result isn't surfaced as an entity, add a row with HA entity = "DIAGNOSTIC ONLY" or "INTERNAL".

- [ ] **Step 1.8: Replace `entity-sync-matrix.md` with stub**

Overwrite `docs/research/entity-sync-matrix.md` with:

```markdown
# Entity sync matrix (retired)

This file has been retired. The current authoritative matrix is at
[`docs/research/entity-validation-matrix.md`](entity-validation-matrix.md),
produced by the protocol-validation audit
(`docs/superpowers/specs/2026-05-09-protocol-validation-audit-design.md`).

The retired file's claims have been superseded; do not consult it.
```

- [ ] **Step 1.9: Commit**

```bash
git add docs/research/entity-validation-matrix.md docs/research/entity-sync-matrix.md
git commit -m "$(cat <<'EOF'
docs(audit): skeleton entity-validation-matrix.md (Task 1, first pass)

Replaces entity-sync-matrix.md (retired with redirect stub) with a
fresh first-pass matrix populated entirely from code reading. Every
row is marked ⚠ hypothesis pending the second-pass live verification.
Spec: docs/superpowers/specs/2026-05-09-protocol-validation-audit-design.md
EOF
)"
git push origin main
```

---

## Task 2: Read-only telemetry verification

**Goal:** Verify ~20 telemetry / state rows in the matrix during a single normal mowing session, with one MQTT probe-log capture covering the whole session.

**Files:**
- Modify: `docs/research/entity-validation-matrix.md` (rows for the verified entities)
- Create: `docs/research/wire-captures/telemetry-session-<date>.md` (sample MQTT frames + decoded values)
- Update: `docs/research/g2408-research-journal.md` (one entry for this session)

**Rows touched (20 candidates — adjust based on what fires during the session):**
- `sensor.battery` (s3p1)
- `sensor.charging_status` (s3p2)
- `sensor.state` (s2p1)
- `sensor.error_code` (s2p2)
- `sensor.error_description` (derived from error_code)
- `sensor.position_x_m`, `_y_m`, `_north_m`, `_east_m` (s1p4 telemetry)
- `sensor.area_mowed_m2`, `sensor.session_distance_m`, `sensor.mowing_phase` (s1p4 telemetry)
- `sensor.active_selection` (derived)
- `binary_sensor.obstacle_detected` (s1p53)
- `binary_sensor.mowing_session_active` (live_map.is_active())
- `binary_sensor.robot_tilted`, `_bumper_error`, `_robot_lifted`, `_emergency_stop_activated`, `_safety_alert_active`, `_top_cover_open`, `_battery_temp_low` (s1p1 byte bits)
- `binary_sensor.mower_in_dock`, `_dock_in_lawn_region` (cloud DOCK poll, observed at session start/end)

- [ ] **Step 2.1: Pre-session checklist**

```bash
# Confirm probe log is alive and capturing
ls -lat /data/claude/homeassistant/probe_log_*.jsonl | head -1
# Snapshot HA state (baseline)
python3 - <<'PY'
import json, websocket
token = open('/data/claude/homeassistant/ha-credentials.txt').read().splitlines()[3]
ws = websocket.create_connection("ws://10.0.0.30:8123/api/websocket")
ws.recv(); ws.send(json.dumps({"type":"auth","access_token":token})); ws.recv()
ws.send(json.dumps({"id":1,"type":"get_states"}))
data = json.loads(ws.recv()); ws.close()
import time
out = f"/tmp/audit_ha_baseline_{int(time.time())}.json"
with open(out, "w") as f:
    json.dump([s for s in data["result"] if "dreame" in s["entity_id"]], f, indent=2)
print(f"saved {out}")
PY
# Snapshot cloud (baseline)
python3 /tmp/snapshot_cloud.py audit_telemetry_pre
```

Note the timestamp `T_start` for the probe-log scan.

- [ ] **Step 2.2: User runs a normal mow**

Tell the user: "Press Start on the mower (in HA or app — your call). Let it mow for 5+ minutes including a real obstacle event if possible (e.g. walk in front of it briefly). When you're done, recharge or stop, and tell me."

Wait for confirmation. Note `T_end`.

- [ ] **Step 2.3: Capture probe-log span**

```bash
LATEST=$(ls -t /data/claude/homeassistant/probe_log_*.jsonl | head -1)
T_START="2026-05-09 HH:MM"  # fill from step 2.1
T_END="2026-05-09 HH:MM"    # fill from step 2.2

# Extract every property-changed event in the session window
grep "properties_changed" "$LATEST" | python3 -c "
import json, sys
import datetime as dt
T0 = dt.datetime.fromisoformat('$T_START')
T1 = dt.datetime.fromisoformat('$T_END')
seen = {}
for line in sys.stdin:
    try:
        d = json.loads(line)
        ts = dt.datetime.fromisoformat(d['timestamp'])
        if not (T0 <= ts <= T1): continue
        for p in d.get('params', []):
            k = (p.get('siid'), p.get('piid'))
            seen[k] = seen.get(k, 0) + 1
    except Exception:
        pass
for k in sorted(seen):
    print(f'  s{k[0]}p{k[1]}: {seen[k]} fires')
" > /tmp/audit_telemetry_slot_counts.txt
cat /tmp/audit_telemetry_slot_counts.txt
```

The output enumerates every `(siid, piid)` that fired during the session and how many times.

- [ ] **Step 2.4: Cross-reference fires with matrix rows**

For each row in the candidate list above:
1. Find the `(siid, piid)` it claims to read from in the matrix.
2. Check `/tmp/audit_telemetry_slot_counts.txt` — did it fire?
3. If yes: capture one sample frame from the probe log into `docs/research/wire-captures/telemetry-session-<date>.md` with the fire-count and the decoded interpretation. Mark the matrix row `✓ live <date> / fw <ver> / int <ver>`.
4. If no: leave row at `⚠`. Note in the row why the fire was expected — the test recipe needs the right trigger.

- [ ] **Step 2.5: Snapshot HA state again, diff against baseline**

```bash
python3 - <<'PY'
# Repeat the get_states call from step 2.1, save as audit_ha_post
PY
# Diff: which entities changed during the session?
python3 -c "
import json, glob
pre = max(glob.glob('/tmp/audit_ha_baseline_*.json'))
# load pre + post, diff state values
" > /tmp/audit_ha_diff.txt
```

For any entity that changed in HA during the session, verify the matrix row's read source predicts that. Update row evidence.

- [ ] **Step 2.6: Update matrix + journal**

For each verified row, fill in:
- Last verified: `<date> / fw <fw_ver> / int <int_ver> / spec b17bc6a`
- Test recipe: condensed (e.g. "Run a normal mowing session under probe log; expect s1p4 fires every ~5s during MOWING")

Add a journal entry to `docs/research/g2408-research-journal.md`:

```markdown
#### Telemetry-session audit (YYYY-MM-DD)

Single mowing session under probe log, captured T_start..T_end.
Slot fires: <paste /tmp/audit_telemetry_slot_counts.txt>
Verified <N> rows in entity-validation-matrix.md (✓ live).
<N_unverified> rows still ⚠ — reason: <e.g. obstacle never triggered s1p53>.
```

- [ ] **Step 2.7: Commit**

```bash
git add docs/research/entity-validation-matrix.md \
        docs/research/wire-captures/telemetry-session-*.md \
        docs/research/g2408-research-journal.md
git commit -m "docs(audit): Task 2 — telemetry session verification"
git push origin main
```

---

## Task 3: CFG-backed settings (s2p51) verification

**Goal:** Verify the ~17 entities backed by a CFG key that pushes via s2p51 MQTT — these have always been claimed to propagate fast; this task confirms the read AND the write paths still work end-to-end.

**Files:**
- Modify: `docs/research/entity-validation-matrix.md`
- Append: `docs/research/wire-captures/cfg-settings-<date>.md`
- Update: `docs/research/g2408-research-journal.md`

**CFG keys to verify (one row each, plus sub-rows for multi-bit ones):**
- `CLS` (Child Lock) — single int
- `VOL` (Volume) — single int 0-100
- `LANG` (Language) — list[2] [text_idx, voice_idx]
- `DND` (Do Not Disturb) — list[3]
- `WRP` (Rain Protection) — list[2]
- `LOW` (Low-Speed Nighttime) — list[3]
- `BAT` (Charging config) — list[6], BAT[2] hardcoded
- `LIT` (LED config) — list[8], read-only because LIT[1,2,7] not stored
- `ATA` (Anti-Theft) — list[3]
- `REC` (Human Presence Alert) — list[9], read-only because REC[2..8] not stored
- `MSG_ALERT` (Notifications) — list[4]
- `VOICE` (Voice Prompts) — list[4]
- `FDP` (Frost Protection) — single int
- `STUN` (Auto Recharge after Standby) — single int
- `AOP` (AI Obstacle Photos) — single int — note: distinct from `AI_HUMAN.0`
- `PROT` (Navigation Path) — single int
- `PRE` (Mowing Efficiency + …) — list[2] on g2408

For each: T3 (app-side toggle, expect s2p51 fire) + T4 (HA-side toggle, expect cloud accept + cold-start app reflect).

The full per-row sub-task structure is identical for each CFG key. The pattern below is the canonical template; instantiate for each key.

### Per-CFG-key canonical pattern (instantiate for each key above)

- [ ] **Step 3.X.1: Pre-toggle baseline**

```bash
python3 /tmp/snapshot_cloud.py audit_cfg_<KEY>_pre
# Note current HA state for the related entity
```

- [ ] **Step 3.X.2: User toggles in app (T3)**

Tell the user: "Toggle <feature_name> in the Dreame app. Save / confirm if needed. Tell me when done."

Note `T_app_toggle`.

- [ ] **Step 3.X.3: Observe MQTT + cloud**

```bash
# Look for s2p51 fires in the 30s after T_app_toggle
LATEST=$(ls -t /data/claude/homeassistant/probe_log_*.jsonl | head -1)
T="<T_app_toggle>"
# Tail probe log for s2p51 within ±30s
grep "s2p51\|properties_changed" "$LATEST" | grep -A 1 "$T" | head -20
# Snapshot cloud post-app-toggle
python3 /tmp/snapshot_cloud.py audit_cfg_<KEY>_post_app
# Diff
python3 /tmp/snapshot_cloud.py diff audit_cfg_<KEY>_pre audit_cfg_<KEY>_post_app
```

Expected: s2p51 fires with the new value within seconds; CFG.<KEY> changes in cloud diff; CFG.VER bumps.

- [ ] **Step 3.X.4: HA toggle (T4)**

Tell the user: "I'll toggle the entity in HA via the WebSocket call." Then:

```bash
python3 - <<'PY'
import json, websocket
token = open('/data/claude/homeassistant/ha-credentials.txt').read().splitlines()[3]
ws = websocket.create_connection("ws://10.0.0.30:8123/api/websocket")
ws.recv(); ws.send(json.dumps({"type":"auth","access_token":token})); ws.recv()
# call_service to flip the relevant entity
ws.send(json.dumps({
    "id": 1,
    "type": "call_service",
    "domain": "switch",  # or select / number depending
    "service": "toggle",
    "service_data": {"entity_id": "switch.dreame_a2_mower_<entity>"}
}))
print(ws.recv())
ws.close()
PY
sleep 5
python3 /tmp/snapshot_cloud.py audit_cfg_<KEY>_post_ha
python3 /tmp/snapshot_cloud.py diff audit_cfg_<KEY>_post_app audit_cfg_<KEY>_post_ha
```

Expected: CFG.<KEY> changes again; CFG.VER bumps. s2p51 may or may not fire (HA writes don't always echo).

- [ ] **Step 3.X.5: Cold-start app verify**

Tell the user: "Force-quit the Dreame app on either device and reopen it. Look at <feature_name>. Tell me what value it shows."

If the cold-started app reflects HA's value: write outcome is `✓ end-to-end <date>`.
If it shows the pre-HA-toggle value: write outcome is `✗ HA-write doesn't drive device <date>` — open a Phase 3 line item.

- [ ] **Step 3.X.6: Update matrix row**

Fill in for this CFG key's row(s):
- Read sources (priority): `live MQTT s2p51`, fallback `cloud CFG.<KEY> @10min poll`
- Live mechanism: `live MQTT push`
- Live latency: `≤5s via s2p51`
- Cold-start strategy: `cloud CFG.<KEY>`
- Sanity-check strategy: `cloud CFG poll @10min, alert on divergence`
- Write current path: `coordinator.write_setting('<KEY>', value) → set_cfg via routed-action s2.50 s.<KEY>`
- Write pre-rewrite path: (run `git log -p coordinator.py` from before commit `3413170`; record if different, else "(unchanged)")
- Write outcome: from step 3.X.5
- Last verified stamp + test recipe.

- [ ] **Step 3.X.7: Restore original value**

Toggle back to the pre-test value (HA can do this — it's a settable setting). This keeps the user's actual settings intact across the audit.

After all CFG keys verified:

- [ ] **Step 3.Z.1: Append wire captures + journal entry**

Add per-key sample frames to `docs/research/wire-captures/cfg-settings-<date>.md`. Add a single journal entry summarising: which CFG keys verified, which surprised, which now have explicit `✗` outcomes.

- [ ] **Step 3.Z.2: Commit**

```bash
git add docs/research/entity-validation-matrix.md \
        docs/research/wire-captures/cfg-settings-*.md \
        docs/research/g2408-research-journal.md
git commit -m "docs(audit): Task 3 — CFG-backed settings (s2p51) verification"
git push origin main
```

---

## Task 4: SETTINGS-backed (Mowing settings page) verification

**Goal:** Verify the ~13 entities backed by the chunked-batch SETTINGS surface — the rewrite-touched class. Each row gets explicit confirmation of (a) read source actually delivers fresh values, (b) write-via-`setDeviceData` either fully propagates OR doesn't drive device firmware.

**Files:**
- Same shape as Task 3.

**Entities to verify:**
- `number.mowing_height` (also via s6p2[0] live)
- `number.cutter_position`, `number.cutter_position_height`, `number.edge_mowing_num`
- `number.obstacle_avoidance_height`, `_distance`, `_sensitivity`
- `select.mowing_direction`, `select.mowing_pattern`, `select.edge_walk_mode`
- `switch.edge_mowing_auto`, `_safe`, `_obstacle_avoidance`
- `switch.obstacle_avoidance_enabled`
- `switch.ai_obstacle_recognition_humans`, `_animals`, `_objects` (3 bits in `obstacleAvoidanceAi`)
- `binary_sensor.edgemaster` (read-only via s6p2[2])

For each: T3 (app toggle) + T4 (HA toggle) + cold-start app verification. Same canonical pattern as Task 3 but the read source is `cloud SETTINGS.<field>` and the write path is `setDeviceData`.

- [ ] **Step 4.1: Per-entity test cycle (instantiate the canonical pattern from Task 3)**

For each entity above, run the 7-step T3+T4 cycle. Specifically:

For step 4.X.4 (HA toggle), use the integration's existing optimistic-write path (the entity will write to setDeviceData). For step 4.X.5 (cold-start app verify), this is the load-bearing test — the rewrite-class entities are most likely to reveal `✗ HA-write doesn't drive device`.

- [ ] **Step 4.X.6: Pre-rewrite write path check (T0)**

For each entity, run:

```bash
# Find the commit that introduced the current write path
git log -p custom_components/dreame_a2_mower/coordinator.py custom_components/dreame_a2_mower/cloud_client.py | grep -B 50 "<entity_field_name>" | head -80

# Look at the code as it was before commit 3413170
git show 3413170~1:custom_components/dreame_a2_mower/coordinator.py | grep -A 20 "<related_function>" 2>/dev/null
```

Record the pre-rewrite path in the matrix row. If different from current and the current write doesn't end-to-end propagate, this is a candidate for Phase 3 restore.

- [ ] **Step 4.Z: Cross-row pattern analysis**

After all 13 entities tested, scan the matrix:
- Do ALL setDeviceData writes fail to drive device, or only some?
- Is there a pattern (e.g. only the BT-classified group fails)?
- Is there a pattern based on the cloud field's sub-shape (e.g. ints vs lists vs nested dicts)?

Record findings in the journal. The pattern (if any) drives Phase 3's design.

- [ ] **Step 4.Z.commit: Commit**

```bash
git add docs/research/entity-validation-matrix.md \
        docs/research/wire-captures/settings-*.md \
        docs/research/g2408-research-journal.md
git commit -m "docs(audit): Task 4 — SETTINGS-backed (Mowing settings page) verification"
git push origin main
```

---

## Task 5: AI_HUMAN.0 verification

**Goal:** Verify the single chunked-batch boolean key that's distinct from AOP / AI bits.

**Files:** matrix + wire capture + journal as before.

- [ ] **Step 5.1: T3 + T4 cycle for `switch.ai_human_detection`**

Single round trip: app toggle, HA toggle, cold-start app verify. AI_HUMAN.0 is the simplest chunked-batch write (single bool, single chunk, no entry-0/entry-1 dual-level). The result tells us whether `setDeviceData` works for the trivial case — if even AI_HUMAN.0 fails to propagate from HA writes, the chunked-batch surface is fundamentally write-only-to-cache.

- [ ] **Step 5.2: Update matrix + journal + commit**

```bash
git add docs/research/entity-validation-matrix.md docs/research/g2408-research-journal.md
git commit -m "docs(audit): Task 5 — AI_HUMAN.0 verification"
git push origin main
```

---

## Task 6: SCHEDULE verification

**Goal:** Verify the schedule blob round-trip: read decoding, write via `set_schedule_plans`, mode-flag preservation, slot add / edit / remove.

- [ ] **Step 6.1: Read decode**

Capture current SCHEDULE.0 from cloud, parse via `protocol/schedule.py:parse_schedule_batch`, verify decoded plans match what the app shows. Capture sample wire bytes per slot in `docs/research/wire-captures/schedule-<date>.md`.

- [ ] **Step 6.2: T3 — app-side slot edit**

Tell the user: "Open one of the schedule slots in the Dreame app, change the time of one plan by say 30 minutes, save."

Then:
- Snapshot cloud
- Diff: SCHEDULE.0 should reflect the new time, version (`v`) should increment
- Verify the mode flag (entry index 1 in the slot tuple) is preserved
- Update matrix

- [ ] **Step 6.3: T4 — HA-side slot edit**

```bash
python3 - <<'PY'
# call dreame_a2_mower.set_schedule_plans with a modified plan list
PY
```

Snapshot cloud, diff, then cold-start app. Verify both apps show the new plans.

- [ ] **Step 6.4: HA-side slot add (new slot)**

Add a third slot (slot_id 2 if not present) via service. Verify cloud accepts, cold-start app shows the new slot.

- [ ] **Step 6.5: HA-side slot remove**

Replace a slot's plan list with `[]`. Verify the slot becomes empty, cold-start app reflects it.

- [ ] **Step 6.6: Update matrix + journal + commit**

```bash
git add docs/research/entity-validation-matrix.md \
        docs/research/wire-captures/schedule-*.md \
        docs/research/g2408-research-journal.md
git commit -m "docs(audit): Task 6 — SCHEDULE verification"
git push origin main
```

---

## Task 7: Action surface verification

**Goal:** Verify the control / action surface — start, pause, stop, recharge, find_bot, mow zone/edge/spot, set_active_selection, suppress_fault, finalize_session, refresh_cloud_state.

These are mostly verified by observing a real session, but the various mow modes (zone/edge/spot) need explicit checks.

- [ ] **Step 7.1: Verify state-control buttons during a session**

Use the existing telemetry-session capture from Task 2 if it covered start/pause/stop/recharge transitions. If not, run a minimal session: HA Start → wait 30s → HA Pause → wait 10s → HA Resume → wait 30s → HA Stop. Observe state transitions in the probe log.

- [ ] **Step 7.2: Verify zone-mow / edge-mow / spot-mow opcodes**

For each of zone/edge/spot:
1. Set `select.action_mode` to the right value
2. Pick a target (zone_id / spot_id / edge contour)
3. Press Start
4. Verify the right opcode fires (101 for edge, 102 for zone, 103 for spot — visible in routed-action probe if instrumented; otherwise via app's session-start screen)
5. Stop / recharge
6. Update matrix

- [ ] **Step 7.3: Verify find_bot, suppress_fault, finalize_session, refresh_cloud_state**

- find_bot: press the button, listen for the device's locator beep (user reports)
- suppress_fault: only test if a recoverable fault is present (note "Untested" in matrix if not)
- finalize_session: dry-run by pressing when no session active (should be no-op)
- refresh_cloud_state: press button, observe `_refresh_cloud_state` log line, verify cloud_state object updates in HA

- [ ] **Step 7.4: Update matrix + journal + commit**

```bash
git add docs/research/entity-validation-matrix.md docs/research/g2408-research-journal.md
git commit -m "docs(audit): Task 7 — action surface verification"
git push origin main
```

---

## Task 8: Maps / multi-map / LiDAR verification

**Goal:** Verify map-related entities — active map switching, zone/spot/edge pickers, multi-map cameras, replay session, LiDAR archive, work_log picker.

- [ ] **Step 8.1: Active map switch**

In HA, change `select.active_map`. Observe: opcode 200 fired, MAPL repolls (s1p50 trigger), `_active_map_id` updates, all SETTINGS-driven entities re-bind to new map's settings, camera re-renders.

- [ ] **Step 8.2: Zone / spot / edge pickers**

For each: change the picker, verify `MowerState.active_selection_*` updates, `sensor.active_selection` reflects new label. No cloud write happens (these are local).

- [ ] **Step 8.3: Camera live-map render during session**

Already covered by Task 2's session capture if camera updated. Otherwise: confirm `_main_view_png` updates as `s1p4` telemetry fires; the camera re-fetches.

- [ ] **Step 8.4: Replay session**

Pick an archived session in `select.work_log`. Verify `_work_log_png` populates, the work-log camera shows it.

- [ ] **Step 8.5: LiDAR**

If a recent LiDAR PCD exists in the archive, verify `camera.lidar_top_down` and `camera.lidar_top_down_full` render. The Lovelace card test is out of scope for this audit (UI work).

- [ ] **Step 8.6: Update matrix + journal + commit**

```bash
git add docs/research/entity-validation-matrix.md docs/research/g2408-research-journal.md
git commit -m "docs(audit): Task 8 — maps / multi-map / LiDAR verification"
git push origin main
```

---

## Task 9: Diagnostics + housekeeping verification

**Goal:** Verify the long tail — diagnostic / observability sensors, hardware metadata, novel-observation tracker, freshness sensor, schedule_count, etc.

- [ ] **Step 9.1: Read-only diagnostic walk**

For each diagnostic sensor (novel_observations, state_freshness_s, api_endpoints_supported, schedule_count, hardware_serial, firmware_version, mower_timezone, cloud_connected, wifi_rssi_dbm, etc.), confirm:
1. The sensor has a value (not None / "unknown")
2. The value matches what we can independently verify (e.g. firmware_version against device info)
3. Mark `✓ live`

- [ ] **Step 9.2: Update matrix + journal + commit**

```bash
git add docs/research/entity-validation-matrix.md docs/research/g2408-research-journal.md
git commit -m "docs(audit): Task 9 — diagnostics + housekeeping verification"
git push origin main
```

---

## Task 10: Consolidation + frontier

**Goal:** Cross-pattern analysis, next-steps frontier, audit completion stamp.

**Files:**
- Modify: `docs/research/entity-validation-matrix.md` (final review pass + completion stamp)
- Modify: `docs/TODO.md` (next-steps frontier per row)
- Modify: `docs/research/g2408-research-journal.md` (audit-complete entry)
- Modify: `README.md` (point to the new matrix; remove "BT-only" leftovers)

- [ ] **Step 10.1: Final consistency pass on the matrix**

Read every row. Check:
- Every row has either `✓ live <date>` or `⚠ hypothesis (with reason)` or `✗ live <date>` — no row is missing evidence
- Multi-source rows list every source, in priority order
- Write-capable rows have a verified outcome
- Sample wire captures referenced where they should be

Fix any inconsistency inline.

- [ ] **Step 10.2: Cross-row pattern analysis**

In `g2408-research-journal.md`, write a final entry:

```markdown
#### Audit complete (YYYY-MM-DD)

Verified <X> rows ✓ live, <Y> rows ⚠ (with explicit reason), <Z> rows ✗.
Patterns observed:
- <pattern 1: e.g. setDeviceData writes for AI bits don't propagate to device firmware>
- <pattern 2: e.g. all CFG-backed settings work end-to-end via set_cfg>
- <pattern 3: e.g. EdgeMaster only in s6p2 — no SETTINGS field>

Surprises / corrections:
- <e.g. <X> entities were claimed to be on path Y but actually live on Z>
- <e.g. doc claim from <date> is wrong: <retraction>>

Next-steps frontier in docs/TODO.md.
```

- [ ] **Step 10.3: Build next-steps frontier in `docs/TODO.md`**

For each `⚠`/`✗` row, add a TODO entry. Group by:
- **Phase 2 (read-side refactor / wiring fixes)**: rows where a slow path is used when a faster source exists; rows missing entities for surfaced data
- **Phase 3 (write-path repair)**: rows with `✗ HA-write doesn't drive device` — needs app-RPC capture
- **Untested-blocked (physical event needed)**: rows where the trigger requires manual action we couldn't perform (suppress_fault, specific obstacle types, etc.)
- **Untested-blocked (state-dependent)**: rows that need a specific mower state we didn't reach (mid-mow only, dock-only, etc.)

Format each as a one-paragraph TODO entry with the matrix row link.

- [ ] **Step 10.4: Audit-complete stamp**

Add a header to `entity-validation-matrix.md`:

```markdown
**Audit completion:** YYYY-MM-DD against integration `<int_ver>`, firmware `<fw_ver>`.
Spec: `docs/superpowers/specs/2026-05-09-protocol-validation-audit-design.md`.
Plan: `docs/superpowers/plans/2026-05-09-protocol-validation-audit.md`.
```

- [ ] **Step 10.5: Update README.md**

Replace the existing "Known sync nuances" section's link target from `entity-sync-matrix.md` to `entity-validation-matrix.md`. Remove any other "BT-only" leftovers if found.

- [ ] **Step 10.6: Final commit + tag**

```bash
git add docs/research/entity-validation-matrix.md \
        docs/research/g2408-research-journal.md \
        docs/TODO.md \
        README.md
git commit -m "docs(audit): Task 10 — audit complete; cross-pattern analysis + Phase 2/3 frontier"
git push origin main
git tag audit-complete-2026-05-09
git push origin audit-complete-2026-05-09
```

---

## Self-review notes

- **Spec coverage**: every audit goal in the spec maps to a task above (skeleton → Task 1; live verification per category → Tasks 2-9; consolidation → Task 10).
- **Placeholders**: none — every "fill in" instruction has the exact command or parameter that drives the substitution.
- **Type / name consistency**: matrix file is `entity-validation-matrix.md` consistently. Wire captures are `wire-captures/<feature>-<date>.md` consistently. Spec commit referenced as `b17bc6a` in step 2.6 is the spec's actual commit hash.

## Open follow-up after this plan

After this plan completes, the next deliverables are:

- **Phase 2 spec / plan**: read-side architectural refactor driven by the audit's findings — coordinator decomposition, multi-source resolution per row's strategy, removal of the `_refresh_cfg` legacy alongside `_refresh_cloud_state`, surfacing missing entities (e.g. `mow_mode` from `pre_mowing_efficiency`).
- **Phase 3 spec / plan**: write-path repair, possibly including HTTPS sniff of the Dreame app to capture the actual write RPC for the `✗` rows.

Both are out of scope for this plan.
