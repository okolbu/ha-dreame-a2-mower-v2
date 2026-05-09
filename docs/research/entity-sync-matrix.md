# Entity sync matrix (g2408)

Authoritative lookup of every HA entity and public service, mapped to:

- **Read source** — where the integration gets the value from
- **Write target** — how the integration writes back (or whether it can)
- **App pickup** — does the Dreame app reflect a change initiated by HA?

Use this to quickly diagnose "I toggled X in HA but the app didn't see it"
or to scope new work. Last verified: **2026-05-09** (g2408 fw 4.3.6_0550).

## Column definitions

### Read source
- `cloud SETTINGS` — chunked-batch, key `SETTINGS.0..N + SETTINGS.info`. Dual top-level entries; entry 0 = user-saved (canonical), entry 1 = firmware-applied mirror. See `docs/research/cloud-write-reference.md`.
- `cloud CFG.<KEY>` — routed-action `s2.50 g.CFG` GET dict. Keys like CLS, VOL, DND, BAT, LIT, REC, ATA, MSG_ALERT, VOICE, FDP, STUN, AOP, PROT, PRE, etc.
- `cloud AI_HUMAN.0` — chunked-batch single bool, "Capture Photos AI Obstacles" toggle.
- `cloud SCHEDULE.0` — chunked-batch, slot list `[id, mode, name, blob_b64]`.
- `cloud MAP.*` — chunked-batch, map geometry (boundary/zones/contours).
- `cloud MAPL` — routed-action s2.50 g.MAPL, multi-map active list.
- `cloud DOCK / LOCN / NET / DEV / MIHIS` — routed-action probes.
- `MQTT s<N>p<M>` — live property push (telemetry, state, errors).
- `derived` — computed locally from other sources.

### Write target
- `setDeviceData` — chunked-batch (SETTINGS, AI_HUMAN.0, SCHEDULE.0). **Cloud accepts but device firmware does not always apply** — see "BT-only" caveat below.
- `set_cfg` — routed-action `s2.50 s.<KEY>`. **Drives the device** for CFG keys it supports.
- `set_pre` — routed-action `s2.50 s.PRE` (special, full-array). Drives the device.
- `dispatch_action` / `routed_action` — operation codes (mow start/pause/stop, change-map, find-bot, etc.). Drives the device.
- `set_property` MIoT — direct property write. Returns 80001 on g2408 for most siids; only specific opcodes work.
- `read-only` — no cloud write path. Often because not all wire elements are decoded into MowerState.

### App pickup
- `Yes — full propagation` — verified or expected: HA writes, app reflects within seconds-to-minutes.
- `Cloud-only — app does not refresh` — HA writes succeed at the cloud, but the device firmware doesn't apply, so the app keeps showing the old value (it reads device-applied state). Verified 2026-05-09.
- `Untested` — write path exists but no live verification of app-side behaviour.
- `N/A — read-only` — no write path.

## BT-only / cloud-write-invisible category

A specific class of settings on g2408: the device firmware applies them only over Bluetooth (the Dreame app keeps a BT link to the mower while open). **Cloud writes via `setDeviceData` are accepted by the cloud (CFG.VER may even bump) but the device firmware never applies them**, so the app shows the pre-write value. Confirmed BT-only on g2408 (most via toggle test 2026-04-26 in the historical doc; AI Obstacle Recognition and obstacleAvoidance fields re-confirmed 2026-05-09):

- AI Obstacle Recognition: Humans / Animals / Objects (3 bits in `obstacleAvoidanceAi`)
- Mowing Direction (`mowingDirection`)
- Mowing Pattern (`mowingDirectionMode`)
- Edge Mowing: Auto, Safe, Obstacle Avoidance (`edgeMowingAuto`, `edgeMowingSafe`, `edgeMowingObstacleAvoidance`)
- Edge Walk Mode (`edgeMowingWalkMode`)
- LiDAR Obstacle Recognition (`obstacleAvoidanceEnabled`)
- Obstacle Avoidance Distance / Height / Sensitivity
- Mowing Height (`mowingHeight`), Cutter Position(`cutterPosition`), Cutter Height (`cutterPositionHeight`), Edge Passes (`edgeMowingNum`)
- Start from Stop Point
- Pathway Obstacle Avoidance

For these, HA correctly READS the cloud SETTINGS (so HA shows what the user last *saved* via the app — entry 0 is user-saved). Writes from HA land in cloud SETTINGS but do not drive the device. To make the device apply, the user must toggle in the Dreame app.

The integration's `dreame_a2_mower.refresh_cloud_state` service / `button.refresh_from_cloud` button forces an immediate cloud re-fetch, useful as a manual escape hatch.

The `s6p2` MQTT tripwire ("settings-saved" pulse) is hooked to a debounced cloud refresh in v1.0.2a4+, so app-side changes surface in HA within ~5 seconds without waiting for the next 10-min poll.

## Switches

| Entity | Read source | Write target | App pickup | Notes |
|---|---|---|---|---|
| switch.child_lock | cloud CFG.CLS | set_cfg (CLS int) | Yes — full propagation | Single int {0, 1}. Verified 2026-04-30. |
| switch.dnd | cloud CFG.DND | set_cfg (DND list[3]) | Yes — full propagation | `[enabled, start_min, end_min]`. All in MowerState. Defaults 20:00→08:00. |
| switch.rain_protection | cloud CFG.WRP | set_cfg (WRP list[2]) | Yes — full propagation | `[enabled, resume_hours]`. Coordinates with select.rain_protection_resume_hours (last writer wins). |
| switch.low_speed_at_night | cloud CFG.LOW | set_cfg (LOW list[3]) | Yes — full propagation | `[enabled, start_min, end_min]`. |
| switch.custom_charging_period | cloud CFG.BAT | set_cfg (BAT list[6]) | Yes — full propagation | `[recharge_pct, resume_pct, unknown_flag, custom_charging, start_min, end_min]`. BAT[2] hardcoded to 1 — see TODO entry. |
| switch.anti_theft_lift_alarm | cloud CFG.ATA | set_cfg (ATA list[3]) | Yes — full propagation | `[lift_alarm, offmap_alarm, realtime_location]`. Index [0] overridden. Verified 2026-04-27. |
| switch.anti_theft_offmap_alarm | cloud CFG.ATA | set_cfg (ATA list[3]) | Yes — full propagation | Index [1] overridden. |
| switch.anti_theft_realtime_location | cloud CFG.ATA | set_cfg (ATA list[3]) | Yes — full propagation | Index [2] overridden. |
| switch.frost_protection | cloud CFG.FDP | set_cfg (FDP int) | Yes — full propagation | Single int {0, 1}. Verified 2026-04-30. |
| switch.auto_recharge_standby | cloud CFG.STUN | set_cfg (STUN int) | Yes — full propagation | Single int {0, 1}. Verified 2026-04-30. |
| switch.ai_obstacle_photos | cloud CFG.AOP | set_cfg (AOP int) | Yes — full propagation | Single int {0, 1}. NB: this is the CFG-backed "AI photos" toggle, separate from `switch.ai_human_detection` which writes AI_HUMAN.0. |
| switch.ai_human_detection | cloud AI_HUMAN.0 | setDeviceData (AI_HUMAN.0) | Untested | Single chunked-batch key, JSON-encoded bool. Live propagation to app not yet verified. |
| switch.msg_alert_anomaly / _error / _task / _consumables | cloud CFG.MSG_ALERT | set_cfg (MSG_ALERT list[4]) | Yes — full propagation | 4-bool list `[anomaly, error, task, consumables]`. Each switch overrides one index; all 4 stored in MowerState. |
| switch.voice_regular_notification / _work_status / _special_status / _error_status | cloud CFG.VOICE | set_cfg (VOICE list[4]) | Yes — full propagation | 4-bool list `[regular, work, special, error]`. Same pattern as MSG_ALERT. |
| switch.led_period | cloud CFG.LIT[0] | read-only | N/A — read-only | Wire is `list(8)`. Indices 1, 2, 7 not in MowerState → cannot safely reconstruct full list → settable not implemented. |
| switch.led_in_standby / _working / _charging / _error | cloud CFG.LIT[3..6] | read-only | N/A — read-only | Same `list(8)` reconstruction problem. |
| switch.human_presence_alert | cloud CFG.REC[0] | read-only | N/A — read-only | Wire is `list(9)`. Indices [2..8] not decoded → cannot safely reconstruct → read-only. |
| switch.edge_mowing_auto | cloud SETTINGS (edgeMowingAuto) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only setting. HA reads correctly; HA writes land in SETTINGS but the device firmware doesn't apply. |
| switch.edge_mowing_safe | cloud SETTINGS (edgeMowingSafe) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only setting. |
| switch.edge_mowing_obstacle_avoidance | cloud SETTINGS (edgeMowingObstacleAvoidance) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only setting. |
| switch.obstacle_avoidance_enabled | cloud SETTINGS (obstacleAvoidanceEnabled) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only setting (LiDAR Obstacle Recognition top-level). |
| switch.ai_obstacle_recognition_humans | cloud SETTINGS (obstacleAvoidanceAi bit 0) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only AI bit. Verified 2026-05-09: HA writes land in SETTINGS entry 0 but app shows pre-write value (even after restart). |
| switch.ai_obstacle_recognition_animals | cloud SETTINGS (obstacleAvoidanceAi bit 1) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | Same pattern as humans bit. |
| switch.ai_obstacle_recognition_objects | cloud SETTINGS (obstacleAvoidanceAi bit 2) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | Same pattern as humans bit. |

## Selects

| Entity | Read source | Write target | App pickup | Notes |
|---|---|---|---|---|
| select.action_mode | MowerState.action_mode (RestoreEntity) | local state only | N/A — local only | User's mode picker (All-areas / Edge / Zone / Spot). Persisted via RestoreEntity; not written to device. Determines which opcode the Start button uses. |
| select.mowing_efficiency | cloud CFG.PRE[1] | set_cfg via set_pre (full PRE list[10]) | Yes — full propagation | Wire on g2408 is actually `list(2)`; integration pads to 10 with hardcoded defaults. See TODO entry — defaults may clobber firmware-side values if the firmware ever stores indices 2..9. |
| select.navigation_path | cloud CFG.PROT | set_cfg (PROT int) | Yes — full propagation | `{0=Direct, 1=Smart}`. |
| select.rain_protection_resume_hours | cloud CFG.WRP[1] | set_cfg (WRP list[2]) | Yes — full propagation | Resume-hours picker. Coordinates with switch.rain_protection. |
| select.language | cloud CFG.LANG | read-only | N/A — read-only | Wire is `list(2) [text_idx, voice_idx]`. Write path not confirmed on g2408 (different language packs across firmware locales). |
| select.work_log | coordinator.session_archive | internal dispatch (render_work_log_session) | Yes — local archive | Picker over archived sessions. Picking one renders the path into the work-log camera. |
| select.zone | cloud MAP.* (mowingAreas) | MowerState.active_selection_zones (local) | N/A — local picker | Updates picker; does not write to device. Read by start_mowing button to route to the zone-mow opcode. |
| select.spot | cloud MAP.* (spotAreas) | MowerState.active_selection_spots (local) | N/A — local picker | Same pattern as zone picker. |
| select.edge | cloud MAP.* (contours) | MowerState.active_selection_edge_contours (local) | N/A — local picker | Same pattern. Default = "all perimeters" (every outer-perimeter `[N, 0]`). |
| select.active_map | cloud MAPL | dispatch_action (op:200 changeMap) | Yes — full propagation | Active-map selector. Op:200 drives device; MAPL re-poll confirms within seconds via s1p50 ping. |
| select.mowing_direction | cloud SETTINGS (mowingDirection) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only setting. Direction in degrees: 0°, 90°, 180°, 270°. |
| select.mowing_direction_mode | cloud SETTINGS (mowingDirectionMode) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. Striped / Crisscross / Chequerboard. |
| select.edge_walk_mode | cloud SETTINGS (edgeMowingWalkMode) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. walk_0 / walk_1. |

## Numbers

| Entity | Read source | Write target | App pickup | Notes |
|---|---|---|---|---|
| number.volume | cloud CFG.VOL | set_cfg (VOL int 0..100) | Yes — full propagation | Voice volume percentage. |
| number.auto_recharge_battery_pct | cloud CFG.BAT[0] | set_cfg (BAT list[6]) | Yes — full propagation | 10-25% in 5% steps. BAT[2] hardcoded — see TODO. |
| number.resume_battery_pct | cloud CFG.BAT[1] | set_cfg (BAT list[6]) | Yes — full propagation | 80-100% in 5% steps. |
| number.human_presence_alert_sensitivity | cloud CFG.REC[1] | read-only | N/A — read-only | Wire is `list(9)`. REC[2..8] not decoded → can't reconstruct → read-only. |
| number.mowing_height | cloud SETTINGS (mowingHeight) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. 30-70 mm in 5 mm steps (3-7 cm). |
| number.cutter_position | cloud SETTINGS (cutterPosition) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. |
| number.cutter_position_height | cloud SETTINGS (cutterPositionHeight) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. |
| number.edge_mowing_num | cloud SETTINGS (edgeMowingNum) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. Edge passes (1-3). |
| number.obstacle_avoidance_height | cloud SETTINGS (obstacleAvoidanceHeight) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. 5/10/15/20 cm. |
| number.obstacle_avoidance_distance | cloud SETTINGS (obstacleAvoidanceDistance) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. 10/15/20 cm. |
| number.obstacle_avoidance_sensitivity | cloud SETTINGS (obstacleAvoidanceSensitivity) | setDeviceData (SETTINGS) | Cloud-only — app does not refresh | BT-only. 1-3. |

## Sensors (read-only)

All sensors are read-only and either reflect MQTT live state or derived values.

| Entity | Source | Notes |
|---|---|---|
| sensor.battery | MQTT s3p1 | Battery %. |
| sensor.charging_status | MQTT s3p2 | Enum: not_charging / charging / charged. |
| sensor.state | MQTT s2p1 | Mower state: working / standby / paused / returning / charging / mapping / charged / updating. |
| sensor.error_code, sensor.error_description | MQTT s2p2 | Fault index + human label. Sticky until app/PIN clear. |
| sensor.position_x_m, _y_m, _north_m, _east_m | MQTT s1p4 | Charger-relative position; updated every ~5 s during mowing. |
| sensor.area_mowed_m2, .session_distance_m, .mowing_phase | MQTT s1p4 | Session telemetry; resets at session start. |
| sensor.active_selection | derived | Formatted picker state. |
| sensor.hardware_serial | cloud get_properties (s1p5) | Often unreliable due to 80001. |
| sensor.api_endpoints_accepting | cloud_client.endpoint_log | Diagnostic. |
| sensor.state_freshness_s | coordinator.freshness | Diagnostic — staleness of oldest tracked field. |
| sensor.archived_session_count | session_archive | Count of finalized sessions. |
| sensor.schedule_count | cloud SCHEDULE.0 | Count of plans across all slots. |
| sensor.cfg_keys_raw | cloud CFG (full dict) | Diagnostic — full CFG dump as attrs, plus `_last_diff` of which key changed last refresh. |
| sensor.mihis (lifetime totals) | cloud MIHIS | Lifetime mowed area / time / count. |
| sensor.mowing_height (cm), sensor.mow_mode, sensor.edgemaster | MQTT s6p2 | s6p2 frame elements; also fires as the "settings-saved tripwire" that drives the integration's debounced cloud refresh (v1.0.2a4+). |
| sensor.firmware_version | cloud DEV | Read-only metadata. |
| sensor.cloud_connected | MQTT s6p3[0] | Cloud reachability flag. |
| sensor.wifi_rssi_dbm | MQTT s6p3[1] | Signal strength. |

## Binary sensors (read-only)

| Entity | Source | Notes |
|---|---|---|
| binary_sensor.obstacle_detected | MQTT s1p53 | Live obstacle/person flag. |
| binary_sensor.rain_protection_active | MQTT s2p2 == 56 | Bad-weather signal (derived from error_code). |
| binary_sensor.positioning_failed | MQTT s2p2 == 71 | Derived. |
| binary_sensor.failed_to_return_to_station | MQTT s2p2 == 31 | Two paths: 33→31 or 48→31. |
| binary_sensor.battery_temp_low | MQTT s1p1 byte | Decoded from heartbeat. |
| binary_sensor.mowing_session_active | live_map.is_active() | Authoritative — drives session lifecycle. |
| binary_sensor.robot_tilted, _bumper_error, _robot_lifted | MQTT s1p1 bytes | Decoded from heartbeat. |
| binary_sensor.emergency_stop_activated | MQTT s1p1 byte[3] bit 7 | PIN-required latch; clears only on PIN entry. |
| binary_sensor.safety_alert_active | MQTT s1p1 byte[10] bit 1 | One-shot flag, self-clears 30-90 s. |
| binary_sensor.top_cover_open | MQTT s2p2 == 73 | Derived. |
| binary_sensor.mower_in_dock | cloud DOCK (connect_status) | More reliable than s2p1==6 inference. |
| binary_sensor.dock_in_lawn_region | cloud DOCK (in_region) | Diagnostic. |
| binary_sensor.wheel_bind_detected | derived (position vs area-mowed deltas) | Computed locally. |
| binary_sensor.edgemaster | MQTT s6p2[2] (`pre_edgemaster`) | EdgeMaster toggle mirror. Read-only — write path is BT-only. Live updates via MQTT push within seconds of any app-side save. v1.0.2a8+. |

## Buttons

| Entity | Write target | App pickup | Notes |
|---|---|---|---|
| button.start_mowing | dispatch_action (START_MOWING / EDGE / ZONE / SPOT) | Yes — full propagation | Routes via lawn_mower; respects action_mode + active_selection. |
| button.pause_mowing | dispatch_action (PAUSE) | Yes — full propagation | Available WORKING / MAPPING. |
| button.stop_mowing | dispatch_action (STOP) | Yes — full propagation | Available WORKING / MAPPING / PAUSED / RETURNING. |
| button.recharge | dispatch_action (RECHARGE) | Yes — full propagation | Greyed when CHARGING / CHARGED / RETURNING. |
| button.find_bot | dispatch_action (FIND_BOT, op:9) | Yes — fire-and-forget | Locator beep. No state echo. |
| button.finalize_session | dispatch_action (FINALIZE_SESSION) | Yes — local | Force-finalize stuck session. |
| button.refresh_from_cloud | _refresh_cloud_state() | N/A — local | On-demand cloud re-fetch. v1.0.2a6+. Diagnostic category. |

## Lawn mower

| Entity | Read source | Write target | App pickup | Notes |
|---|---|---|---|---|
| lawn_mower.dreame_a2_mower | MQTT s2p1 (state) + MowerState | dispatch_action (start/pause/dock) | Yes — full propagation | Primary control surface. Maps internal State → LawnMowerActivity. |

## Events

| Entity | Source | Notes |
|---|---|---|
| event.lifecycle | coordinator state machine | Fires: mowing_started / paused / resumed / ended, dock_arrived / departed. Logbook automatic. |
| event.alert | (reserved) | Pre-registered for the alert-tier PR. Empty event_types today. |

## Cameras / Device Tracker

| Entity | Source | Notes |
|---|---|---|
| camera.live_map | live_map.render() | Active-session path render; updates on MQTT property changes. |
| camera.work_log | render_work_log_session() | Archived-session replay; updates when select.work_log picks one. |
| camera.lidar | lidar_archive | LiDAR PCD render; service show_lidar_fullscreen fires event for Lovelace cards. |
| device_tracker.mower_location | MQTT s1p4 (X/Y) | Charger-relative metres. |

## Public services

| Service | Wire effect | App pickup | Notes |
|---|---|---|---|
| dreame_a2_mower.set_active_selection | local picker only | N/A | Updates active_selection_zones / spots / edge_contours. |
| dreame_a2_mower.mow_zone | dispatch_action (START_ZONE_MOW) | Yes | One-shot: set selection + start. |
| dreame_a2_mower.mow_edge | dispatch_action (START_EDGE_MOW) | Yes | Empty contour list = all outer-perimeters. |
| dreame_a2_mower.mow_spot | dispatch_action (START_SPOT_MOW) | Yes | One-shot. |
| dreame_a2_mower.recharge | dispatch_action (RECHARGE) | Yes | Send to dock. |
| dreame_a2_mower.find_bot | dispatch_action (FIND_BOT) | Yes — fire-and-forget | Locator beep. |
| dreame_a2_mower.lock_bot | toggles switch.child_lock (CFG.CLS) | Yes — full propagation | |
| dreame_a2_mower.suppress_fault | dispatch_action (SUPPRESS_FAULT) | Untested | Clear recoverable error. |
| dreame_a2_mower.finalize_session | dispatch_action (FINALIZE_SESSION) | N/A — local | Force-finalize stuck session. |
| dreame_a2_mower.replay_session | render_work_log_session(md5) | N/A — local | Render archived session into work-log camera. |
| dreame_a2_mower.show_lidar_fullscreen | fires `dreame_a2_mower_lidar_fullscreen` event | N/A — UI | Lovelace fullscreen popup hook. |
| dreame_a2_mower.dump_map_diagnostics | log only | N/A | Diagnostic dump of raw MAP keys. |
| dreame_a2_mower.discover_cloud_api | writes `<config>/dreame_a2_mower/api_discovery.json` | N/A | Recursive API discovery report. |
| dreame_a2_mower.set_schedule_plans | setDeviceData (SCHEDULE.0) | Yes — full propagation | Replace one schedule slot. Preserves `mode` flag (v1.0.2a2+). |
| dreame_a2_mower.refresh_cloud_state | _refresh_cloud_state() | N/A — local | Force on-demand cloud re-fetch. v1.0.2a6+. |

## How to use this doc

### "I toggled X in HA but the app doesn't reflect it"

1. Find the entity row.
2. If "App pickup" is **Cloud-only — app does not refresh**: this is the known BT-only category. HA's writes are accepted by the cloud but the device firmware doesn't apply them. The user must toggle via the Dreame app to actually change device behaviour.
3. If "App pickup" is **Yes — full propagation**: the write should have worked. Check HA logs for `[settings-write] rejected: ...` (CFG-side) or `[ai-human-write] rejected: ...` (chunked-batch) — the cloud may have rejected the write with a `code=...` payload. Also re-check the cloud directly with `/tmp/snapshot_cloud.py`.
4. If "App pickup" is **Untested**: gather evidence and update this doc.

### "I changed X in the app and HA didn't catch up"

App-side changes propagate to HA via two mechanisms:
1. **MQTT s6p2 "settings-saved" tripwire** → debounced cloud refresh (~5 s). v1.0.2a4+.
2. **Periodic 10-min cloud poll** → full state refresh.

Manually force a refresh: `service: dreame_a2_mower.refresh_cloud_state` or press `button.refresh_from_cloud`.

### "I want to add a new entity for setting Y"

1. Find Y in the cloud surface tables in `docs/research/cloud-write-reference.md`.
2. Decide if it's BT-only — if yes, the entity should be **read-only** until we have the app's write RPC.
3. If CFG-backed: add a `_build_<key>` helper and wire to `coordinator.write_setting(cfg_key, value)`.
4. If SETTINGS-backed: wire to `coordinator.write_settings(map_id, field, value)` with the `_settings_writes.settings_optimistic_write` helper for revert-on-fail.
5. Update this doc with the new row.

## Related references

- `docs/research/cloud-write-reference.md` — canonical chunked-batch + routed-action surface reference, dual-entry semantic, propagation lag.
- `docs/research/g2408-research-journal.md` — chronological RE log (incl. 2026-05-09 SETTINGS dual-entry resolution, 2026-04-26 BT-only classification).
- `docs/research/historical/g2408-protocol-PRESERVED-RAW-2026-05-06.md` — full slot-by-slot protocol decode.
- `docs/TODO.md` — open items (PRE shape, BAT[2] hardcoded, app-write RPC sniff for BT-only settings).

## Open questions / TODOs

The biggest open item this matrix surfaces: **all "Cloud-only — app does not refresh" rows can only become "Yes" after we capture the app's actual write RPC for BT-only settings.** That requires HTTPS-sniffing the Dreame app while the user taps Save on a settings page and identifying the request the app uses to drive the device (likely some MIoT siid/piid combination not yet tried, or a different routed-action target). Open as a TODO item.
