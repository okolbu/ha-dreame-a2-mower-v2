# Data policy — persistent / volatile / computed

Per spec §8, every `MowerState` field has a documented unknowns
policy. This doc is the index, kept in sync with the source-of-truth
docstrings in `custom_components/dreame_a2_mower/mower/state.py`.

## Persistent fields (RestoreEntity, last-known across HA boot)

- `total_lawn_area_m2` — s2.66[0]
- `position_x_m`, `position_y_m` — s1.4 decoded
- `position_north_m`, `position_east_m` — computed from x,y + station bearing
- `position_lat`, `position_lon` — LOCN
- `blades_life_pct`, `side_brush_life_pct` — CFG.CMS
- `total_cleaning_time_min`, `total_cleaned_area_m2`, `cleaning_count`,
  `first_cleaning_date` — CFG
- `station_bearing_deg` — config_flow option
- `action_mode` — integration state, default ALL_AREAS, set by select.action_mode
- `active_selection_zones`, `active_selection_spots` — integration state, set by services
- `child_lock_enabled` — CFG.CLS
- `volume_pct` — CFG.VOL (0..100%)
- `language_code` — CFG.LANG (raw string repr of index pair)
- `pre_zone_id` — CFG.PRE[0]
- `pre_mowing_efficiency` — CFG.PRE[1]; also s6.2[1]
- `pre_mowing_height_mm` — CFG.PRE[2]; also s6.2[0]
- `pre_edgemaster` — CFG.PRE[8]; also s6.2[2]
- `rain_protection_enabled`, `rain_protection_resume_hours` — CFG.WRP (confirmed); also pushed via s2.51 Setting.RAIN_PROTECTION
- `low_speed_at_night_enabled`, `low_speed_at_night_start_min`, `low_speed_at_night_end_min` — CFG.LOW (confirmed); also pushed via s2.51 Setting.LOW_SPEED_NIGHT
- `anti_theft_lift_alarm`, `anti_theft_offmap_alarm`, `anti_theft_realtime_location` — CFG.ATA (confirmed); also pushed via s2.51 Setting.ANTI_THEFT
- `dnd_enabled`, `dnd_start_min`, `dnd_end_min` — CFG.DND (confirmed); also pushed via s2.51 Setting.DND
- `auto_recharge_battery_pct`, `resume_battery_pct`, `custom_charging_enabled`, `charging_start_min`, `charging_end_min` — CFG.BAT (confirmed); also pushed via s2.51 Setting.CHARGING
- `led_period_enabled`, `led_in_standby`, `led_in_working`, `led_in_charging`, `led_in_error` — CFG.LIT (confirmed); also pushed via s2.51 Setting.LED_PERIOD
- `human_presence_alert_enabled`, `human_presence_alert_sensitivity` — CFG.REC (confirmed); also pushed via s2.51 Setting.HUMAN_PRESENCE_ALERT
- `language_text_idx`, `language_voice_idx` — s2.51 Setting.LANGUAGE
- `last_settings_change_unix` — s2.51 Setting.TIMESTAMP (observability hook)
- `in_progress_md5` — archive/session.py write_in_progress; md5 of the in-progress disk entry
- `pending_session_object_name` — event_occured OSS key; cleared on successful cloud fetch
- `pending_session_first_attempt_unix` — unix ts of first fetch attempt; drives max-age expiry (spec §6)
- `pending_session_attempt_count` — fetch attempt count; drives max-attempts cutoff
- `latest_session_md5` — md5 of last archived session; set by archive/session.py on archive
- `latest_session_unix_ts` — unix ts when last session ended; from session-summary JSON
- `latest_session_area_m2` — area mowed in last session (m²); from session-summary JSON
- `latest_session_duration_min` — duration of last session (minutes); from session-summary JSON
- `archived_session_count` — total sessions in on-disk archive; from archive/session.py load_index

## Volatile fields (unavailable when source is None)

- `state` — s2.1 (apk-confirmed enum)
- `battery_level` — s3.1
- `charging_status` — s3.2 (g2408 enum offset)
- `error_code` — s2.2 (apk fault index)
- `obstacle_flag` — s1.53
- `area_mowed_m2`, `total_distance_m`, `mowing_phase` — s1.4 decoded
- `wifi_rssi_dbm`, `cloud_connected` — s6.3 (g2408 overlay)
- `battery_temp_low` — s1.1 byte[6] bit
- `slam_task_label` — s2.65
- `task_state_code` — s2.56
- `manual_mode` — computed (15s no-s1.4 detector, wired in F5)
- `session_active` — derived from s2p56 in {1, 2, 4}; synced from LiveMapState each tick
- `session_started_unix` — unix ts when current session started; set on s2p56=1
- `session_track_segments` — tuple of leg-tracks (x_m, y_m); populated from s1p4 telemetry

## Computed fields (inherits source's policy)

- `position_north_m`, `position_east_m` — derived from `position_x_m`,
  `position_y_m`, `station_bearing_deg`. Inherits the persistent policy
  of its sources.
- `error_description` — derived from `error_code` via
  `mower/error_codes.describe_error()`. Inherits volatile policy of
  `error_code`.
