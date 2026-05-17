# Session data completeness — design

Date: 2026-05-17
Status: design, awaiting implementation plan

## Goal

Make every finished mowing session self-describe completely:

1. **Complete trail.** No data loss across HA reboots; trail extends through
   the final drive-back-to-dock arc, not just the mowing-stops-here moment
   when session-done fires.
2. **Complete context.** A full firmware-state snapshot taken at session-start
   so the archive is forensically interpretable months later, independent of
   what the cloud / device looks like at read time.
3. **Defense-in-depth recovery.** A recorder-merge safety net catches sample
   streams even if the in-progress persist chain regresses again.

Three open MEMORY.md TODOs roll up into this spec:

- `[[project_session_persist_audit_todo]]` — 2026-05-15 19h session lost 8.5h of samples
- `[[project_session_dock_return_capture_todo]]` — trail collector stops at session-done
- `[[project_gappy_sessions_todo]]` — replay card behaviour on gappy sessions un-characterized

## Non-goals

- **Power loss between persist ticks.** Per-segment fsync would be too disk-
  intensive for the SD-card storage typical on HA installs. The existing 30s
  debounced persist remains the baseline; data accumulated between the last
  persist and a hard power loss is gone.
- **Retroactive recovery of pre-fix sessions.** Existing gappy archives stay
  as-is; `tools/rebuild_session.py` is the offline tool for those when they
  matter to the user.
- **Cloud session-summary truncation.** When the cloud emits a partial
  session-summary, we still archive what we have. This spec doesn't try to
  reconcile cloud-side gaps.

## Phase 1 — Persist-chain race-guard fix

### Root cause

`coordinator/_session.py:_restore_in_progress`:

```python
if self.live_map.is_active():
    LOGGER.info(...)  # "MQTT arrived before restore; skipping disk restore"
    return
```

The race: on HA reboot, the coordinator's `_async_update_data` first refresh
runs in parallel with the MQTT subscriber connecting. If an MQTT property
push (e.g. s3p1 battery percent, s2p1 state) arrives BEFORE
`_restore_in_progress` executes, the on_state_update handler calls
`live_map.begin_session(...)` which sets `started_unix`. Now
`is_active()` is True. Restore runs, sees the active live_map, and **bails
out without loading the persisted samples / legs / settings_snapshot from
disk**. The next `_persist_in_progress` tick (30s later) then writes the
EMPTY-but-fresh in_progress.json over the disk file — the persisted 8.5h
of data is irrecoverably lost.

### Fix

Replace the bailout with **restore-then-merge**:

1. Always read `in_progress.json` first (regardless of `live_map.is_active()`).
2. If the on-disk session matches the live one (same `session_start_ts` or
   close enough — within 5 minutes — to absorb clock drift between cloud
   start_ts and locally-stamped start_ts), MERGE: union the legs (dedupe
   on full-tuple equality), append-and-dedupe the 5 sample arrays, restore
   `charge_at_start` if currently None, restore `settings_snapshot` if
   currently None.
3. If the on-disk session is OLDER (start_ts differs by > 5 min), treat
   it as a stale snapshot from a previous run — log warning and delete it.
   This handles the legitimate "I rebooted between two sessions" case.
4. If `live_map` was inactive, restore as today.

### Atomic write hardening

Replace `write_in_progress`'s current write-rename with:

1. Write to `in_progress.json.tmp`.
2. `fsync` the tmp file (commits the data, not just the directory entry).
3. Rename tmp over the target.

Append a CRC32 footer line to the JSON payload (out-of-spec but on its own
line so the JSON parser ignores it; a trailing `# crc32=DEADBEEF` comment-
style line in the file but stored as a top-level `__crc32__` field
inside the JSON object itself). On read, recompute CRC over the
canonical-serialised body minus the field; if mismatch, log warning and
treat the file as missing (so restore falls through to "no in-progress
session" rather than restoring corrupt data).

### Acceptance

- Reboot HA during an active session → re-run produces a session archive
  whose sample counts equal probe-truth (no data-loss gap in the time-
  breakdown).
- Power-cycle test (`kill -9` the HA process mid-write): in_progress.json
  is either fully-readable-with-correct-CRC or fails the CRC check; never
  half-written-and-silently-restored.
- Two consecutive sessions across a reboot: stale in_progress from the
  prior session is dropped, not merged into the new one.

## Phase 2 — Recorder-merge for state / charging / error

### Today

`v1.0.14a7` added a recorder-merge safety net for `battery_samples` and
`wifi_samples` — if the in_progress chain drops samples, the merge helper
backfills from HA's recorder DB at session finalize. The other three sample
streams (`charging_status_samples`, `state_samples`, `error_samples`) have
no such backup because the underlying values aren't exposed as their own
sensors.

### Add

Three new diagnostic sensors:

- `sensor.dreame_a2_mower_state_code` — raw s2p1 STATE int (MOWING / PAUSED /
  RETURNING / CHARGING / etc.), `entity_category=DIAGNOSTIC`
- `sensor.dreame_a2_mower_charging_status_code` — raw s3p2 charging-status int
- `sensor.dreame_a2_mower_error_code_raw` — raw s2p2 error/notification int.
  The existing `sensor.dreame_a2_mower_error_code` returns the
  human-readable string label; this new one carries the integer for the
  recorder-merge pipeline. Both kept side-by-side rather than renaming,
  to avoid orphan-entity churn in user dashboards/automations.

Each is a thin wrapper over the corresponding MowerState field; no new
wire decode work.

Extend the recorder-merge helper at
`coordinator/_recorder_merge.py:merge_recorder_samples` (currently
covers battery + wifi only; called from `_session.py:510` and
`_lidar_oss.py:409`) to also:

1. Query recorder rows for the new three entities across the session's
   `[start_ts, end_ts]` window at finalize.
2. Convert each recorder row into the existing `[ts_unix, value]`
   `TelemetrySample` shape.
3. Union with `_local_legs.<stream>` and dedupe on full-tuple equality
   (same logic the wifi/battery merge already uses).

### Acceptance

- Simulated persist failure (e.g., make `in_progress.json` unreadable
  partway through a session) → finalized session JSON still has
  state/charging/error samples spanning the whole `[start, end]` window,
  because the recorder backfill kicked in.
- The state-driven time breakdown (v1.0.14a8 feature) shows minimal
  "Other" bucket on long sessions even after simulated chain failures.

## Phase 3 — Dock-return capture extension

### Today

When the integration's session-end event fires (cloud session-summary
arrives OR FINALIZE_INCOMPLETE gate triggers), the trail collector
stops appending s1p4 position points to `live_map.legs`. The mower
then physically drives back to the dock — that arc is lost.

### Change

After session-end fires, do NOT immediately archive. Instead:

1. Set a `_pending_finalize: bool` flag and start a 5-minute timeout
   task.
2. Keep accepting s1p4 pushes into `live_map.legs` (continuing the
   last leg, since this is a continuous motion).
3. Wait for either:
   - `task_state_code` returns to idle baseline (per inventory.yaml
     s2p1, this fires when the firmware-side session is fully wrapped up
     and the mower is back in standby)
   - `charging_status == 1` (mower has physically docked and started
     charging)
   - The 5-minute timeout (in case the mower can't return — e.g.
     stuck, or a "park without charge" low-battery scenario)
4. Whichever fires first triggers the actual archive write.

### Edge cases

- **Multiple session-ends in quick succession.** Shouldn't happen normally;
  if it does (e.g. cloud retries summary delivery), the second one is a
  no-op while `_pending_finalize` is True.
- **MQTT outage during dock-return.** Trail captures less than ideal but
  the 5-min timeout fires and the archive is still written.
- **HA reboot during the pending-finalize window.** The in_progress.json
  is still on disk (the dock-return points landed in it via the regular
  30s persist), so Phase 1's restore picks them up. The new session-end
  detection runs on the post-restore state and re-triggers the
  pending-finalize loop. Should be safe.

### Acceptance

- Sessions that ended far from the dock show a continuous trail to the
  dock in the replay card (no abrupt mid-yard stop).
- Low-battery emergency dock without charging: archive still writes
  after 5 min timeout, trail captured up to where MQTT stopped pushing.

## Phase 4 — Full firmware-state snapshot at session-start

### Today

`live_map.settings_snapshot` is set at session-begin to a `dict()` copy of
`cloud_state.settings.by_map_id_canonical[active_map_id]`. Covers ~19
per-map fields (mowingHeight, edge modes, AI/obstacle avoidance, etc.).

### Expand to T1+T2+T3+T4

Replace the current single dict with a structured snapshot object
covering everything that could affect or explain mowing behaviour. New
shape:

```yaml
settings_snapshot:
  version: 2                          # schema version (1 = legacy per-map-only)
  captured_at_unix: <int>             # session start time

  # T1 — per-map cloud SETTINGS (existing, kept as-is for backward compat)
  per_map:
    mowingHeight: 4
    mowingEfficiency: 0
    mowingDirection: 172
    mowingDirectionMode: 1
    cutterPosition: 0
    cutterPositionHeight: 3
    edgeMowingAuto: 1
    edgeMowingSafe: 1
    edgeMowingObstacleAvoidance: 1
    edgeMowingNum: 2
    edgeMowingWalkMode: 0
    obstacleAvoidanceEnabled: 1        # LiDAR obstacle recognition master
    obstacleAvoidanceAi: 2             # AI flag (bitmask?)
    obstacleAvoidanceDistance: 15
    obstacleAvoidanceHeight: 10
    obstacleAvoidanceSensitivity: 2
    edgemaster: 0
    ai_obstacle_recognition_humans: false
    ai_obstacle_recognition_animals: true
    ai_obstacle_recognition_objects: false
    # …all per-map fields

  # T2 — device-wide CFG / SETTINGS fields that affect mowing behaviour
  device_wide:
    rain_protection_enabled: true
    rain_protection_resume_hours: 4
    frost_protection_enabled: true
    navigation_path: "Direct Path"
    auto_recharge_battery_threshold: 15
    resume_after_charge_battery_threshold: 95
    auto_recharge_after_extended_standby: true
    custom_charging_period_enabled: false
    custom_charging_period_start: "22:00"   # if enabled
    custom_charging_period_end: "06:00"     # if enabled
    dnd_enabled: false
    dnd_start: "22:00"
    dnd_end: "07:00"
    low_speed_at_night_enabled: true
    low_speed_at_night_start: "22:00"
    low_speed_at_night_end: "07:00"

  # T3 — peripheral but "could explain behaviour"
  peripheral:
    human_presence_alert_enabled: true
    human_presence_alert_sensitivity: 1
    human_presence_scenario_standby: true
    human_presence_scenario_mowing: true
    human_presence_scenario_recharge: true
    human_presence_scenario_patrol: true
    human_presence_alert_voice: false
    human_presence_push_interval_min: 3
    photo_consent: true
    ai_obstacle_photos: true

  # T4 — forensic completeness (no expected mowing impact)
  forensic:
    led_in_standby: true
    led_on_error: true
    led_while_charging: true
    led_while_working: true
    led_period_enabled: false
    voice_language: "Norwegian"
    lcd_language: "Norwegian"
    voice_volume: 70
    anti_theft_lift_alarm: false
    anti_theft_off_map_alarm: false
    anti_theft_realtime_location: true
    child_lock: false
```

~55 fields total. Builder function lives in `coordinator/_session.py` (or
a dedicated `coordinator/_snapshot.py` if it grows beyond ~150 LOC), called
once at session-begin. Each subsection is independently populated — missing
data sources (e.g. brand-new entity not yet hooked up) leave their slot as
`None` rather than failing the snapshot.

### Backward compatibility

- Old archives have `settings_snapshot` as the legacy flat per-map dict
  (no `version` field). Consumer code in `session_card.py` and the dashboard
  needs to handle both shapes: if `version >= 2`, read from
  `per_map.<key>`; if no `version`, treat the dict itself as the per-map
  block.
- Bump `INDEX_VERSION` in `archive/session.py` from 1 to 2; on load, log a
  one-time warning when encountering v1 archives.

### Acceptance

- New session-archive JSON contains the full v2-shape `settings_snapshot`.
- Existing archives still render correctly (dashboard's "Settings in effect
  at session start" card handles both shapes).
- Field-by-field comparison between snapshot and live-after-mow shows zero
  drift when no settings were changed mid-session.

## Phase 5 — Gappy-session characterization

### Today

`[[project_gappy_sessions_todo]]` parked the question of how the replay
card behaves on sessions whose trail data has gaps (mid-session MQTT
outages, partial restores, etc.). Closing it requires a verification pass,
not new code.

### Verify

Pick representative sessions:

1. **Reboot-gap session.** Force a 5-min HA reboot mid-session, let
   Phase 1 restore complete, run session through to end. Compare
   `_local_legs` continuity before/after fix.
2. **Pause-resume session.** Use the app's pause button mid-mow, wait
   5 min, resume. Legitimate "gap" in the trail (mower wasn't moving)
   — replay card should show pause as a frozen-cursor span, not as a
   teleport jump.
3. **MQTT-outage session.** Disconnect MQTT for 60s mid-mow. _local_legs
   gets a gap (no s1p4 capture during outage). Replay-card animation
   shouldn't drift its time-cursor wildly; pause-budget allocation
   should land in the right place.

Document expected behavior in `docs/research/replay-card-gap-behavior.md`.
If any of the three reveals genuine animation bugs (not just expected gap
rendering), open a follow-up issue rather than expanding scope here.

### Acceptance

- All three test sessions produce visually-defensible replay-card output.
- Doc commits explaining what each gap type looks like and why.

## Cross-cutting: file structure

New file boundaries the implementation plan should respect:

| File | New / extended | Concern |
|---|---|---|
| `coordinator/_session.py` | extend | `_restore_in_progress` (race fix), `_persist_in_progress` (CRC), dock-return pending-finalize logic |
| `archive/session.py` | extend | atomic write with fsync + CRC32 footer; `INDEX_VERSION = 2` bump |
| `coordinator/_snapshot.py` | NEW if > 150 LOC, else inline | `build_settings_snapshot_v2()` helper |
| `sensor.py` | extend | 3 new diagnostic sensors: state_code, charging_status_code, error_code |
| `session_card.py` | extend | Handle both v1 and v2 snapshot shapes when building picked_session attrs |
| `dashboards/mower/dashboard.yaml` | extend | "Settings in effect at session start" markdown — fall back to v1 fields if v2 not present, render new sections when v2 |

`coordinator/_session.py` is already at the upper end of comfortable size
(667 LOC per CLAUDE.md). If Phase 3's dock-return logic + Phase 1's
restore-merge + Phase 2's recorder-merge extension push it past ~900 LOC,
split the recorder-merge out into `coordinator/_session_recorder_merge.py`
as a sibling mixin.

## Risks / open questions

- **CRC32 footer in JSON.** Putting the CRC inside the JSON object means
  recomputing the CRC requires re-serializing with a canonical key order
  (sort_keys=True) and excluding the CRC field. Worth verifying that
  `json.dumps(payload, sort_keys=True)` is stable across Python versions
  before betting on it for integrity. Alternative: store the CRC as a
  sidecar file (`in_progress.json.crc`) — simpler but doubles the file
  count.
- **Per-map vs device-wide split in snapshot.** The per-map values come
  from `cloud_state.settings.by_map_id_canonical[map_id]`; device-wide
  from `cloud_state.cfg.<key>` (single namespace). The builder needs to
  cleanly handle "active_map_id is None" (session starts before
  cloud_state.settings has populated) — fall back to `per_map: None`
  rather than failing the snapshot.
- **Recorder-merge for error_code.** s2p2 fires many distinct codes during
  a session (rain_protection, low_battery_return, etc.). The recorder
  stores one row per state change; that matches the existing `error_samples`
  semantic. But the recorder also stores attribute snapshots; we only
  want the integer state, not the attributes. Confirm during implementation
  that the merge helper queries state-only.
- **Phase 3 timeout interaction with finalize.** If the 5-min dock-return
  window is still open when HA restarts, Phase 1's restore re-arms it
  (good), but the timer counter restarts from 0 — could compound up to
  ~10 min total. Acceptable trade-off; explicit timer-state persistence
  would be over-engineering.

## References

- `[[project_session_persist_audit_todo]]` — the 19h-session data-loss observation
- `[[project_session_dock_return_capture_todo]]` — the dock-return arc miss
- `[[project_gappy_sessions_todo]]` — replay-card gap behavior
- `[[reference_session_rebuild_tool]]` — offline recovery path (still valid; not superseded by this)
- `2026-05-16-session-recorder-merge-and-rain-bucket-design.md` — v1.0.14a7 recorder-merge for wifi/battery (the prior art for Phase 2)
- `2026-05-16-state-driven-time-breakdown.md` — v1.0.14a8 state-partition algorithm (consumer of the state_samples Phase 2 backfills)
