# Telemetry session wire captures — 2026-05-09

Live capture from a normal mowing session that started at `2026-05-09 14:31:39` and was actively MOWING when the audit ran (~23 min in). Cross-validated against the user's note that 10-20 full sessions exist in the same probe log going back to 2026-05-05 at least.

**Probe log:** `/data/claude/homeassistant/probe_log_20260419_130434.jsonl`
**Integration:** `v1.0.2a8`
**Firmware:** `4.3.6_0550`
**Spec commit:** `b17bc6a`

## Session-start signature

```
2026-05-09 14:31:39   s2p2 = 50          ← manual session start (transition 48 → 50)
2026-05-09 14:31:39   s2p56 = {"status": []}    ← initial empty status
2026-05-09 14:31:40   s2p1 = 1           ← state machine: 1 = WORKING (initial value also captured)
2026-05-09 14:31:40   s3p2 = 0           ← charging_status: 0 = NOT_CHARGING (off-dock)
2026-05-09 14:31:50   s5p106 = 6         ← diagnostic raw (uncharacterized)
2026-05-09 14:32:17   s1p50 = {}         ← empty-dict ping → MAPL repoll trigger
2026-05-09 14:32:17   s1p51 = {}         ← suppressed
2026-05-09 14:32:17   s2p50 = {"d":{"exe":true,"o":200,"status":true},"t":"TASK"}   ← TASK envelope echo (suppressed)
```

Cross-check against historical session starts in the same log:
```
2026-05-07 20:04:25   48 → 50            ← matches: idle → manual mow
2026-05-06 17:46:57   43 → 50            ← matches: returning-to-station → manual mow (mid-recharge interrupt)
2026-05-05 17:00:45   48 → 50            ← matches: idle → manual mow
```

## Per-slot first-fire captures

### `s1p1` (HEARTBEAT blob, 88 fires this session)

```python
[206, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 17, 255, 0, 0, 128, 163, 186, 206]
# byte[0]   = 0xCE = sentinel (constant)
# byte[1]   = 0    = drop_tilt / bumper bits (none set)
# byte[2]   = 0    = lift bit (not set)
# byte[3]   = 0    = emergency_stop bit (not set)
# byte[6]   = 0    = battery_temp_low bit (not set)
# byte[10]  = 0x00 = safety_alert_active bit (not set)
# byte[11]  = 100  = battery percentage (?)
# byte[19]  = 0xCE = sentinel (constant)
```

**Verifies**: `binary_sensor.drop_tilt`, `_bumper`, `_lift`, `_emergency_stop`, `_safety_alert_active`, `_battery_temp_low` slot fires. The specific bits being 0 in this sample is the steady-state mowing case; for full bit-flip evidence, search the full session for byte changes.

### `s1p4` (MOWING_TELEMETRY blob, 274 fires this session — every ~5 s)

```python
[206, 244, 255, 223, 255, 255, 145, 0, 0, 0, 255, 127, 0, 128, 255, 127, 0, 128, 255, 127, 0, 128, 1, 1, 0, 0, 176, 29, 0, 0, 0, 0, 206]
# byte[0]    = 0xCE  = sentinel
# bytes[1..6] = position fields (decoded by MowingTelemetry)
# bytes[10..21] = three 4-byte float-or-fixed fields (likely position_x/y/heading)
# bytes[22..27] = phase / area / distance fields
# byte[32]   = 0xCE = sentinel
```

**Verifies**: telemetry blob arrives at ~5 s cadence during MOWING. Decode is in `protocol/telemetry.py`. **TODO** for second-pass deep verification: cross-check the decoded field values against `sensor.position_x_m / _y_m / _area_mowed_m2 / _session_distance_m / _mowing_phase` updates in HA — the integration's MowingTelemetry decoder should produce values matching what the entities surface.

### `s1p53` (OBSTACLE_FLAG, 5 fires this session)

```python
False  # first sample at 14:32:24 — mower starting nominal mowing
```

Then several `False ↔ True` flips during the session as obstacles are encountered/cleared.

**Verifies**: `binary_sensor.obstacle_detected` — instant fires on every obstacle encounter.

### `s2p1` (state, 1 fire — fired once at session-start transition)

```python
1   # WORKING (per State enum)
```

**Verifies**: `sensor.state` — the integration's state-mapping reads s2p1 as the authoritative state.

### `s2p2` (error_code, 1 fire — fired once at session-start)

```python
50   # apk fault index 50 = manual session start (action surface)
```

Cross-check across 149 historical transitions: 20 distinct s2p2 codes observed including 0 (idle), 1, 9, 23, 27, 30 (maintenance reminder?), 31 (FTRTS), 33, 36, 43 (charging-related), 48 (mow complete), 50 (manual mow), 53, 54 (charging-with-something), 56 (rain), 60, 70, 71 (positioning failed), 73 (top cover open), 75. Some are transient one-shots; others are sticky.

**Verifies**: `sensor.error_code`, `sensor.error_description` (derived), plus the derived binary sensors `_rain_protection_active` (==56), `_positioning_failed` (==71), `_failed_to_return_to_station` (==31), `_top_cover_open` (==73).

### `s2p56` (task_state_code, 2 fires this session)

```python
{"status": []}                # 14:31:39 — no active task at this exact moment
{"status": [[1, 0]]}          # 14:32:18 — task running (sub-state 0)
```

**Verifies**: `sensor.task_state_code` reads `status[0][1]` (the sub-state). 0 = running, 4 = paused-pending-resume; empty = no session.

### `s3p1` (battery_level, 20 fires this session)

```python
99   # first sample at 14:32:38 — battery starts near full
# subsequent fires drop incrementally as the mower works
```

**Verifies**: `sensor.battery` — fires every ~1-2 min during mowing as the integer % drops.

### `s3p2` (charging_status, 1 fire — at session start)

```python
0   # NOT_CHARGING (mower departed dock)
```

**Verifies**: `sensor.charging_status` — only fires on transition. Codes: 0=NOT_CHARGING, 1=CHARGING, 2=CHARGED.

### `s5p106` (diagnostic raw, 1 fire)

```python
6   # uncharacterized
```

Surfaces as `sensor.s5p106_raw` for protocol-RE work; semantics not decoded.

## Session-end pattern (from historical sessions)

A typical session ends with `s2p2: 50 → 54` (mowing → charging-related), `s2p1: 1 → 6` (WORKING → CHARGING), `s2p56: {"status":[[1,0]]} → {"status":[[1,2]]}` (running → completing), then `s2p2: 54 → 48` (mowing-complete) and finally `s2p2: 48 → 43` (post-charge).

Each of these transitions in the historical 149-event log is consistent with the apk fault-index labeling, providing high confidence in the state-machine + error-code interpretation.

## Verifications recorded

| Entity | Slot | Evidence | Tier |
|---|---|---|---|
| sensor.battery | s3p1 | 20 fires this session | ✓ live 2026-05-09 |
| sensor.charging_status | s3p2 | 1 fire at session start | ✓ live 2026-05-09 |
| sensor.state | s2p1 | 1 fire at session start (value 1 = WORKING) | ✓ live 2026-05-09 |
| sensor.error_code | s2p2 | 149 historical transitions across 20 distinct codes | ✓ live 2026-05-09 |
| sensor.error_description | derived | values look-up via `_describe_error_or_none` | ✓ derived |
| sensor.task_state_code | s2p56 | 2 fires showing empty → running | ✓ live 2026-05-09 |
| sensor.position_x_m / y / north / east | s1p4 | 274 fires at ~5 s cadence | ✓ live 2026-05-09 (slot fires; field decoding cross-check deferred to Task 9) |
| sensor.area_mowed_m2 / session_distance_m / mowing_phase | s1p4 | same blob | ✓ live 2026-05-09 (slot fires; field decoding cross-check deferred) |
| binary_sensor.obstacle_detected | s1p53 | 5 fires during session | ✓ live 2026-05-09 |
| binary_sensor.mowing_session_active | derived | True throughout (s2p56 status non-empty) | ✓ live 2026-05-09 |
| binary_sensor.drop_tilt / bumper / lift / emergency_stop / safety_alert_active / battery_temp_low | s1p1 byte bits | 88 fires; bits all 0 in steady-state sample (no fault during this session) | ⚠ slot fires confirmed; per-bit flips need a fault session for full evidence |
| binary_sensor.rain_protection_active / positioning_failed / failed_to_return_to_station / top_cover_open | derived from error_code | error_code itself confirmed | ✓ live derivation |
| sensor.s5p106_raw | s5p106 | 1 fire (uncharacterized) | ✓ live 2026-05-09 (slot exists, semantic unknown — known TODO) |
