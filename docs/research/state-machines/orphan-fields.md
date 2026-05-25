# MowerState orphan fields

Fields declared in `MowerState`
(`custom_components/dreame_a2_mower/mower/state.py`) that no
audit-discovered entity reads directly. After the F10 detection
improvements and prune, the remaining orphans (count: **22**) all fall
into legitimate "used internally" or "non-entity surface" categories.

The audit's orphan detector deliberately stays narrow — it flags fields
with no entity consumer so we can periodically review whether they're
still needed. Internal-use orphans are tracked here so reviewers don't
re-derive their purpose every release.

> **How to refresh this list.** Re-run the audit:
> ```bash
> python3 -m tools.state_machine_audit | tail
> ```
> The "Summary: ... + N orphan MowerState fields" line is the canonical
> count. The full sorted list is in the orphan-fields section of the
> audit's stdout (above the summary).

---

## Bucket I — Read internally (no entity surface)

These fields are written or read by coordinator code, archive code,
live_map code, or other internal modules but never surfaced as an HA
entity. Pruning them would break internal logic.

| Field | Used by (internal reader) | Notes |
|---|---|---|
| `active_selection_edge_contours` | `button.py:101` (edge-mow dispatch), `select.py:1232` (edge-contour select holds it) | Read by select.py via `self.coordinator.data...`; the select entity's `current_option` is a class property, not a kwarg-driven `value_fn`, so the audit's AST walker misses it. |
| `active_selection_spots` | `coordinator/_writes.py § dispatch_action (SPOT)` (SPOT dispatch), `sensor.py:60` (spots sensor) | Same class-property pattern as above. |
| `active_selection_zones` | `coordinator/_writes.py § dispatch_action (ZONE)` (ZONE dispatch), `sensor.py:55` (zones sensor), `select.py:1080` | Same class-property pattern as above. |
| `cloud_connected` | (write-only on g2408) | Decoded from `s6.3[0]` by `mower/property_mapping.py:121`. No entity reads it currently — the cloud connectivity signal is exposed via the cloud-state diagnostic sensors. Kept because the s6.3 disambiguator references it; pruning would require restructuring the property-mapping wire decoder. Candidate for future removal once a `binary_sensor.cloud_connected` is wired. |
| `latest_lidar_object_name` | `coordinator/_lidar_oss.py § _handle_lidar_object_name` (LiDAR fetch trigger) | Coordinator uses change-detection on this field to kick off OSS LiDAR fetches; not user-visible. |
| `pending_session_attempt_count` | `coordinator/_session.py § _do_oss_fetch (retry counter)`, `live_map/finalize.py` | Internal retry counter for OSS session-summary fetches. |
| `pending_session_first_event_unix` | `coordinator/_session.py § _do_oss_fetch (retry window)`, `live_map/finalize.py:111` | Internal — finalize-gate retry window. |
| `pending_session_last_attempt_unix` | `coordinator/_session.py § _do_oss_fetch (retry interval)`, `live_map/finalize.py:112` | Internal — finalize-gate retry interval. |
| `pending_session_object_name` | `coordinator/_session.py § _do_oss_fetch (pending object_name)` (`_do_oss_fetch`) | Internal — OSS object pending fetch. |
| `position_heading_deg` | `coordinator/_rendering.py § _current_mower_heading`, `map_render/trail.py § render_with_trail` | Read by the map renderer to rotate the mower icon. Not an entity — used by the camera proxy / map render pipeline. |
| `position_lat` | `device_tracker.py:77` | Read by the `device_tracker` platform (not in the audit's PLATFORMS list). |
| `position_lon` | `device_tracker.py:82` | Same — `device_tracker` platform. |
| `pre_mowing_height_mm` | `select.py:198` (PRE wire builder) | Used to rebuild the PRE list when writing a setting; the user-facing height is exposed via `number.settings_mowing_height` which reads a different field. |
| `pre_zone_id` | `select.py:197` (PRE wire builder) | Same — write-path helper for the PRE wire format. |
| `session_started_unix` | `coordinator/_mqtt_handlers.py § _on_state_update (live_map sync)` (live_map sync) | Internal — stamped by live_map state sync, used for session-archive bookkeeping. |
| `settings_edge_mowing_auto` | `switch.py:829` (class-attr translation_key) | Class-attribute switch entity (no value_fn lambda) — read via the snapshot-attr base. Audit can't yet walk all class-attribute readers in switch.py. |
| `settings_edge_mowing_obstacle_avoidance` | `switch.py:929` (class-attr translation_key) | Same pattern. |
| `settings_edge_mowing_safe` | `switch.py:880` (class-attr translation_key) | Same pattern. |
| `settings_obstacle_avoidance_ai` | `switch.py:1153` (toggle handler) | Read by an `async_turn_on/off` handler, not a value_fn. |
| `settings_obstacle_avoidance_enabled` | `switch.py:978` (class-attr translation_key) | Same class-attr pattern. |
| `task_total_area_m2` | `coordinator/_writes.py § dispatch_action (live area-mowed gate)` (live area-mowed gate) | Internal — used to gate live area-mowed updates during an active session. |
| `wheel_bind_consecutive_frames` | `coordinator/_property_apply.py § _apply_s1p4_telemetry (wheel-bind detector accumulator)` (wheel-bind detector state) | Internal — accumulator state for the wheel-bind consecutive-frames detector. |

## Bucket D — DeviceInfo / future

(empty after F10) — Fields previously kept "for future correlation" with
no internal reader were pruned. If a future feature needs a previously
pruned field, restore the declaration and add the write site as part of
the new feature's diff.

---

## Removed in F10 (2026-05-14)

These eight fields were declared but had no readers (the audit's orphan
list ran to 43 at the start of F10). F9's investigation confirmed each
was either a stillborn placeholder or "future correlation" speculation
that never landed; F10 deleted them along with their dead writes.

- **`wifi_map_data`** — declared only; no writer, no reader. The wifi-map
  flow uses `_wifi_archive_store` instead.
- **`manual_mode`** — computed-field placeholder; F5 (the manual-mode
  detector) was never wired.
- **`station_bearing_deg`** — declared for future GPS-frame rotation; no
  writer landed.
- **`latest_session_md5`** — written but no reader; per-map session
  dedup uses `start_ts` from the session-archive index (see
  `project_g2408_session_archive_quirks` memory note).
- **`dock_near_x`**, **`dock_near_y`**, **`dock_near_yaw`**,
  **`dock_path_connect`** — written from the DOCK cloud payload but
  never read; the "future correlation" comment in `state.py` was
  speculative.

## Audit-detection improvements applied in F10

Three changes to the audit tools dropped the false-positive orphan rate
from ~25 to ~14 (the 22 number after the prune reflects the broader
detection — without these improvements the post-prune count would have
been higher).

- **Improvement A — snapshot-alias.** `find_orphan_fields` now also
  treats `coord.state_machine.snapshot().X` reads as consuming
  `MowerState.X` (same-name) plus any aliased name in
  `_SNAPSHOT_TO_MOWER_STATE_ALIASES` (currently just
  `battery_percent → battery_level`).
- **Improvement B — getattr regex.** `_fields_read_from_mower_state`
  now matches `getattr(coord.data, "field", ...)` /
  `getattr(self.coordinator.data, "field", ...)` defensive-read idioms.
- **Improvement C — broader entity-description suffix.** The AST walker
  in `state_machine_audit_discover.py` now matches both
  `*EntityDescription` and `*SelectDescription` (catches
  `DreameA2SettingsSelectDescription` in `select.py`).

The remaining false positives concentrate on switch.py class-attribute
entities (no `value_fn` kwarg to parse) and on `device_tracker.py` /
`button.py` platforms that aren't in the audit's PLATFORMS list. Those
are picked up by the entity-validation matrix instead.
