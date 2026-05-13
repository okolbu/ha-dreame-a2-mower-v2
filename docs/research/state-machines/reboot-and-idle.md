# Doc 2 — Reboot Survival + Idle Value Matrix

One row per observable field. Columns:

- **Holder**: MowerStateMachine snapshot / MowerState / LiveMapState / CloudState / coordinator-private.
- **Persisted?**: stored to disk and restored after HA restart.
- **Cold-start value**: what the field is at the moment HA finishes loading, before any MQTT/cloud traffic.
- **Idle expected**: what the field *should* be when the mower is sitting at the dock with no session active. Prescriptive — discrepancies are remediation candidates.
- **Current idle behaviour**: what the field actually is today.
- **First overwrite**: the source that next mutates the field after boot.
- **Glitch**: any known cold-start surprise.

External staleness pointers:
- Cloud CFG.DOCK has a documented 5–10 min lag; see [`cloud-write-reference.md` § Cloud-side propagation lag](../cloud-write-reference.md#cloud-side-propagation-lag).
- s3p1 (battery%) and s3p2 (charging) only push **on change**; mid-session restarts can leave them dormant.
- `live_map.is_active()` requires the `wifi_archive_store` blob to be reloaded; see `coordinator._restore_in_progress`.
- For per-entity write paths and current consumer references, cross-check [`entity-validation-matrix.md`](../entity-validation-matrix.md).
- For s2p1 / s2p2 / s1p1 / s1p4 / s3p1 / s3p2 wire semantics, see [`g2408-protocol.md`](../g2408-protocol.md).

## Snapshot fields

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `mow_session` | snapshot | yes (Store) | last value (e.g. IN_SESSION mid-restart) | BETWEEN_SESSIONS | matches | s2p1/s2p2/seed_in_session/reconcile | seed_in_session+reconcile both fight if in_progress.json + telemetry disagree |
| `current_activity` | snapshot | yes | last value | IDLE | matches | many | — |
| `location` | snapshot | yes | last value | AT_DOCK | matches | many | cloud DOCK lag suppressed when IN_SESSION+ON_LAWN |
| `charging` | snapshot | yes | last value | depends on battery state | matches | s3p2 / battery rise | s3p2 fires only on change; persisted value can be stale |
| `battery_percent` | snapshot | yes | last value | persisted value | matches | s3p1 push | (legacy MowerState.battery_level still Unknown at cold-start until s3p1 fires — see Reds) |
| `errors` | snapshot | yes | last value | empty set | matches | s2p2 error codes | — |
| `pin_required` | snapshot | yes | last value | False | matches | s1p1 heartbeat byte[3] bit 7 | — |
| `mqtt_connectivity` | snapshot | yes | STALE | STALE → ONLINE on first HB | correct | first heartbeat | — |
| `last_heartbeat_unix` | snapshot | yes | last value | persisted | matches | every heartbeat | — |
| `positioning_health` | snapshot | yes | LOCALIZED | LOCALIZED | matches | s2p2=31/33/71 | s2p2=71 disambiguates over 30 s window |
| `wifi_rssi_dbm` | snapshot | yes | last value | persisted | matches | every heartbeat | — |

## MowerState fields (non-persisted)

The `MowerState` dataclass (`custom_components/dreame_a2_mower/mower/state.py`) is held in-memory by the coordinator and is **not** persisted as a unit — every field defaults to `None` at cold-start. Reboot survival relies on either (a) the snapshot writing the durable copy back via `coordinator._sync_snapshot_to_mower_state` at coord.py:~1086, or (b) the field being repopulated by the next event source (s3p1 push, CFG poll, telemetry frame, etc.). The "Cold-start" column below is `None` for everything except the handful of fields with non-`None` dataclass defaults; "Idle expected" is the prescriptive target.

### Battery / Charging

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `battery_level` | MowerState | no | None | persisted (rewire to snapshot) | None (Unknown) | s3p1 push (only on change) | **RED — Battery=Unknown while Charging=charging across restart.** |
| `charging_status` | MowerState | no, but synced from snapshot at coord.py:1086 | snapshot.charging at boot | persisted | matches | s3p2 push | — |
| `battery_temp_low` | MowerState | no | None | False | None | s1p1 heartbeat byte[6] bit | RED — should be False idle |
| `auto_recharge_battery_pct` | MowerState | no | None | persisted CFG.BAT | None (Unknown) | CFG.BAT poll on boot | RED — CFG-backed value Unknown briefly |
| `resume_battery_pct` | MowerState | no | None | persisted CFG.BAT | None (Unknown) | CFG.BAT poll on boot | RED — CFG-backed value Unknown briefly |
| `custom_charging_enabled` | MowerState | no | None | persisted CFG.BAT | None (Unknown) | CFG.BAT poll on boot | RED — CFG-backed value Unknown briefly |
| `charging_start_min` | MowerState | no | None | persisted CFG.BAT | None (Unknown) | CFG.BAT poll on boot | RED — CFG-backed value Unknown briefly |
| `charging_end_min` | MowerState | no | None | persisted CFG.BAT | None (Unknown) | CFG.BAT poll on boot | RED — CFG-backed value Unknown briefly |
| `auto_recharge_standby_enabled` | MowerState | no | None | persisted CFG.STUN | None (Unknown) | CFG.STUN poll on boot | RED — CFG-backed value Unknown briefly |

### Position / Localization

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `position_x_m` | MowerState | no | None | persisted (rewire) | None | s1p4 telemetry | RED if reboot during session |
| `position_y_m` | MowerState | no | None | persisted (rewire) | None | s1p4 telemetry | RED if reboot during session |
| `position_north_m` | MowerState | no | None | persisted (rewire) | None | computed when x/y arrive | RED if reboot during session |
| `position_east_m` | MowerState | no | None | persisted (rewire) | None | computed when x/y arrive | RED if reboot during session |
| `position_heading_deg` | MowerState | no | None | persisted (rewire) | None | s1p4 telemetry heading byte | — |
| `position_lat` | MowerState | no | None | persisted | None | LOCN routed action | — |
| `position_lon` | MowerState | no | None | persisted | None | LOCN routed action | — |
| `station_bearing_deg` | MowerState | no | None | persisted (config_flow option) | None until option-load wires it | config_flow option apply on boot | — |
| `slam_task_label` | MowerState | no | None | last localization label | None | s2p65 | — |

### Error / Safety state

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `error_code` | MowerState | no | None | None when no error | None | s2p2 error events | — |
| `obstacle_flag` | MowerState | no | None | False | None (Unknown) | s2p2 events | RED — should be False idle |
| `drop_tilt` | MowerState | no | None | False | None (Unknown) | s1p1 heartbeat byte[1] bit 1 | RED — should be False idle |
| `bumper` | MowerState | no | None | False | None (Unknown) | s1p1 heartbeat byte[1] bit 0 | RED — should be False idle |
| `lift` | MowerState | no | None | False | None (Unknown) | s1p1 heartbeat byte[2] bit 1 | RED — should be False idle |
| `emergency_stop` | MowerState | no, but mirrored to snapshot.pin_required | None | False | None | s1p1 heartbeat byte[3] bit 7 | snapshot covers reboot survival via pin_required |
| `safety_alert_active` | MowerState | no | None | False | None | s1p1 heartbeat byte[10] bit 1 | one-shot, self-clears 30–90s |
| `wheel_bind_active` | MowerState | no | None | False | None | cross-frame s1p4 diff (wheel_bind.py) | — |
| `wheel_bind_consecutive_frames` | MowerState | no | 0 (dataclass default) | 0 | 0 | cross-frame s1p4 diff | — |
| `manual_mode` | MowerState | no | None | None (off) | None | 15s no-s1p4 detector (F5) | — |

### Session telemetry

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `area_mowed_m2` | MowerState | no | None | 0 between sessions | None (Unknown) | s1p4 telemetry while in session | **RED — should be 0, not Unknown.** |
| `session_distance_m` | MowerState | no | None | 0 between sessions | None (Unknown) | LiveMapState.total_distance_m() integrate | RED — should be 0, not Unknown |
| `session_started_unix` | MowerState | no | None | None | None | task_state_code None→non-None | — |
| `session_track_segments` | MowerState | no | None | None (or restored leg list while IN_SESSION) | None | LiveMapState legs / archive restore | — |
| `task_state_code` | MowerState | no | None | None | None | s2p56 | — |
| `task_total_area_m2` | MowerState | no | None | None | None | s1p4 bytes [26-28] | — |
| `target_area_m2` | MowerState | no | None | full-lawn area when no selection | None until cloud poll | _compute_target_area_m2 on cloud refresh | — |
| `mowing_phase` | MowerState | no | None | None | None | s1p4 byte[8] | — |
| `total_lawn_area_m2` | MowerState | no | None | persisted CFG.LAWN | None (Unknown) | s2p66[0] / CFG poll | — |
| `total_mowing_time_min` | MowerState | no | None | persisted | None (Unknown) | CFG poll | — |
| `total_mowed_area_m2` | MowerState | no | None | persisted | None (Unknown) | CFG poll | — |
| `mowing_count` | MowerState | no | None | persisted | None (Unknown) | CFG poll | — |
| `first_mowing_date` | MowerState | no | None | persisted | None (Unknown) | CFG poll | — |

### Pending session / archive bookkeeping

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `pending_session_object_name` | MowerState | yes (in_progress.json) | restored value or None | None when no pending fetch | matches | s4p1 event_occured | — |
| `pending_session_first_event_unix` | MowerState | yes | restored | None | matches | s4p1 event_occured | — |
| `pending_session_last_attempt_unix` | MowerState | yes | restored | None | matches | _do_oss_fetch | — |
| `pending_session_attempt_count` | MowerState | yes | restored | None | matches | _do_oss_fetch | — |
| `latest_session_md5` | MowerState | yes | restored | last md5 string | matches | archive/session.py finalize | — |
| `latest_session_unix_ts` | MowerState | yes | restored | last session end | matches | session-summary parse | — |
| `latest_session_area_m2` | MowerState | yes | restored | last session m² | matches | session-summary parse | — |
| `latest_session_duration_min` | MowerState | yes | restored | last session minutes | matches | session-summary parse | — |
| `archived_session_count` | MowerState | yes | restored | archive count | matches | archive/session.py load_index | — |
| `latest_lidar_object_name` | MowerState | no | None | None when no pending fetch | None | s99p20 announcement | — |
| `archived_lidar_count` | MowerState | yes | restored | archive count | matches | archive/lidar.py load_index | — |

### Action intent (F3 — user selections)

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `action_mode` | MowerState | yes (RestoreEntity via select.action_mode) | restored value or ALL_AREAS | last selection | matches | select.action_mode user pick | — |
| `active_selection_zones` | MowerState | yes (RestoreEntity) | restored or () | last selection | matches | set_active_selection service | — |
| `active_selection_spots` | MowerState | yes (RestoreEntity) | restored or () | last selection | matches | set_active_selection service | — |
| `active_selection_edge_contours` | MowerState | yes (RestoreEntity via select.edge) | restored or () | last selection | matches | select.edge user pick | — |

### Settings — CFG.PRE / per-map mowing

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `pre_zone_id` | MowerState | no | None | persisted CFG.PRE | None (Unknown) | CFG.PRE poll / s6p2[1] push | RED — CFG-backed value Unknown briefly |
| `pre_mowing_efficiency` | MowerState | no | None | persisted CFG.PRE | None (Unknown) | CFG.PRE poll / s6p2[1] push | RED — CFG-backed value Unknown briefly |
| `pre_mowing_height_mm` | MowerState | no | None | persisted CFG.PRE | None (Unknown) | CFG.PRE poll / s6p2[0] push | RED — CFG-backed value Unknown briefly |
| `pre_edgemaster` | MowerState | no | None | persisted CFG.PRE | None (Unknown) | CFG.PRE poll / s6p2[2] push | RED — CFG-backed value Unknown briefly |
| `settings_mowing_height` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_mowing_direction` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_mowing_direction_mode` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_cutter_position` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_cutter_position_height` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_edge_mowing_num` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_edge_mowing_auto` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_edge_mowing_safe` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_edge_mowing_obstacle_avoidance` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_edge_mowing_walk_mode` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_obstacle_avoidance_enabled` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_obstacle_avoidance_height` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_obstacle_avoidance_distance` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_obstacle_avoidance_sensitivity` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |
| `settings_obstacle_avoidance_ai` | MowerState | no | None | persisted per-map | None | _apply_cloud_state_to_mower_state | — |

### Settings — global toggles & schedules (CFG-backed)

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `child_lock_enabled` | MowerState | no | None | persisted CFG.CLS | None (Unknown) | CFG.CLS poll | RED — CFG-backed value Unknown briefly |
| `volume_pct` | MowerState | no | None | persisted CFG.VOL | None (Unknown) | CFG.VOL poll | RED — CFG-backed value Unknown briefly |
| `language_code` | MowerState | no | None | persisted CFG.LANG | None | CFG.LANG poll | — |
| `language_text_idx` | MowerState | no | None | persisted | None | s2p51 LANGUAGE push | — |
| `language_voice_idx` | MowerState | no | None | persisted | None | s2p51 LANGUAGE push | — |
| `rain_protection_enabled` | MowerState | no | None | persisted CFG.WRP | None (Unknown) | CFG.WRP poll | RED — CFG-backed value Unknown briefly |
| `rain_protection_resume_hours` | MowerState | no | None | persisted CFG.WRP | None (Unknown) | CFG.WRP poll | RED — CFG-backed value Unknown briefly |
| `low_speed_at_night_enabled` | MowerState | no | None | persisted CFG.LOW | None (Unknown) | CFG.LOW poll | RED — CFG-backed value Unknown briefly |
| `low_speed_at_night_start_min` | MowerState | no | None | persisted CFG.LOW | None (Unknown) | CFG.LOW poll | RED — CFG-backed value Unknown briefly |
| `low_speed_at_night_end_min` | MowerState | no | None | persisted CFG.LOW | None (Unknown) | CFG.LOW poll | RED — CFG-backed value Unknown briefly |
| `anti_theft_lift_alarm` | MowerState | no | None | persisted CFG.ATA | None (Unknown) | CFG.ATA poll | RED — CFG-backed value Unknown briefly |
| `anti_theft_offmap_alarm` | MowerState | no | None | persisted CFG.ATA | None (Unknown) | CFG.ATA poll | RED — CFG-backed value Unknown briefly |
| `anti_theft_realtime_location` | MowerState | no | None | persisted CFG.ATA | None (Unknown) | CFG.ATA poll | RED — CFG-backed value Unknown briefly |
| `dnd_enabled` | MowerState | no | None | persisted CFG.DND | None (Unknown) | CFG.DND poll | RED — CFG-backed value Unknown briefly |
| `dnd_start_min` | MowerState | no | None | persisted CFG.DND | None (Unknown) | CFG.DND poll | — |
| `dnd_end_min` | MowerState | no | None | persisted CFG.DND | None (Unknown) | CFG.DND poll | — |
| `led_period_enabled` | MowerState | no | None | persisted CFG.LIT | None (Unknown) | CFG.LIT poll | — |
| `led_in_standby` | MowerState | no | None | persisted CFG.LIT | None (Unknown) | CFG.LIT poll | — |
| `led_in_working` | MowerState | no | None | persisted CFG.LIT | None (Unknown) | CFG.LIT poll | — |
| `led_in_charging` | MowerState | no | None | persisted CFG.LIT | None (Unknown) | CFG.LIT poll | — |
| `led_in_error` | MowerState | no | None | persisted CFG.LIT | None (Unknown) | CFG.LIT poll | — |
| `human_presence_alert_enabled` | MowerState | no | None | persisted CFG.REC | None (Unknown) | CFG.REC poll | — |
| `human_presence_alert_sensitivity` | MowerState | no | None | persisted CFG.REC | None (Unknown) | CFG.REC poll | — |
| `photo_consent` | MowerState | no | None | persisted CFG.REC[7] | None (Unknown) | CFG.REC poll | — |
| `frost_protection_enabled` | MowerState | no | None | persisted CFG.FDP | None (Unknown) | CFG.FDP poll | — |
| `ai_obstacle_photos_enabled` | MowerState | no | None | persisted CFG.AOP | None (Unknown) | CFG.AOP poll | — |
| `navigation_path_smart` | MowerState | no | None | persisted CFG.PROT | None (Unknown) | CFG.PROT poll | — |
| `msg_alert_anomaly` | MowerState | no | None | persisted CFG.MSG_ALERT | None (Unknown) | CFG.MSG_ALERT poll | — |
| `msg_alert_error` | MowerState | no | None | persisted CFG.MSG_ALERT | None (Unknown) | CFG.MSG_ALERT poll | — |
| `msg_alert_task` | MowerState | no | None | persisted CFG.MSG_ALERT | None (Unknown) | CFG.MSG_ALERT poll | — |
| `msg_alert_consumables` | MowerState | no | None | persisted CFG.MSG_ALERT | None (Unknown) | CFG.MSG_ALERT poll | — |
| `voice_regular_notification` | MowerState | no | None | persisted CFG.VOICE | None (Unknown) | CFG.VOICE poll | — |
| `voice_work_status` | MowerState | no | None | persisted CFG.VOICE | None (Unknown) | CFG.VOICE poll | — |
| `voice_special_status` | MowerState | no | None | persisted CFG.VOICE | None (Unknown) | CFG.VOICE poll | — |
| `voice_error_status` | MowerState | no | None | persisted CFG.VOICE | None (Unknown) | CFG.VOICE poll | — |
| `last_settings_change_unix` | MowerState | no | None | persisted | None | s2p51 TIMESTAMP push | — |

### Dock / Map (CFG.DOCK)

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `dock_in_lawn_region` | MowerState | no | None | persisted CFG.DOCK | None (Unknown) | CFG.DOCK poll | YELLOW — 5–10 min cloud lag |
| `dock_x_mm` | MowerState | no | None | persisted CFG.DOCK | None (Unknown) | CFG.DOCK poll | YELLOW — 5–10 min cloud lag |
| `dock_y_mm` | MowerState | no | None | persisted CFG.DOCK | None (Unknown) | CFG.DOCK poll | YELLOW — 5–10 min cloud lag |
| `dock_yaw` | MowerState | no | None | persisted CFG.DOCK | None (Unknown) | CFG.DOCK poll | YELLOW — 5–10 min cloud lag |
| `dock_near_x` | MowerState | no | None | persisted CFG.DOCK | None (Unknown) | CFG.DOCK poll | YELLOW — 5–10 min cloud lag |
| `dock_near_y` | MowerState | no | None | persisted CFG.DOCK | None (Unknown) | CFG.DOCK poll | YELLOW — 5–10 min cloud lag |
| `dock_near_yaw` | MowerState | no | None | persisted CFG.DOCK | None (Unknown) | CFG.DOCK poll | YELLOW — 5–10 min cloud lag |
| `dock_path_connect` | MowerState | no | None | persisted CFG.DOCK | None (Unknown) | CFG.DOCK poll | YELLOW — 5–10 min cloud lag |

### Wi-Fi / Network

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `wifi_rssi_dbm` | MowerState | no, but synced from snapshot | snapshot value at boot (CFG.NET fallback within ~1 cycle) | persisted | matches | s1p1 byte[17] / CFG.NET fallback | — |
| `wifi_ssid` | MowerState | no | None | persisted CFG.NET.current | None (Unknown) | CFG.NET poll | — |
| `wifi_ip` | MowerState | no | None | persisted CFG.NET.list | None (Unknown) | CFG.NET poll | — |
| `cloud_connected` | MowerState | no | None | True | None (Unknown) | s6p3[0] | YELLOW — should be True idle |
| `wifi_map_data` | MowerState | no | None | last cached dict | None | cloud_client.fetch_wifi_map | — |

### Device metadata

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `hardware_serial` | MowerState | no | None | persisted CFG.DEV.sn (never changes) | None until CFG poll | CFG.DEV poll | — |
| `firmware_version` | MowerState | no | None | persisted CFG.DEV.fw | None until CFG poll | CFG.DEV poll | — |
| `ota_capable_raw` | MowerState | no | None | persisted CFG.DEV.ota | None until CFG poll | CFG.DEV poll | — |

### Consumables (CFG.CMS)

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `blades_life_pct` | MowerState | no | None | persisted CFG.CMS | None (Unknown) | CFG.CMS poll / s2p51 CONSUMABLES | — |
| `cleaning_brush_life_pct` | MowerState | no | None | persisted CFG.CMS | None (Unknown) | CFG.CMS poll / s2p51 CONSUMABLES | — |
| `robot_maintenance_life_pct` | MowerState | no | None | persisted CFG.CMS | None (Unknown) | CFG.CMS poll / s2p51 CONSUMABLES | — |

### Debug / Diagnostic raw slots

| Field | Holder | Persisted? | Cold-start | Idle expected | Current idle | First overwrite | Glitch |
|---|---|---|---|---|---|---|---|
| `s5p104_raw` | MowerState | no | None | None | None | s5p104 push | — |
| `s5p105_raw` | MowerState | no | None | None | None | s5p105 push | — |
| `s5p106_raw` | MowerState | no | None | None | None | s5p106 push | — |
| `s5p107_raw` | MowerState | no | None | None | None | s5p107 push | — |
| `s6p1_raw` | MowerState | no | None | None | None | s6p1 push | — |

## LiveMapState fields

| Field | Persisted? | Cold-start | Idle expected | First overwrite |
|---|---|---|---|---|
| `legs` | yes (in_progress.json) | last value if file present, else [] | [] when no session | per-telemetry packet |
| `started_unix` | yes | last value or None | None when no session | session start |
| `latest_position` | no (derived from `legs[-1][-1]`) | None or last leg tail | None when no session | per-telemetry packet |
| `total_distance_m` | no (computed from legs) | 0.0 or computed-from-restored | 0.0 when no session | per-telemetry packet |
| `is_active()` | n/a (predicate) | False unless wifi_archive_store re-loaded a live blob | False | coordinator._restore_in_progress decides |

## CloudState fields

CloudState is ephemeral by design — every field is None or empty at cold-start and is filled by the next cloud poll (typically within ~10 s, with the documented 5–10 min CFG.DOCK lag for that subtree specifically). Consumers that need reboot persistence either:

1. **Rewire to the snapshot** when the snapshot already tracks the same semantic (battery, charging, pin_required, RSSI), or
2. **Accept the brief Unknown window** with `available = False` until the first cloud refresh lands.

Entities reading CloudState that need reboot persistence are inherently `YELLOW` in the audit; see [`entity-validation-matrix.md`](../entity-validation-matrix.md) for per-entity colour.

| Field group | Source | Cold-start | Idle expected | First overwrite |
|---|---|---|---|---|
| `device` (did, model, fw, sn, name, online) | cloud_client.fetch_devices | empty/None | populated dict | first cloud poll (~10 s) |
| `maps` (by_id_canonical) | cloud_client.fetch_maps | {} | populated dict | first cloud poll |
| `settings.by_map_id_canonical` | cloud CFG poll | {} | populated dict | first CFG batch |
| `dock` (CFG.DOCK subtree) | cloud CFG poll | None | populated dict | first CFG.DOCK poll (5–10 min lag) |
| `consumables` (CFG.CMS) | cloud CFG poll | None | populated dict | first CFG.CMS poll |
| `schedule` (CFG.SCHED) | cloud CFG poll | None | populated dict | first CFG.SCHED poll |
| `active_map_id` | derived from cloud | None | last selected | first cloud poll |
| `cameras` (per-map cached frames) | cloud_client.fetch_camera | {} | last fetched | per-map fetch |

## Remediation buckets

1. **Rewire to snapshot** — Battery, position (x/y/north/east/heading), error_code, charging_status (if any consumer reads `MowerState.charging_status` for reboot survival rather than the synced value), wifi_rssi_dbm.
2. **Default to literal idle** — area accumulators (`area_mowed_m2`, `session_distance_m`), session-scoped distances, boolean fault flags (`obstacle_flag`, `drop_tilt`, `bumper`, `lift`, `battery_temp_low` → False by default at boot).
3. **Mark unavailable** — live-telemetry rates, current-session ETA, things only meaningful mid-session; CFG-backed settings during the brief poll window can show `available = False` rather than Unknown.

The audit verifier (`tools/state_machine_audit.py`) produces the ranked list automatically; this matrix documents the prescriptive targets.
