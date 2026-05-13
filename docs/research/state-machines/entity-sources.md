# Doc 3 — Entity → Field Dependency Matrix

> **Generated** by `tools/state_machine_audit.py`. Do not hand-edit; rerun the
> audit instead. Spec:
> `docs/superpowers/specs/2026-05-13-state-machine-audit-design.md`.

Sorted alphabetically by `<platform>.<key>` so entities reading the same
field cluster together. Status column collapses the three checks into one
worst-of indicator.


| Entity | Platform | Holder | Status | Sourcing | Idle | Reboot |
|---|---|---|---|---|---|---|
| `binary_sensor.battery_temp_low` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `binary_sensor.bumper` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `binary_sensor.dock_in_lawn_region` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `binary_sensor.drop_tilt` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `binary_sensor.edgemaster` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `binary_sensor.emergency_stop` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `binary_sensor.failed_to_return_to_station` | binary_sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['error_code'] | RED: expected False, got None | GREEN: ok |
| `binary_sensor.lift` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `binary_sensor.mower_in_dock` | binary_sensor | snapshot | GREEN | GREEN: ok | GREEN: ok | GREEN: ok |
| `binary_sensor.mowing_session_active` | binary_sensor | snapshot | GREEN | GREEN: ok | GREEN: ok | GREEN: ok |
| `binary_sensor.obstacle_detected` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `binary_sensor.photo_consent` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `binary_sensor.positioning_failed` | binary_sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['error_code'] | RED: expected False, got None | GREEN: ok |
| `binary_sensor.rain_protection_active` | binary_sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['error_code'] | RED: expected False, got None | GREEN: ok |
| `binary_sensor.safety_alert_active` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `binary_sensor.top_cover_open` | binary_sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['error_code'] | RED: expected False, got None | GREEN: ok |
| `binary_sensor.wheel_bind_active` | binary_sensor | mower_state | RED | GREEN: ok | RED: expected False, got None | GREEN: ok |
| `number.auto_recharge_battery_pct` | number | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `number.human_presence_alert_sensitivity` | number | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `number.resume_battery_pct` | number | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `number.volume` | number | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.active_selection` | sensor | other | YELLOW | GREEN: ok | YELLOW: value_fn raised: NameError: name '_format_active_selection' is not defined | YELLOW: unclassified holder (other); manual review |
| `sensor.api_endpoints_supported` | sensor | other | YELLOW | GREEN: ok | YELLOW: value_fn raised: NameError: name '_api_endpoints_value' is not defined | YELLOW: unclassified holder (other); manual review |
| `sensor.archived_session_count` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.area_mowed_m2` | sensor | mower_state | RED | GREEN: ok | RED: expected 0, got None | GREEN: ok |
| `sensor.battery_level` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.blades_life_pct` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.charging_status` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.cleaning_brush_life_pct` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.cloud_device_id` | sensor | other | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | YELLOW: unclassified holder (other); manual review |
| `sensor.data_freshness` | sensor | other | YELLOW | GREEN: ok | YELLOW: value_fn raised: NameError: name '_freshness_value' is not defined | GREEN: ok |
| `sensor.dock_x_mm` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.dock_y_mm` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.dock_yaw` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.error_code` | sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['error_code'] | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.error_description` | sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['error_code'] | YELLOW: value_fn raised: NameError: name '_describe_error_or_none' is not defined | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.firmware_version_dev` | sensor | other | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | YELLOW: unclassified holder (other); manual review |
| `sensor.first_mowing_date` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.hardware_serial` | sensor | other | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | YELLOW: unclassified holder (other); manual review |
| `sensor.language_text_idx` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.language_voice_idx` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.last_settings_change_unix` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.latest_session_area_m2` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.latest_session_duration_min` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.latest_session_unix_ts` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.lidar_archive_count` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.mac_address` | sensor | other | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | YELLOW: unclassified holder (other); manual review |
| `sensor.mowing_count` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.mowing_phase` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.novel_observations` | sensor | snapshot | RED | GREEN: ok | RED: expected 0, got None | GREEN: ok |
| `sensor.ota_capable_raw` | sensor | other | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | YELLOW: unclassified holder (other); manual review |
| `sensor.position_east_m` | sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['position_east_m'] | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.position_north_m` | sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['position_north_m'] | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.position_x_m` | sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['position_x_m'] | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.position_y_m` | sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['position_y_m'] | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.robot_maintenance_life_pct` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.s5p104_raw` | sensor | mower_state | GREEN | GREEN: ok | GREEN: ok | GREEN: ok |
| `sensor.s5p105_raw` | sensor | mower_state | GREEN | GREEN: ok | GREEN: ok | GREEN: ok |
| `sensor.s5p106_raw` | sensor | mower_state | GREEN | GREEN: ok | GREEN: ok | GREEN: ok |
| `sensor.s5p107_raw` | sensor | mower_state | GREEN | GREEN: ok | GREEN: ok | GREEN: ok |
| `sensor.s6p1_raw` | sensor | mower_state | GREEN | GREEN: ok | GREEN: ok | GREEN: ok |
| `sensor.session_distance_m` | sensor | mower_state | RED | GREEN: ok | RED: expected 0, got None | GREEN: ok |
| `sensor.session_track_point_count` | sensor | mower_state | RED | GREEN: ok | RED: expected 0, got None | GREEN: ok |
| `sensor.slam_task_label` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.task_state_code` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.total_lawn_area_m2` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.total_mowed_area_m2` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.total_mowing_time_min` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.wifi_ip` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.wifi_rssi_dbm` | sensor | mower_state | RED | RED: reads snapshot-owned field(s) from MowerState: ['wifi_rssi_dbm'] | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `sensor.wifi_ssid` | sensor | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.ai_obstacle_photos` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.anti_theft_lift_alarm` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.anti_theft_offmap_alarm` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.anti_theft_realtime_location` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.auto_recharge_standby` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.child_lock` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.custom_charging_period` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.dnd` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.frost_protection` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.human_presence_alert` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.led_in_charging` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.led_in_error` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.led_in_standby` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.led_in_working` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.led_period` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.low_speed_at_night` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.msg_alert_anomaly` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.msg_alert_consumables` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.msg_alert_error` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.msg_alert_task` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.rain_protection` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.voice_error_status` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.voice_regular_notification` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.voice_special_status` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `switch.voice_work_status` | switch | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `time.charging_end_time` | time | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `time.charging_start_time` | time | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `time.dnd_end_time` | time | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `time.dnd_start_time` | time | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `time.low_speed_at_night_end_time` | time | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
| `time.low_speed_at_night_start_time` | time | mower_state | RED | GREEN: ok | RED: expected persisted value, got None at cold-start | RED: reads MowerState (not persisted); rewire to snapshot |
