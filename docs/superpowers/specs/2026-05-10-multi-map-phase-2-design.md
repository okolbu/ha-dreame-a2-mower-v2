# Multi-Map Phase 2: Full UX Reshape

**Status:** draft 2026-05-10
**Predecessor:** [2026-05-07-multi-map-design.md](2026-05-07-multi-map-design.md) (Phase 1, shipped)
**Scope:** restructure entities into mower + per-map sub-devices, fill in
the LiDAR / WiFi / live-video / settings gaps that Phase 1 left flat,
switch unique_ids to SN-based with one-time migration, expose Custom
Mode via a service-call API. Still dev-only deployment; no production
migrations.

## Why

Phase 1 made the integration *aware* of multiple maps (it fetches all N,
caches by `map_id`, has `_active_map_id` / `_render_map_id`, and exposes
`select.active_map`). What Phase 1 *didn't* do is restructure the entity
surface around that awareness. Today every per-map setting, sensor, and
camera is still on the single mower device, and most of them silently
"flip" when active-map changes — meaning HA history is incoherent
(yesterday's value was for Map 1, today's is for Map 2, same entity).
The new LiDAR and WiFi-heatmap work is single-map only because there's
no obvious place to put per-map variants in the current flat layout.

The user has 2 maps live. The Dreame app silently flips per-map context
across all UI; HA should NOT mimic that. HA wants stable per-entity
semantics so automations and history graphs survive map switches.

## Goal

Every entity has a stable single semantic. A "Map 1 LiDAR top-down
camera" entity always shows Map 1, never silently flips. The user picks
the active map via `select.active_map` (the only "global pointer" left)
and dashboards / automations target the specific map sub-device they
care about.

## Non-goals

- Production migration. Dev-only assumption stands; we'll wipe-and-
  rebuild as needed.
- Multi-mower-per-account first-class support. The architecture below
  doesn't preclude it (SN-keying, sub-devices) but the user has one
  mower, can't test N, and it's deferred.
- App-only items: Change PIN (LCD lock — see correction below; this
  one IS in scope), Support, Send Feedback, Legal, Device Sharing.
  The latter four stay app-only; PIN is mower-level.
- Reshaping the cloud fetch layer; Phase 1 already produces the right
  data shape (`_cached_maps_by_id`, `mow_paths_by_map_id`, etc.).

## Architecture

### Device hierarchy

Every entity lives on one of two device kinds:

```
Config Entry (one per mower account binding)
└── Device: Mower (top-level)
    identifiers={(DOMAIN, sn)}
    connections={(CONNECTION_NETWORK_MAC, mac)}
    │
    ├── Device: Map 0 (sub-device)
    │   identifiers={(DOMAIN, f"{sn}_map_0")}
    │   via_device=(DOMAIN, sn)
    │
    ├── Device: Map 1 (sub-device)
    │   identifiers={(DOMAIN, f"{sn}_map_1")}
    │   via_device=(DOMAIN, sn)
    │
    └── … per-map device for each id in _cached_maps_by_id
```

Map sub-devices are added/removed by the coordinator as
`_cached_maps_by_id` changes. Adding is via `device_registry.async_get_or_create`;
removing requires explicit `device_registry.async_remove_device` since
HA doesn't garbage-collect devices that have no entities. Implementation
note: deletion runs on coordinator data update when a previously-cached
map_id is no longer present.

### Stable keying via SN

Phase 1 keyed everything off `entry.entry_id`. That breaks entity
history on integration remove-and-re-add and is account-scoped (`did`
is the user's Dreame account number, not the mower). Phase 2 switches
to **SN-based keying**:

- `cloud_client._handle_device_info` captures `self._sn = info.get("sn")`
  alongside the existing did/mac/model. SN is hardware-unique
  (e.g. `G2408053AEE0006232`) and surfaces in nearly every cloud and
  MQTT response, so non-null is safe to assume; we still log+warn if
  missing and fall back to `mac` then `entry_id`.
- Mower device identifiers: `{(DOMAIN, sn)}`.
- Map sub-device identifiers: `{(DOMAIN, f"{sn}_map_{map_id}")}`.
- Mower-level entity unique_ids: `f"{sn}_{key}"`.
- Map-level entity unique_ids: `f"{sn}_map_{map_id}_{key}"`.

**Migration.** `async_migrate_entry` walks the existing entity registry
for entries on this config entry, rewrites unique_ids from the old
`{entry_id}_{key}` pattern to `{sn}_{key}` (or `{sn}_map_{N}_{key}` for
the entities that move to sub-devices). Entities lacking a clean
mapping (orphans from prior renames, see the
`feedback_entity_rename_orphan` memory) are left as-is and surfaced via
a one-shot `persistent_notification` listing them so the user can
remove them manually via WS `config/entity_registry/remove`.

The migration runs once at integration setup if `entry.version < 2`;
on success the entry is bumped to `version=2`.

## Entity placement

The split below reflects where entities live AFTER Phase 2. Items
marked **(move)** exist today on the mower device and shift to the map
sub-device. **(new)** items don't exist yet. Everything else is either
already mower-level and stays, or is a Phase 2 addition at mower level.

### Map sub-device (one per map)

| Surface | Entities | Status |
|---|---|---|
| Cameras | static map snapshot, live map (during session), live trail, **live video stream**, **LiDAR top-down**, **WiFi heatmap**, mow-path snapshot | snapshot exists; LiDAR/WiFi (move); live video (new) |
| Selects | zone, spot, edge, **mowing type** (all-area / edger / zone / spot / manual) | first three (move); mowing-type (new) |
| Schedule | schedule entity + per-day slot inspection | (move) |
| General Mode settings | Mowing Efficiency, Mowing Height, Mowing Direction (+sub), Automatic Edge Mowing, Safe Edge Mowing, EdgeMaster, Obstacle Avoidance on Edges, LiDAR Obstacle Recognition, Obstacle Avoidance Height, AI Obstacle Recognition (umbrella + 3 bit-switches), Obstacle Avoidance Distance | most exist as mower-level "active-map followers" (move); a few new |
| Per-map Functions | Pathway Obstacle Avoidance, Ignore Obstacle Zones (sensor + service), Maintenance Points (sensor + select to choose target point) | new |
| Custom Mode | one diagnostic sensor `sensor.{map}_custom_mode_overrides`; writes via service calls (see below) | new |
| AI/Human zones | per-map state sensor | (move) |
| Map metadata | name, **area (m²)**, segment count, settings version (entry 0 vs entry 1) | new sensors |
| Per-map sessions | last session timestamp, area mowed last session, weekly area trend | new |

### Mower device

| Surface | Entities | Status |
|---|---|---|
| Core state | `lawn_mower` entity (state machine), battery, error code, signal strength | exists |
| Action buttons | Start, Stop, Pause, Return to Dock, Find My Robot, Head to Maintenance Point | mostly exist; Find My Robot (new); Head to Maintenance acts on active map's selected point |
| Map picker | `select.active_map` | exists (Phase 1) |
| Location/dock | LOCN, DOCK, MIHIS, MISTA-derived sensors | exists |
| Cross-map history | session archive sensor (Work Logs in app) | exists conceptually |
| [Functions] settings | Rain Protection (+sub), Frost Protection, Do Not Disturb, Low-speed at Nighttime, Navigation Path, Charging, Start from Stop Point (+sub), Auto Recharge After Extended Standby, Capture Photos of AI-Detected Obstacles (exists as `switch.ai_obstacle_photos`), Light | most new |
| [Security] settings | Anti-theft Alarm (+sub), Human Presence Detection Alert (+sub), Child Lock, **Change PIN Code** (LCD-display unlock PIN) | all new |
| [General] settings | Time Zone, Switch Unit, Robot Voice (exists as voice + LCD language selects), Notifications | most new |
| Diagnostics | firmware version, MAC, SN, online status, MQTT-connected, signal | most exist |

### App-only (no HA entity)

`Support`, `Send Feedback`, `Legal Information`, `Device Sharing`. Each
is informational or out-of-scope; the user can still access them in the
Dreame app.

## Custom Mode (per-zone setting overrides)

The app's "Mowing settings" page has a Custom Mode tab where every
General Mode setting can be overridden per zone. With ~10 zones and
11 settings on each of 2 maps, exposing each as an HA entity yields
~220 churning entities. We don't.

### Read surface

One diagnostic-category sensor per map:
`sensor.{map}_custom_mode_overrides`. State is the count of zones with
any override; `extra_state_attributes` carries the full structure:

```yaml
state: 3
attributes:
  zones:
    "1":
      mowing_efficiency: high
      obstacle_avoidance_distance: 0.5
    "5":
      mowing_height: 30
    "7":
      automatic_edge_mowing: false
```

Refreshed on every `_refresh_settings` tick (existing).

### Write surface

Two services on the integration's domain:

```yaml
dreame_a2_mower.set_zone_setting:
  description: Set a Custom Mode override on one zone of one map.
  fields:
    map_id: int      # required
    zone_id: int     # required
    key: string      # required, one of the General Mode setting keys
    value: any       # required, type depends on the key

dreame_a2_mower.clear_zone_setting:
  description: Remove a Custom Mode override (revert that zone+key to General).
  fields:
    map_id: int
    zone_id: int
    key: string
```

Both services validate map_id ∈ `_cached_maps_by_id`, zone_id ∈ that
map's segments, and key ∈ the General Mode keyset. Writes go through
the existing optimistic-write pipeline (`_settings_writes.py`).

The Mower dashboard later renders Custom Mode as a tabbed panel that
calls these services — same UX as the app, no entity-registry pollution.

## LiDAR per-map

Phase 1 left LiDAR as a single-archive single-camera surface. The app
shows different point clouds for Map 1 vs Map 2, so the archive needs
per-map separation.

### Archive layout

```
<config>/dreame_a2_mower/lidar/
├── 0/                  # map_id 0
│   ├── index.json
│   └── *.pcd
├── 1/                  # map_id 1
│   ├── index.json
│   └── *.pcd
└── … per map_id
```

`LidarArchive` gains a `map_id: int` constructor arg; coordinator holds
`lidar_archives_by_map_id: dict[int, LidarArchive]` and routes incoming
LiDAR pushes to the right one.

### Routing the push

The MQTT s99p20 LiDAR-push event currently doesn't carry an explicit
`map_id`, but the mower can only push for the map it's actively on, so
`map_id = self._active_map_id` at push receipt time is correct. If
`_active_map_id` is `None` at receipt (rare), the push is buffered and
reattempted after the next `MAPL` poll resolves. **Open question:**
verify by triggering a LiDAR push from each map in turn and checking
the file lands in the right subdir.

### Camera entities

`DreameA2LidarTopDownCamera` becomes one-per-map, registered to the
map sub-device. Unique_id: `f"{sn}_map_{map_id}_lidar_top_down"`. The
`/api/dreame_a2_mower/lidar/latest.pcd` HTTP view changes to
`/api/dreame_a2_mower/lidar/{map_id}/latest.pcd` so the WebGL card can
fetch the right map's PCD blob.

### Migration

Existing flat `lidar/index.json` + `*.pcd` move to `lidar/0/` on first
startup of v2; if multiple maps existed during the flat-archive period
the user accepts that those scans are "best guess Map 0." A one-shot
`persistent_notification` flags this with the file count moved.

## WiFi heatmap per-map

Same shape as LiDAR.

`fetch_wifi_map(map_id: int)` (was no-arg) downloads from OSS using
the cloud-supplied per-map URL. Cache key is now `(map_id, sha)`.
Camera entity `DreameA2WifiMapCamera` becomes one-per-map; unique_id
`f"{sn}_map_{map_id}_wifi_map"`. The "refresh wifi map" button (`button.wifi_map_refresh`)
becomes per-map too.

The cloud response carries one heatmap per map (verified in the
Apr-19 device-info dump — `heatmap` field is per-map). No new wire
investigation needed beyond plumbing the `map_id` through.

## Live video per-map

The mower exposes a live video stream when actively running. Stream is
intrinsically per-map (you can only stream when the mower is on that
map; only the active map streams at any time). Per-map camera entity
`DreameA2LiveVideoCamera`; unique_id `f"{sn}_map_{map_id}_live_video"`.

Inactive maps' live-video entity reports `unavailable`. Active map's
entity is `idle` when mower is docked, `streaming` when mowing.

Stream URL is fetched per-session via the existing cloud client method
(see `dreame_cloud_dumps/` for the camera-stream-info call shape).
**Open question:** confirm the stream URL is map-scoped or session-
scoped — if session-scoped, all per-map entities share one URL but
only one is active at a time; that's fine.

## Newly per-map: maintenance points, pathway, ignore zones

These three are the per-map items from the "more generic" settings page.

- **Maintenance Points**: each map has 0..N saved points (placed on
  the map by the user). Surface as a `select` entity per map listing
  the named points, plus a `button.head_to_maintenance_point` at
  mower level that targets `select.{active_map}_maintenance_point`'s
  current value. Cloud field name TBD — see Open questions.
- **Pathway Obstacle Avoidance**: per-map switch + sub-numbers
  (sensitivity / threshold). Lives on map sub-device.
- **Ignore Obstacle Zones**: per-map list of rectangles. Read surface:
  one sensor per map with rectangles in `extra_state_attributes`.
  Write surface: services
  `dreame_a2_mower.add_ignore_zone(map_id, x1, y1, x2, y2)` and
  `dreame_a2_mower.remove_ignore_zone(map_id, zone_index)`.

## Tests

### New

- `tests/integration/test_device_hierarchy.py` — config entry setup
  produces 1 mower device + N map sub-devices, each with correct
  identifiers and `via_device`.
- `tests/integration/test_sn_unique_id_migration.py` — entry version 1
  with old `{entry_id}_*` unique_ids gets rewritten to `{sn}_*`; entry
  version bumped to 2; orphan entries surfaced via persistent_notification.
- `tests/integration/test_lidar_per_map_routing.py` — LiDAR push
  while `_active_map_id=0` lands in `lidar/0/`; while `=1`, lands in
  `lidar/1/`. Buffered push when `_active_map_id is None` lands after
  next MAPL.
- `tests/integration/test_custom_mode_services.py` — `set_zone_setting`
  / `clear_zone_setting` validate args, route through `_settings_writes`,
  and refresh the diagnostic sensor.
- `tests/integration/test_per_map_entity_count.py` — 2 maps in
  `_cached_maps_by_id` produces 2 of each per-map entity; reducing to
  1 map removes the orphaned set.

### Modified

- Existing entity-platform tests (`tests/integration/test_*.py`) update
  to assert SN-based unique_ids and per-map device assignment.
- `tests/protocol/test_settings.py` — General vs Custom Mode parsing
  in `SettingsRoot.by_map_id_canonical`.

### Skipped (followups)

- Live video stream end-to-end (depends on a live mowing session;
  manual verify).
- Maintenance points wire format (TBD).

## Out of scope (filed as TODOs)

- **Multi-mower full support**: architecture allows it (SN-keyed
  identifiers don't collide across mowers in the same HA instance);
  not tested. README note: "Tested with one mower; multi-mower
  partially supported, untested."
- **Sub-sub-devices for zones**: option (A) was rejected in favor of
  service-call API. If a future need arises (e.g. dashboard wants
  per-zone history), revisit then.
- **Migration code for production users**: still dev-only; v2 is a
  hard cut. If/when the integration goes production, write a proper
  migration in a Phase 3 doc.
- **Mower dashboard reshape** to mimic the app's two-page settings
  structure (Mowing settings per-map / Generic settings global). The
  user has flagged this for later — once the entities exist, the
  dashboard yaml regenerates around them.

## Open questions to resolve during implementation

1. **SN presence in fresh probes** — verified in cloud dumps, but
   confirm `info["sn"]` is populated on first call after login (not
   only after a later getDeviceData). If absent at first call, the
   migration runs against fallback identifiers and re-runs once SN
   lands.
2. **LiDAR push map-id routing** — verify by triggering a push from
   each map; if pushes can land before MAPL resolves the active map,
   tighten the buffer logic.
3. **Live video URL scope** — map-scoped or session-scoped; affects
   whether per-map entities share the URL or each has its own.
4. **Maintenance points cloud field** — locate in cloud SETTINGS or
   a dedicated batch family; check `dreame_cloud_dumps/` first per
   the standing convention.
5. **EdgeMaster writability** — currently read-only `binary_sensor`
   per the existing code; the app shows it as a toggle, so likely
   writable. Confirm the wire op and promote to `switch` if so.
6. **"Sub-entities" in the user's app description** — some entries
   (Mowing Direction, Rain Protection, Anti-theft Alarm, etc.) have
   sub-entities behind a single label. Discovered piecemeal during
   implementation; not blocking the design.
