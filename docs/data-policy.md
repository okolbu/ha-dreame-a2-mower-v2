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

## Computed fields (inherits source's policy)

- `position_north_m`, `position_east_m` — derived from `position_x_m`,
  `position_y_m`, `station_bearing_deg`. Inherits the persistent policy
  of its sources.
- `error_description` — derived from `error_code` via
  `mower/error_codes.describe_error()`. Inherits volatile policy of
  `error_code`.
