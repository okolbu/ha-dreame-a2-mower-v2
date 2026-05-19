# Integration Audit — Meta Pass

**Date:** 2026-05-19
**Status:** in progress — populated task-by-task per plan
**Plan:** `docs/superpowers/plans/2026-05-19-integration-audit-meta.md`
**Parent spec:** `docs/superpowers/specs/2026-05-19-integration-audit-overview.md`

This document is the shared ground-truth referenced by all four subsequent
audit blocks. It is read-only output of the meta pass — no remediation lives
here.

## 1. Module map

### Top-level (`custom_components/dreame_a2_mower/`)

| File | LOC | Purpose |
|---|---|---|
| `__init__.py` | 279 | HA entrypoint: setup/unload entry, platform forward, services register |
| `_devices.py` | 96 | SN-based unique_id + DeviceInfo factories for mower + per-map sub-devices |
| `_lidar_migration.py` | 75 | One-shot flat→per-map lidar archive layout migration (sync, executor-safe) |
| `_migration.py` | 468 | Entity-registry migration v1→v2: entry_id to SN-based unique_id rewrite |
| `_render_direction.py` | 76 | Infer dominant mow direction from cloud track_segments for stripe overlay |
| `_render_dotted.py` | 51 | Dotted-polygon drawing helper for EDGE/SPOT idle-preview outlines |
| `_render_stripes.py` | 127 | Pre-start stripe overlay renderer (alternating bands at inferred mow angle) |
| `_resources.py` | 117 | Embedded mower icon asset (64×64 RGBA, pre-rotated 270° CCW) |
| `_settings_writes.py` | 77 | Shared optimistic-write helper for SETTINGS-driven switch/select/number entities |
| `binary_sensor.py` | 276 | Binary sensor platform: error, charging, rain, human-presence, and status flags |
| `button.py` | 324 | Button platform: Start / Pause / Stop / Recharge + Finalize + Refresh-Cloud buttons |
| `calendar.py` | 116 | Calendar platform: archived sessions as read-only CalendarEvents |
| `camera.py` | 962 | **>800 — refactor candidate.** Camera platform: base map + live-trail + LiDAR + WiFi PNG endpoints with aiohttp views |
| `cloud_client.py` | 2197 | **>800 — refactor candidate.** Cloud HTTP auth + RPC (get/set_properties, action) + OSS signed-URL fetch |
| `cloud_state.py` | 128 | CloudState frozen dataclass container for all cloud-fetched data (CFG, SETTINGS, SCHEDULE, MAP, etc.) |
| `config_flow.py` | 146 | Config + options flow: credential collection + archive-retention / station-bearing options |
| `const.py` | 143 | Domain constants, platform list, logger, CONF_* keys, default values |
| `device_tracker.py` | 96 | Device tracker platform: GPS lat/lon from telemetry, RestoreEntity |
| `diagnostics.py` | 112 | HA diagnostics dump: redacted config + MowerState + capabilities + observability snapshots |
| `event.py` | 133 | Event platform: lifecycle (start/pause/resume/end/dock) and alert event entities |
| `lawn_mower.py` | 155 | LawnMower platform: primary mowing state + start/pause/stop/dock controls |
| `logbook.py` | 118 | Logbook describers for lifecycle and alert EventEntity instances |
| `map_decoder.py` | 794 | Cloud-JSON map decoder: MAP.* batch → typed MapData (boundary, zones, exclusions, dock) |
| `map_render.py` | 1283 | **>800 — refactor candidate.** PNG renderer for base map + zone/spot/trail/obstacle/WiFi overlays |
| `mqtt_client.py` | 406 | Dumb-pipe MQTT transport (paho wrapper): connect, subscribe, callback dispatch |
| `number.py` | 683 | Number platform: voice volume + battery thresholds settable via coordinator write_setting |
| `select.py` | 1990 | **>800 — refactor candidate.** Select platform: action-mode picker + per-map enum CFG settings (efficiency, blade height, etc.) |
| `sensor.py` | 1499 | **>800 — refactor candidate.** Sensor platform: battery, state, area, dist, telemetry, freshness, and session-summary sensors |
| `services.py` | 711 | Service handlers: zone/spot/edge/all-area mowing, inject-archive, and replay services |
| `session_card.py` | 645 | Session summary builder: flat attribute dict for dashboard cards (pure Python, no HA imports) |
| `switch.py` | 1308 | **>800 — refactor candidate.** Switch platform: settable boolean CFG settings (DnD, rain, child lock, anti-theft, etc.) |
| `time.py` | 167 | Time platform: read-only display of DnD / low-speed-night / charging schedule slots |
| `wifi_archive_store.py` | 321 | Disk-backed archive of cloud WiFi heatmap OSS objects; dedup by object_name |
| `wifi_map_render.py` | 118 | PNG renderer for WiFi RSSI heatmap from cloud OSS JSON |
| `wifi_match.py` | 190 | WiFi heatmap → map_id correlator via RSSI fingerprint matching |

### `coordinator/`

| File | LOC | Purpose |
|---|---|---|
| `__init__.py` | 76 | Class assembly + public re-exports (`DreameA2MowerCoordinator`, helpers, slot maps) |
| `_core.py` | 828 | **>800 — refactor candidate.** `__init__`, `_async_update_data`, properties, `_init_cloud`, `_init_mqtt` |
| `_refreshers.py` | 802 | **>800 — refactor candidate.** All `_refresh_*` cloud-refresh cycles |
| `_session.py` | 925 | **>800 — refactor candidate.** Restore / persist / finalize / replay / work-log render |
| `_mqtt_handlers.py` | 810 | **>800 — refactor candidate.** MQTT message routing, state-update glue, event_occured, MAPL apply |
| `_property_apply.py` | 599 | Module-level helpers + constants — pure `(siid, piid, value) → MowerState` functions |
| `_writes.py` | 543 | `write_*` (settings, schedule, ai_human, action) + `dispatch_action` + `start_mowing_*` |
| `_lidar_oss.py` | 621 | LiDAR archive + cloud-OSS fetch handlers |
| `_device_sync.py` | 395 | Map sub-device registry sync + emergency-stop banner + `_fire_*` lifecycle events |
| `_cloud_state.py` | 366 | `cloud_state` apply to MowerState + map fetch / persist |
| `_rendering.py` | 347 | Live-map render, live-trail re-render, last-session-obstacle overlay |
| `_recorder_merge.py` | 432 | Recorder-merge safety net: backfills session sample gaps from HA recorder |
| `_restore_merge.py` | 129 | Pure restore-then-merge logic for in_progress.json reconciliation on restart |
| `_snapshot.py` | 139 | Full firmware-state snapshot at session-start (per_map + device_wide + peripheral + forensic) |
| `_wifi_archive.py` | 246 | WiFi heatmap archive refresh + matcher plumbing |

### `mower/`

| File | LOC | Purpose |
|---|---|---|
| `actions.py` | 252 | Typed action enum + (siid, aiid) dispatch table; constructs wire payloads, no HA imports |
| `capabilities.py` | 74 | g2408 capability flags — frozen constants derived from MQTT probe logs |
| `error_codes.py` | 89 | Mower error code → human description map (apk fault index) |
| `property_mapping.py` | 179 | `(siid, piid) → field_name` dispatch table with optional disambiguator callables |
| `state.py` | 619 | `MowerState` dataclass — all device fields with §2.1 citations; no HA imports |
| `state_machine.py` | 764 | `MowerStateMachine` — multi-dim mow-session state (MQTT + cloud inputs → StateSnapshot) |
| `state_snapshot.py` | 204 | `StateSnapshot` dataclass + dimension enums (imported without pulling state-machine logic) |

### `protocol/`

| File | LOC | Purpose |
|---|---|---|
| `__init__.py` | 50 | Re-exports public protocol symbols (decoders, enums, error types) |
| `_jsonable.py` | 33 | Coerce integration dataclasses to plain JSON-safe structures (HA event-stream compat) |
| `api_log.py` | 48 | One-line structural log summaries for cloud API responses (scrubs secrets) |
| `batch_grouper.py` | 53 | Groups cloud batch-response keys by dot-prefix family (MAP.*, SETTINGS.*, etc.) |
| `cfg_action.py` | 195 | Typed wrappers for siid:2 aiid:50 routed-action calls (CFG/PRE/DOCK/CMS get/set/action) |
| `cloud_map_geom.py` | 56 | Geometry helpers for cloud-map JSON: apply rotation angle to axis-aligned zone polygons |
| `config_s2p51.py` | 338 | s2p51 multiplexed config decoder/encoder (DnD, rain protection, LED schedule, etc.) |
| `heartbeat.py` | 86 | s1p1 heartbeat decoder: 20-byte frame → Heartbeat dataclass (battery, state, phase) |
| `m_path.py` | 72 | M_PATH.* regex decoder: `[x,y]` pair list with pen-up sentinel → track segments |
| `mqtt_archive.py` | 108 | Daily-rotating JSONL archive of raw MQTT payloads for novel-field recovery |
| `pcd.py` | 146 | Minimal PCD v0.7 parser for g2408 LiDAR binary blobs (binary unorganised cloud) |
| `pcd_render.py` | 127 | PNG renderer for LiDAR point clouds (orthographic + oblique projection) |
| `pose.py` | 82 | Two s1p4 pose decoder variants (int16 vs packed x24/y24/angle8) for firmware comparison |
| `properties_g2408.py` | 72 | g2408-specific siid/piid map and state-code translations (replaces multi-model upstream registry) |
| `replay.py` | 58 | Probe-log JSONL replay iterator (yields ProbeLogEvent per MQTT properties_changed line) |
| `schedule.py` | 291 | SCHEDULE.* batch decoder: base64-blob slot plans → typed weekday/time/zone records |
| `session_summary.py` | 296 | Session-summary JSON → typed dataclass decoder (areas, obstacles, coordinates in metres) |
| `settings.py` | 117 | SETTINGS.* batch decoder + read-modify-write helper for per-map mowing settings |
| `telemetry.py` | 260 | s1p4 mowing telemetry decoder: 33-byte frame → position, heading, area, battery, phase |
| `unknown_watchdog.py` | 143 | Dedupe novelty detector: first-observation-only flag for unknown MQTT (siid, piid) pairs |
| `wheel_bind.py` | 91 | Wheel-bind detector: cross-frame Δposition vs Δarea cross-check for stalled odometry |

### `live_map/`

| File | LOC | Purpose |
|---|---|---|
| `finalize.py` | 143 | Finalize-gate logic: per-update decision to start/continue/finalize in-progress session |
| `state.py` | 402 | `LiveMapState` dataclass: in-progress session — start time, multi-leg track accumulator |
| `trail.py` | 130 | Trail rendering helpers: LiveMapState legs → drawing primitives for map_render compositor |

### `observability/`

| File | LOC | Purpose |
|---|---|---|
| `__init__.py` | 24 | Re-exports `FreshnessTracker`, `NovelLogBuffer`, `PersistentNovelStore`, `NovelObservationRegistry` |
| `freshness.py` | 42 | Per-field freshness tracker: stamps changed fields with wall-clock time on each state mutation |
| `log_buffer.py` | 35 | Bounded ring buffer of NOVEL log lines for diagnostics dumps (Python logging handler) |
| `novel_store.py` | 183 | Append-only JSONL persistence for novel observations; seeds watchdog across restarts |
| `registry.py` | 187 | Timestamped novel-observation registry: category + wall-clock wrapper over `unknown_watchdog` |
| `schemas.py` | 133 | Schema fingerprints for known JSON blobs; `SchemaCheck.diff_keys` returns unknown dotted paths |

### `inventory/`

| File | LOC | Purpose |
|---|---|---|
| `__init__.py` | 14 | Re-exports `Inventory`, `load_inventory` |
| `loader.py` | 148 | YAML source-of-truth loader: parses inventory.yaml once → frozen `Inventory` with four indexed lookups |

### `archive/`

| File | LOC | Purpose |
|---|---|---|
| `__init__.py` | 9 | Re-exports `ArchivedLidarScan`, `ArchivedSession`, `LidarArchive`, `SessionArchive` |
| `lidar.py` | 333 | On-disk LiDAR PCD archive: content-addressed by md5, per-map subdirs, HA-free |
| `session.py` | 691 | Per-session summary archive: JSON + index.json, content-addressed by md5, HA-free |

## 2. Dependency graph

**Total modules:** 94
**Total internal import edges:** 334

### 2.1 Fan-in top-20 (most-imported modules)

**Method:** each unique (importing_module, imported_module) pair; submodule imports (e.g. `from ..protocol import config_s2p51`) count as one edge to the submodule, not also to the package.

| Module | Importers | Notes |
|---|---|---|
| `const` | 30 | Central constants — expected |
| `mower.state` | 21 | Core domain types (`MowerState`, `ChargingStatus`) — expected |
| `coordinator` | 14 | Coordinator re-export hub — expected (mixin pattern by design; see CLAUDE.md) |
| `_devices` | 13 | Device-info helpers used by all entity platforms — expected |
| `mower.actions` | 13 | `ACTION_TABLE` and `MowerAction` enum referenced by every write path — expected |
| `wifi_archive_store` | 10 | Archive store type used by coordinator + sensor + select — expected |
| `protocol.telemetry` | 10 | Telemetry frame decoder — 9 coordinator submods + `protocol.__init__` re-export |
| `protocol.heartbeat` | 10 | S1P1 heartbeat decoder — 9 coordinator submods + `protocol.__init__` re-export |
| `archive.session` | 10 | `SessionArchive` used across coordinator + entity layers — expected |
| `coordinator._property_apply` | 10 | Module-level pure helpers re-used by all coordinator mixins — expected (coordinator-internal, high fan-in is not a smell here) |
| `protocol.config_s2p51` | 10 | S2P51 settings decoder — 9 coordinator submods + `protocol.__init__` re-export |
| `archive.lidar` | 10 | `LidarArchive` used across coordinator + entity layers — expected |
| `protocol.wheel_bind` | 9 | Wheel-bind stall detector — all coordinator submods import it wholesale |
| `live_map.state` | 9 | `LiveMapState` used by coordinator + rendering + map entities — expected |
| `mqtt_client` | 9 | `DreameMqttClient` transport — coordinator + camera + services — expected |
| `protocol.session_summary` | 9 | Session-summary decoder — all coordinator submods import it wholesale |
| `inventory.loader` | 9 | `load_inventory()` used by all coordinator submods — expected |
| `mower.state_machine` | 9 | `MowerStateMachine` referenced by coordinator write + MQTT paths — expected |
| `live_map.finalize` | 9 | Finalize-decision helpers used by coordinator mixins — expected |
| `observability.schemas` | 9 | Schema constants used by coordinator and sensors — expected |

### 2.2 Import cycles

2 apparent cycles detected by AST scan, **both TYPE_CHECKING-only (annotation-only, no runtime import)**:

- `observability.novel_store` ↔ `observability.registry`: each module imports the other's class solely inside `if TYPE_CHECKING:` for type annotations. No runtime cycle.
- `_devices` → `coordinator.__init__` → `coordinator._device_sync` → `_devices`: `_devices` imports `DreameA2MowerCoordinator` solely inside `if TYPE_CHECKING:` (for the `coord: DreameA2MowerCoordinator` type annotation). At runtime `_devices` only imports `const`. The coordinator → `_device_sync` → `_devices` direction is real but forms no cycle since `_devices` has no runtime back-edge.

**No true runtime cycles.** The codebase is a DAG at runtime.

### 2.3 Orphan modules

Modules with fan-in 0 and not loaded as an HA platform by `PLATFORMS` / HA framework:

| Module | Status | Reason |
|---|---|---|
| `protocol._jsonable` | Test-only utility | Only imported by `tests/protocol/test_entity_jsonable.py`; not used inside the integration at runtime. Intentionally dependency-free. |
| `protocol.mqtt_archive` | Retained-for-reactivation dead code | `coordinator/_core.py` contains an explicit comment explaining it's kept for short debug windows; not imported at runtime. Low priority to remove. |
| `protocol.pose` | Test-only utility | Only imported by `tests/protocol/test_pose.py`. `protocol.telemetry` re-implements pose decoding inline (`_decode_pose`) rather than importing this module. Could be consolidated. |

## 3. Domain-concept ownership

| Concept | Acquired | Stored | Transformed | Rendered |
|---|---|---|---|---|
| cloud_state | `cloud_client.py` (`fetch_full_cloud_state`) | `cloud_state.py` (`CloudState` frozen dataclass) | `coordinator/_cloud_state.py` (`_apply_cloud_state_to_mower_state`) | `sensor.py` (cloud-sourced sensors), `switch.py`, `select.py` (per-map settings) |
| mower_state | `mqtt_client.py` + `coordinator/_mqtt_handlers.py` **(split)** | `mower/state.py` (`MowerState`) | `coordinator/_property_apply.py` (`apply_property_to_state`), `mower/state_machine.py` **(split)** | `lawn_mower.py`, `sensor.py`, `binary_sensor.py` |
| session | `coordinator/_mqtt_handlers.py` (start trigger via `live_map.begin_session`) + `cloud_client.py` (OSS summary fetch) **(split)** | `live_map/state.py` (`LiveMapState`), `archive/session.py` (`SessionArchive`) **(split)** | `coordinator/_session.py` (finalize / restore / replay / work-log) | `sensor.py` (session-summary sensor), `calendar.py` (archived sessions as CalendarEvents) |
| map | `cloud_client.py` (`fetch_map`) | `cloud_state.py` (`CloudState.maps_by_id`) [canonical], `coordinator/_core.py` (`_cached_maps_by_id`) [shadow] **(split)** | `map_decoder.py` (`parse_cloud_maps` → `MapData`), `coordinator/_cloud_state.py` (`_refresh_map`) | `camera.py` (base-map PNG endpoint), `map_render.py` (rendering pipeline) |
| settings | `cloud_client.py` (`fetch_full_cloud_state`, SETTINGS.* batch) | `cloud_state.py` (`CloudState.settings` / `SettingsRoot`) | `protocol/settings.py` (`parse_settings_batch`, `write_setting`), `coordinator/_writes.py` (`write_settings`) **(split)** | `switch.py` (boolean CFG settings), `select.py` (enum CFG settings), `number.py` (numeric settings) |
| schedule | `cloud_client.py` (`fetch_full_cloud_state`, SCHEDULE.* batch) | `cloud_state.py` (`CloudState.schedule` / `ScheduleData`) | `coordinator/_writes.py` (`write_schedule`), `protocol/schedule.py` (decode + encode) **(split)** | `sensor.py` (`schedule_count`), `time.py` (DnD + charging slot display) |
| lidar | `coordinator/_lidar_oss.py` (`_handle_lidar_object_name`, cloud-OSS fetch) | `archive/lidar.py` (`LidarArchive`) | `coordinator/_lidar_oss.py` (parse + archive write via `protocol/pcd.py`) [Acquired+Transformed co-located] | `camera.py` (`LidarTopDownCamera`, `LidarTopDownFullCamera`, `LidarSelectedCamera`) |
| wifi | `coordinator/_wifi_archive.py` (`refresh_wifi_archive`, `_download_and_archive_wifi`) | `wifi_archive_store.py` (`WifiArchiveStore`) | `wifi_match.py` (fingerprint → map_id correlation), `wifi_map_render.py` (OSS JSON → heatmap PNG) | `camera.py` (`WifiHeatmapSelectedCamera`, `WifiHeatmapMapCamera`) |
| observability | `coordinator/_mqtt_handlers.py` + 9 coordinator mixins (novelty detection), `__init__.py` (log buffer + persistent store seed) **(split)** | `observability/registry.py` (`NovelObservationRegistry`), `observability/novel_store.py` (`PersistentNovelStore`) | `observability/freshness.py` (`FreshnessTracker`), `observability/schemas.py` (`SchemaCheck`) | `diagnostics.py` (HA diagnostics dump), `sensor.py` (novel-token count + data-freshness sensors) |

## 4. Cross-cutting smells

### 4.1 Retry / poll / backoff loops

Four retry / poll locations exist in integration source. Three are ad-hoc loops
in `cloud_client.py` with inconsistent shapes; one is the well-bounded
finalize-gate pattern. At four total occurrences this is a borderline case —
not an urgent consolidation target, but worth a shared helper once the cloud
transport layer is refactored (Block 1 remediation target — `cloud_client.py` is Block 1 scope).

| Location | Pattern | Notes |
|---|---|---|
| `cloud_client.py:1387` — `request()` | `while retries < retry_count+1` (default `retry_count=2`, so 3 loop iterations), no inter-attempt sleep | Retries on `requests.Timeout` or any `Exception`; not deadline-protected; runs in a blocking thread (no async cancellation point); `retry_count` flows in from callers with varying defaults (1–4) making the effective attempt count opaque at call sites |
| `cloud_client.py:1219` — `get_file()` | `while retries < retry_count+1` (default 5 attempts), no inter-attempt sleep | Same shape as `request()`; retries on any exception or non-200 HTTP status; unbounded in wall-clock time; no graceful cancellation |
| `cloud_client.py:578` — `send()` action path | `for attempt in range(attempts)` with `attempts = 3 if method == "action" else 1`, fixed `sleep(8)` between non-80001 failures | Action method only (non-action always exits after 1 attempt); 8s sleep is `time.sleep` on the calling thread (blocking); no deadline; 80001 breaks fast deliberately — but the break logic is inlined, not extracted |
| `live_map/finalize.py:32–34` + `coordinator/_session.py:446` + `coordinator/_core.py:506–518` — finalize-gate | Deadline-bounded (MAX\_AGE\_SECONDS=1800, MAX\_ATTEMPTS=10, RETRY\_INTERVAL\_SECONDS=60); pure state-machine decide(); dispatched via `async_track_time_interval` | **Model pattern.** Well-bounded on both wall-clock and attempt count; pure function (`decide()`) separates policy from I/O; graceful cancellation via HA's `async_on_unload` unsubscribes the interval; attempt tracking persisted in `MowerState` so it survives coordinator restarts |

**Consolidation note:** The three `cloud_client.py` loops share the same flaw:
`retry_count` is threaded as a parameter through five call levels
(`set_property` → `set_properties` → `send` → `_api_call` → `request`) with
differing defaults at each level, making the real attempt ceiling invisible at
the top-level callsite. Worse, `send()`'s outer `for attempt in range(attempts)`
is **stacked on top of** `_api_call → request`'s inner retry loop — so an
action call's effective ceiling is `3 × 3 = 9` attempts, not 3, with each
outer attempt costing an 8s sleep plus three inner network attempts. A single
`_cloud_request_with_retry(url, data, max_attempts, delay_s)` helper would
centralize the policy, eliminate the nested loops, and make the finalize-gate
the only place in the codebase that owns retry state. The `sleep(8)` in
`send()` should become `asyncio.sleep` (or moved to the executor wrapper)
once the transport is async.

### 4.2 Scheduling patterns

Block-1 candidate: confirm every interval/timer is cancelled on coordinator shutdown (see "Cancelled?" column). One confirmed leak: `coordinator/_device_sync.py:291` — `loop.call_later` debounce handle is not registered with `async_on_unload`. See smell summary below the table.

**Summary counts**

| API | Count |
|---|---|
| `async_track_time_interval` | 12 |
| `loop.call_later` | 1 |
| `async_call_later` | 1 |
| `loop.call_soon_threadsafe` | 5 |
| `hass.async_create_task` | ~10 (fire-and-forget) |
| `asyncio.create_task` | 1 (observability fallback) |
| `time.sleep` (blocking) | 0 — none found |

All 12 `async_track_time_interval` registrations are in `coordinator/_core.py:_async_update_data`; the other coordinator submodules import the symbol but never call it.

The rows below cover both time-based scheduling (`async_track_time_interval`, `async_call_later`, etc.) and thread-bridging dispatch (`loop.call_soon_threadsafe`). The thread-bridging rows are included for completeness — they are not scheduling primitives but they are control-flow handoffs that audit reviewers expect to see catalogued in this section.

| Location | API | Purpose | Interval | Cancelled? |
|---|---|---|---|---|
| `coordinator/_core.py:385` | `async_track_time_interval` | 2-min cloud-state refresh — picks up settings that are cloud-cache-only and emit no MQTT signal | 120 s | yes — `entry.async_on_unload` |
| `coordinator/_core.py:397` | `async_track_time_interval` | 10-min CFG refresh (blade-life, side-brush-life) | 600 s | yes — `entry.async_on_unload` |
| `coordinator/_core.py:409` | `async_track_time_interval` | 60-s LOCN poll (GPS position) | 60 s | yes — `entry.async_on_unload` |
| `coordinator/_core.py:422` | `async_track_time_interval` | 6-h DEV refresh (hw serial / firmware version) | 6 h | yes — `entry.async_on_unload` |
| `coordinator/_core.py:436` | `async_track_time_interval` | 1-h NET refresh (wifi SSID / IP / RSSI) | 1 h | yes — `entry.async_on_unload` |
| `coordinator/_core.py:449` | `async_track_time_interval` | 60-s DOCK poll (mower-in-dock, dock arrival/departure) | 60 s | yes — `entry.async_on_unload` |
| `coordinator/_core.py:463` | `async_track_time_interval` | 10-min MIHIS refresh (lifetime totals) | 600 s | yes — `entry.async_on_unload` |
| `coordinator/_core.py:475` | `async_track_time_interval` | 6-h MAP refresh (per-map camera PNG at startup) | 6 h | yes — `entry.async_on_unload` |
| `coordinator/_core.py:513` | `async_track_time_interval` | 60-s session-finalize gate (`_periodic_session_retry`) (pattern analysed in § 4.1) | 60 s | yes — `entry.async_on_unload` |
| `coordinator/_core.py:530` | `async_track_time_interval` | 1-h slow-property poll (s6p3 cloud_connected + wifi_rssi) | 1 h | yes — `entry.async_on_unload` |
| `coordinator/_core.py:676` | `async_track_time_interval` | 30-s in-progress trail persist (dirty-flag guarded) | 30 s | yes — `entry.async_on_unload` |
| `coordinator/_core.py:736` | `async_track_time_interval` | 10-s state-machine tick (HB staleness, s2p2=71 disambig, debounced save) | 10 s | yes — `entry.async_on_unload` |
| `coordinator/_device_sync.py:291` | `loop.call_later` | Debounced cloud-state refresh on settings-tripwire (s6p2 etc.); coalesces burst into single fetch after 5 s | one-shot (re-armed each call) | **unclear — verify**: handle stored in `self._cloud_refresh_debounce_handle`; self-cancels on re-arm but is NOT registered with `async_on_unload`; if a tripwire fires just before unload the dangling timer will fire after the coordinator is gone |
| `select.py:1578` | `async_call_later` | 10-s optimistic-clear fallback for `SelectActiveMapId` (reverts to MAPL state if firmware rejects write) | one-shot | no unsubscribe — acceptable; fires once, references only `self._optimistic_target_map_id` (entity lives for integration lifetime) |
| `camera.py:609` | `async_track_state_change_event` | `DreameA2WifiCamera`: watch flip-toggle entities to bust image cache | event-driven | yes — `self.async_on_remove` |
| `camera.py:736` | `async_track_state_change_event` | `DreameA2WifiPerMapCamera`: same flip-toggle cache-bust | event-driven | yes — `self.async_on_remove` |
| `coordinator/_mqtt_handlers.py:223` | `loop.call_soon_threadsafe` + `loop.create_task` | Hop paho-thread event_occured onto event loop; fire-and-forget `_handle_event_occured` | one-shot (per MQTT event) | n/a — no handle to cancel |
| `coordinator/_mqtt_handlers.py:630,647,658,791` | `loop.call_soon_threadsafe` | Hop tripwire / telemetry / MAPL triggers from paho thread to event loop | one-shot (per MQTT message) | n/a — no handle to cancel |
| `observability/registry.py:108` | `asyncio.create_task` | Fallback path for test suite (production path uses `run_coroutine_threadsafe`); fire-and-forget append to PersistentNovelStore | one-shot | n/a — test-only path; no production concern |
| `select.py:774`, `__init__.py:78`, `coordinator/*:multiple` | `hass.async_create_task` | Fire-and-forget render / refresh kicks (map re-render on MAPL, live-trail re-render on position push, lidar fetch, etc.) | one-shot | n/a — short-lived coroutines; no long-running loop |

**Smell summary**

- `coordinator/_device_sync.py:291` — `loop.call_later` debounce handle (`_cloud_refresh_debounce_handle`) is stored on `self` and self-cancels on re-arm, but is **never registered with `async_on_unload`**. If a settings tripwire fires in the 5 s window before config-entry unload, the handle fires into a torn-down coordinator. Low probability in practice but it is a genuine leak class. Fix: add `self.entry.async_on_unload(lambda: self._cloud_refresh_debounce_handle and self._cloud_refresh_debounce_handle.cancel())` at registration time in `_init_cloud` or `_async_update_data`.

### 4.3 Error handling patterns

| Pattern | Count | Locations / Notes |
|---|---|---|
| Bare `except:` (no type) | 0 | — none found; clean |
| `except Exception` total | 127 | Spread across 21 files; `cloud_client.py` (33), `coordinator/_session.py` (10), `coordinator/_recorder_merge.py` (10), `services.py` (9), `mqtt_client.py` (8), `coordinator/_core.py` (8) |
| `except Exception` silent-swallow (no log, no re-raise) | 29 | `cloud_client.py` (13 — all in the large parse-batch block `cloud_client.py:1835–1960`), `services.py` (4), `camera.py` (2 — return None on render failure), `sensor.py` (2 — manifest version load + shadow read), `coordinator/_wifi_archive.py` (2), `switch.py:1276`, `select.py:1763`, `sensor.py:1002`, `number.py:673`, `wifi_map_render.py:98`, `coordinator/_session.py:185`, `protocol/unknown_watchdog.py:94` |
| `except Exception` log-and-swallow (log but no re-raise) | 98 | Dominant pattern throughout the codebase; deliberately defensive in background async loops — appropriate in most cases but obscures unexpected failures |
| `except Exception` with re-raise | 0 | No `except Exception … raise` pattern found anywhere; all caught exceptions are terminal at the catch site |
| Custom exception types defined | 6 | `protocol/session_summary.py:128` `InvalidSessionSummary(ValueError)`, `protocol/telemetry.py:15` `InvalidS1P4Frame(ValueError)`, `protocol/pcd.py:29` `PCDHeaderError(ValueError)`, `protocol/heartbeat.py:42` `InvalidS1P1Frame(ValueError)`, `protocol/cfg_action.py:24` `CfgActionError(RuntimeError)`, `protocol/config_s2p51.py:19` `S2P51DecodeError(ValueError)` |
| Custom exception naming consistency | Mixed | Five exceptions use `Error`/`Exception` suffix inherited from stdlib bases (`ValueError`, `RuntimeError`); naming convention is consistent within `protocol/`; none are raised-and-caught across module boundaries — all are decoder-local |
| `_LOGGER.error` / `_LOGGER.exception` total | 36 | `coordinator/_recorder_merge.py` (10), `coordinator/_mqtt_handlers.py` (6), `coordinator/_core.py` (5), `coordinator/_session.py` (3), `observability/novel_store.py` (2), `coordinator/_refreshers.py` (2), `cloud_client.py` (2), others ≤ 1 each |
| `BaseException` catches | 0 | — none found |

**Notes on the silent-swallow cluster in `cloud_client.py:1835–1960`:** this block parses
multiple optional sub-fields from a cloud batch response (settings, schedule, zone list,
etc.). Each parse step is individually wrapped; a failure in one field allows others to
proceed. The pattern is intentional fault-isolation, not sloppiness — but the total absence
of logging means parse regressions are invisible. Recommend adding at least `_LOGGER.debug`
on each catch.

**Block disposition:**

- Bare-except count is 0 — no bare-except found; clean.
- Silent-swallow count (29) is the primary concern. Most occur where a `None`-or-default
  fallback is acceptable (render functions, shadow reads, manifest load), but 13 in
  `cloud_client.py` parse-batch and 4 in `services.py` produce invisible failures.
  Target for **Block 1 cleanup**: add `_LOGGER.debug` at minimum to silent swallows in
  `cloud_client.py:1835–1960` and `services.py:427/489/495/504`.
- Re-raise count is 0 — the codebase is uniformly "catch-and-continue". This is
  appropriate for background loops but means callers of `services.py` action handlers
  never see propagated exceptions; `ServiceValidationError` (raised at
  `services.py:626/639`) is the only structured caller-visible error. Flag for **Block 1**:
  verify service handlers either propagate `ServiceValidationError` or log at `error` level
  so failures reach the user.
- Custom exception types are confined to `protocol/` and are consistently `ValueError` /
  `RuntimeError` subclasses. No naming inconsistency to fix; no cross-module catch sites
  found, so these are decoder-local sentinels only. Low priority.

### 4.4 Large files & long functions

#### Files >800 LOC (refactor candidates)

| File | LOC | Block | Notes |
|---|---|---|---|
| `cloud_client.py` | 2197 | B1 | auth + RPC + blob + discovery + parse-batch all co-located — split into `_cloud_auth.py`, `_cloud_rpc.py`, `_cloud_oss.py` |
| `select.py` | 1990 | B3 | one class per CFG setting, each ~30 LOC; split by domain group (efficiency / blade-height / rain+DnD / anti-theft / cutter) into `select_map_settings.py` + `select_global.py` |
| `sensor.py` | 1499 | B3 | device-wide sensors + per-map sensors + session-summary sensors interleaved — split by scope into `sensor_device.py`, `sensor_map.py`, `sensor_session.py` |
| `switch.py` | 1308 | B3 | 40+ boolean CFG settings each ~25 LOC — split by domain group (DnD / rain / child-lock / anti-theft / cutter / per-map) mirroring `select.py` split plan |
| `map_render.py` | 1283 | B4 | monolithic PNG compositor — extract per-layer renderers: `_render_zones.py`, `_render_trail.py`, `_render_obstacles.py`; `render_base_map` (439 LOC) is itself the top-split target |
| `coordinator/_session.py` | 925 | B1 | restore + persist + finalize + replay + work-log render co-located — split finalize into `_finalize.py` and work-log into `_work_log.py` |
| `coordinator/_core.py` | 828 | B1 | `__init__` (202 LOC) + `_async_update_data` (408 LOC) + `_init_cloud` + `_init_mqtt` — extract interval-registration table into `_intervals.py`; `_async_update_data` itself is top B1 refactor target |
| `coordinator/_mqtt_handlers.py` | 810 | B1 | MQTT dispatch + state glue + event fire — `_on_state_update` (298 LOC) is a siid:piid if/elif chain; extract per-siid sub-handlers |
| `coordinator/_refreshers.py` | 802 | B1 | `_refresh_cfg` (384 LOC) is a CFG key dispatch block — extract per-key apply functions or use `(key)→callable` table |
| `camera.py` | 962 | B4 | 7 camera subclasses + aiohttp view registration in one file — split into `camera_base.py`, `camera_lidar.py`, `camera_wifi.py`; aiohttp view wiring into `_camera_views.py` |

#### Functions >80 LOC

| File | Line | Function | LOC | Block | Notes |
|---|---|---|---|---|---|
| `map_decoder.py` | 278 | `parse_cloud_map` | 439 | B2 | long if/elif chain per map-object type; extract per-object-type parsers into helpers |
| `coordinator/_core.py` | 336 | `_async_update_data` | 408 | B1 | interval registration + startup sequencing; extract interval table + split startup phases |
| `map_render.py` | 179 | `render_base_map` | 391 | B4 | per-layer draw sequence; extract per-layer render steps |
| `coordinator/_refreshers.py` | 109 | `_refresh_cfg` | 384 | B1 | CFG key if/elif dispatch; use `(key)→apply_fn` table |
| `coordinator/_session.py` | 99 | `render_work_log_session` | 333 | B1 | section-by-section work-log builder; extract section helpers |
| `map_render.py` | 922 | `render_with_trail` | 325 | B4 | composite render + trail overlay; split trail step into helper |
| `coordinator/_mqtt_handlers.py` | 229 | `_on_state_update` | 298 | B1 | siid:piid if/elif dispatch; extract per-siid sub-dispatch or use `(siid,piid)→callable` table |
| `session_card.py` | 360 | `build_picked_session_summary` | 286 | B4 | flat attribute builder; split by attribute group (timing / area / path / obstacles) |
| `coordinator/_lidar_oss.py` | 365 | `_do_oss_fetch` | 256 | B1 | fetch + parse + archive in one function; split parse + archive steps |
| `cloud_client.py` | 805 | `fetch_wifi_map` | 248 | B1 | OSS fetch + parse + cache in one function; split into fetch + parse helpers |
| `__init__.py` | 43 | `async_setup_entry` | 221 | B1 | platform forward + service register + coordinator init sequencing; extract service-register and platform-forward steps |
| `cloud_client.py` | 1757 | `fetch_full_cloud_state` | 219 | B1 | batch-response dispatch; extract per-batch-key parsers |
| `coordinator/_core.py` | 91 | `__init__` | 202 | B1 | attribute init for all mixins; refactor into `_reset_state()` helper called from `__init__` |
| `coordinator/_mqtt_handlers.py` | 605 | `handle_property_push` | 187 | B1 | MQTT property routing; extract per-topic handlers |
| `coordinator/_session.py` | 579 | `_run_finalize_incomplete` | 163 | B1 | finalize gate + cloud-fetch + archive; split cloud-fetch from finalize decision |
| `cloud_client.py` | 1054 | `list_wifi_candidates` | 156 | B1 | pagination + filter + ranking in one function; split pagination from ranking |
| `coordinator/_writes.py` | 352 | `dispatch_action` | 133 | B1 | action-type if/elif dispatch; use `MowerAction→handler` table |
| `protocol/config_s2p51.py` | 127 | `_decode_list_payload` | 129 | B2 | field-index if/elif decode; use index→field table |
| `coordinator/_session.py` | 743 | `_restore_in_progress` | 123 | B1 | restore + reconcile + state-machine seed; extract reconcile step |
| `mower/state_machine.py` | 359 | `reconcile_from_telemetry` | 121 | B2 | phase/state if/elif table; use `(phase,state)→transition_fn` |
| `coordinator/_property_apply.py` | 341 | `_apply_s2p51_settings` | 115 | B1 | s2p51 field if/elif dispatch; extract per-field apply or use field→callable table |
| `coordinator/_wifi_archive.py` | 140 | `_tag_wifi_archive_map_ids` | 106 | B1 | per-archive-entry match loop; split match step into helper |
| `coordinator/_cloud_state.py` | 265 | `_refresh_map` | 101 | B1 | map fetch + decode + sub-device sync; split decode + sync steps |
| `cloud_client.py` | 2012 | `set_cfg` | 101 | B1 | CFG named-key if/elif dispatch + RPC; use `(key)→payload_fn` table |
| `archive/session.py` | 463 | `archive` | 101 | B2 | archive write + index update + dedup; split index-update step |
| `coordinator/_property_apply.py` | 500 | `apply_property_to_state` | 98 | B1 | `(siid,piid)→callable` dispatch; already a dispatch table — top-level else branches could be trimmed |
| `live_map/finalize.py` | 48 | `decide` | 96 | B4 | finalize-gate state machine; well-bounded but dense — inline comments sufficient (`live_map/` is in B4 scope per overview spec, though `decide()` itself is pure domain logic) |
| `_render_stripes.py` | 33 | `compute_stripe_overlay` | 95 | B4 | geometry + sampling in one pass; split bounding-box step from sampling |
| `protocol/session_summary.py` | 205 | `parse_session_summary` | 92 | B2 | field-by-field JSON parse; acceptable length for a flat decoder |
| `map_render.py` | 622 | `render_main_view` | 92 | B4 | per-layer composite; extract per-layer draw calls |
| `select.py` | 1489 | `async_select_option` | 90 | B3 | multi-branch option dispatch; extract per-setting apply helpers |
| `coordinator/_refreshers.py` | 713 | `_poll_slow_properties` | 89 | B1 | per-property poll sequence; acceptable length; low priority |
| `protocol/pcd_render.py` | 33 | `render_top_down` | 88 | B4 | point-cloud projection + draw; split projection from draw |
| `cloud_client.py` | 1668 | `fetch_map` | 88 | B1 | OSS signed-URL fetch + parse; split parse step |
| `coordinator/_lidar_oss.py` | 278 | `_handle_lidar_object_name` | 86 | B1 | object-name routing + fetch dispatch; acceptable; low priority |
| `services.py` | 435 | `_async_handle_discover_cloud_api` | 82 | B3 | cloud-probe + result-format in one function; split probe from format |
| `protocol/config_s2p51.py` | 258 | `encode_s2p51` | 81 | B2 | field-by-field encode; acceptable length for a flat encoder |

**Total functions >80 LOC: 37** — all presented above in descending LOC order.

### 4.5 Other cross-cutting smells

| Smell | Locations | Blocks affected |
|---|---|---|
| `_cached_maps_by_id` shadow of `CloudState.maps_by_id` still read by entity platforms | `coordinator/_core.py:192` (definition); `select.py` (22 reads), `switch.py` (7), `sensor.py` (3), `camera.py` (8) | B1, B3, B4 |
| Schedule decoder (`parse_schedule_batch`) called inside `cloud_client.fetch_full_cloud_state` — acquisition and decode layered in transport module | `cloud_client.py:1881`, `protocol/schedule.py:250` | B1, B2 |
| `coordinator/_lidar_oss.py` owns both OSS fetch (Acquired) and parse+archive-write (Transformed) for the lidar concept | `coordinator/_lidar_oss.py:278` (`_handle_lidar_object_name`), `coordinator/_lidar_oss.py:365` (`_do_oss_fetch`) | B1, B2 |
| PNG serialisation idiom (`BytesIO(); img.save(buf, format="PNG"); buf.getvalue()`) duplicated 6+ times with no shared helper | `map_render.py:559–561`, `map_render.py:817–819`, `map_render.py:853–855`, `map_render.py:1093–1094`, `map_render.py:1235–1237`, `wifi_map_render.py:116–118`, `protocol/pcd_render.py:118–120`, `protocol/pcd_render.py:125–127` | B2, B4 |
| `mower_state` Transformed split between `coordinator/_property_apply.py` (B1) and `mower/state_machine.py` (B2) | `coordinator/_property_apply.py`, `mower/state_machine.py` | B1, B2 |
| `session` Stored split between `live_map/state.py` (B1) and `archive/session.py` (B2) | `live_map/state.py`, `archive/session.py` | B1, B2 |
| `settings` Transformed split between `coordinator/_writes.py` (B1) and `protocol/settings.py` (B2) | `coordinator/_writes.py`, `protocol/settings.py` | B1, B2 |

## 5. Later-block backlog

Items spotted during meta pass that belong to a specific later block.
Each entry: `[Bx] short label — one-line description`.

- [B1] `cloud_client.py` file split — auth + RPC + blob + parse-batch co-located; split into `_cloud_auth.py`, `_cloud_rpc.py`, `_cloud_oss.py`; see § 4.4
- [B1] `coordinator/_session.py` split — restore + persist + finalize + replay + work-log render co-located; split finalize into `_finalize.py` and work-log into `_work_log.py`; see § 4.4
- [B1] `coordinator/_core.py` split — `_async_update_data` (408 LOC) + `__init__` (202 LOC); extract interval-registration table into `_intervals.py`; see § 4.4
- [B1] `coordinator/_mqtt_handlers.py` split — `_on_state_update` (298 LOC) siid:piid if/elif chain; extract per-siid sub-handlers; see § 4.4
- [B1] `coordinator/_refreshers.py` split — `_refresh_cfg` (384 LOC) CFG key dispatch; extract per-key apply functions; see § 4.4
- [B1] `_cached_maps_by_id` removal — CloudState architecture note (cloud_state.py docstring) says it replaces `_cached_*`; `_cached_maps_by_id` at `coordinator/_core.py:192` survived; expose `coordinator.maps_by_id` property proxying `CloudState.maps_by_id` and remove the shadow; downstream B3/B4 entity reads update accordingly
- [B1] `_cloud_refresh_debounce_handle` leak — `coordinator/_device_sync.py:291` `loop.call_later` handle not registered with `async_on_unload`; fix from § 4.2 smell summary
- [B1] `services.py` silent-swallow cluster — 4 silent `except Exception` at lines 427/489/495/504; add `_LOGGER.debug` at minimum; see § 4.3
- [B1] `cloud_client.py` silent-swallow cluster — 13 silent `except Exception` in parse-batch block `cloud_client.py:1835–1960`; add `_LOGGER.debug`; see § 4.3
- [B1] Coordinator mixin import boilerplate — consolidate the duplicated protocol-import block (5 lines: `config_s2p51`, `heartbeat`, `telemetry`, `session_summary`, `wheel_bind`) and observability-import line (`FreshnessTracker`, `NovelObservationRegistry`) into one shared mixin base or expose via `coordinator/__init__.py`. Note: `wheel_bind` is used by only 1 of 9 mixins (`_property_apply.py`) and `config_s2p51` by only 2 (`_property_apply.py`, `_refreshers.py`) — most mixins carry unused imports.
- [B1] `coordinator/_lidar_oss.py` split — extract parse + archive-write logic into a separate `coordinator/_lidar_archive.py` (or `archive/lidar_writer.py`), leaving `_lidar_oss.py` as the pure OSS-fetch path. See § 3 lidar row and § 4.5.
- [B2] `map_decoder.py` function split — `parse_cloud_map` (439 LOC) long if/elif per map-object type; extract per-object-type parsers; see § 4.4
- [B2] `protocol/config_s2p51.py` — `_decode_list_payload` (129 LOC) field-index if/elif; convert to index→field table; see § 4.4
- [B2] `archive/session.py` — `archive()` (101 LOC) archive write + index update + dedup; split index-update step; see § 4.4
- [B2] `protocol.pose` orphan — only used in `tests/protocol/test_pose.py`; `protocol/telemetry.py` re-implements `_decode_pose` inline; consolidate or document divergence; see § 2.3
- [B2] Protocol naming convention — `decode_*` is used for binary-frame entry points (`decode_s1p1`, `decode_s1p4`, `decode_s2p51`); `parse_*` for JSON/batch (`parse_session_summary`, `parse_schedule_batch`, `parse_settings_batch`). `parse_pcd` breaks the pattern (it's binary). Pick one convention or split into two clear groups and rename outliers.
- [B2] `protocol/schedule.py` encode/decode co-location — `parse_schedule_batch` (decode) and `encode_schedule_slot` (encode) live in the same module; the write path in `coordinator/_writes.py` calls both; splitting into `schedule_decode.py` / `schedule_encode.py` would clarify read vs write responsibilities. See § 3 schedule row and § 4.5.
- [B2] `mower/state_machine.py` — `reconcile_from_telemetry` (121 LOC) phase/state if/elif table; convert to `(phase, state)→transition_fn` dispatch; see § 4.4
- [B3] `select.py` split — 1990 LOC; split by domain group into `select_map_settings.py` + `select_global.py`; see § 4.4
- [B3] `sensor.py` split — 1499 LOC; split by scope into `sensor_device.py`, `sensor_map.py`, `sensor_session.py`; see § 4.4
- [B3] `switch.py` split — 1308 LOC; split by domain group mirroring select.py plan; see § 4.4
- [B3] entity orphans from past renames — past unique_id changes (per-map sub-device split, double-prefix fix) left unavailable entities in HA registry; audit via WS `config/entity_registry/list` and remove stale entries
- [B4] `camera.py` split — 962 LOC; split into `camera_base.py`, `camera_lidar.py`, `camera_wifi.py`, `_camera_views.py`; see § 4.4
- [B4] `map_render.py` split — 1283 LOC; extract per-layer renderers; `render_base_map` (391 LOC) is top target; see § 4.4
- [B4] `session_card.py` — `build_picked_session_summary` (286 LOC) flat attribute builder; split by attribute group; see § 4.4
- [B4] PNG serialisation helper — extract `_image_to_png(img: Image.Image) -> bytes` shared helper to eliminate 6+ duplicates across `map_render.py`, `wifi_map_render.py`, `protocol/pcd_render.py`; see § 4.5
- [B4] README version drift — README still says "v1.0.0a — release candidate" and phase table tops out at `v1.0.0a*`; manifest is at `v1.0.17a5`
