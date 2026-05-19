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

(populated by Task 4)

## 4. Cross-cutting smells

### 4.1 Retry / poll / backoff loops
(populated by Task 5)

### 4.2 Scheduling patterns
(populated by Task 6)

### 4.3 Error handling patterns
(populated by Task 7)

### 4.4 Large files & long functions
(populated by Task 8)

### 4.5 Other cross-cutting smells
(populated by Task 9)

## 5. Later-block backlog

Items spotted during meta pass that belong to a specific later block.
Each entry: `[Bx] short label — one-line description`.

(populated incrementally; empty at start)
