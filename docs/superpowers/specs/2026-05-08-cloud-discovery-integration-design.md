# Cloud Discovery — Full Integration Design

**Status:** approved 2026-05-08
**Scope:** unify the integration's cloud-fetch pipeline around
`get_batch_device_datas([])`, integrate the seven new key families
discovered (M_PATH, SETTINGS, SCHEDULE, AI_HUMAN, FBD_NTYPE,
OTA_INFO, TASKID, prop.s_*), and close startup-availability gaps
where cloud data can replace MQTT-wait.

## Why

A 2026-05-08 cloud-API discovery (using the `[]` empty-list pattern
on `get_batch_device_datas`) revealed seven previously-undecoded
key families on the user's g2408 (fw 4.3.6_0550) — all returned
free of charge in the existing batch response we were already
hitting. The integration today fetches MAP from a hardcoded
`MAP.0..MAP.27` request and silently discards everything else. This
spec wires the rest.

The newly-decoded `SETTINGS` batch unblocks several
"blocked-by-investigation" TODO items, most notably the previously-
suspected-BT-only mowing direction setting.

## Discovered key families (2026-05-08)

| Family | Bytes | Status before | Status after this spec |
|---|---|---|---|
| `MAP.*` | 45,361 | Decoded (a99) | Unchanged |
| `M_PATH.*` | 28,060 | Not fetched | Decoded; rendered as gray cloud-history overlay per map |
| `SETTINGS.*` | 1,780 | Not fetched | Decoded; surfaced as 15 per-map active-follower entities |
| `SCHEDULE.*` | 121 | Not fetched | Decoded headers; populates Schedule view; blob decode deferred |
| `AI_HUMAN.*` | 6 | Not fetched | Decoded as boolean; switch entity |
| `FBD_NTYPE.*` | 14 | Not fetched | Decoded as per-map dict; diagnostic attribute |
| `OTA_INFO.*` | 7 | Not fetched | Decoded as `[status, percent]`; sensor entity |
| `TASKID.*` | 1 | Not fetched | Decoded as int; diagnostic attribute |
| `prop.s_*` | 3 keys | Not fetched | Decoded; diagnostic attributes |

## Architecture

### New cloud-fetch pipeline

Today: 8+ scattered cloud calls across multiple intervals
(`_refresh_cfg` 10min, `_refresh_map` 6hr, `_refresh_locn` 60s,
`_refresh_dock` 60s, `_refresh_net` hourly, `_refresh_mihis` 10min,
`_refresh_dev` 6hr, `_poll_slow_properties` hourly, plus on-demand
`_refresh_mapl`).

Going forward: **3 categories of fetches** consolidated into 4 timers.

1. **Empty-batch fetch** (`get_batch_device_datas([])`, every 10 min) —
   returns all chunked-data families in one call: MAP, M_PATH,
   SETTINGS, SCHEDULE, AI_HUMAN, FBD_NTYPE, OTA_INFO, TASKID, plus
   `prop.s_*` standalone keys.
2. **CFG fetch** (`fetch_cfg()`, every 10 min, paired with #1) —
   returns 24 global keys (DND, language, LED, child lock, etc.)
   not present in the empty-batch.
3. **Fast-cadence probes** — LOCN (60s), DOCK (60s), MAPL (on
   `s1p50` ping, on `mowing_started` event, plus 10min). These are
   hardware-state-dependent and need sub-minute updates.

A single `_refresh_cloud_state()` runs (1) and (2) under one timer;
the result populates a unified `CloudState` dataclass that all
consumers (entities, services, render path) read from.

Cadence reduces from ~8 timers to 4. The empty-batch + CFG fetch
takes ~250-500 ms total (one HTTP roundtrip per call, each
returning a few hundred KB). Suitable for 10-minute periodicity
without device load.

### `CloudState` dataclass (new top-level container)

```python
@dataclass(frozen=True, slots=True)
class CloudState:
    cfg: dict[str, Any]                              # 24 CFG keys
    maps_by_id: dict[int, MapData]                   # existing
    mow_paths_by_map_id: dict[int, MowPathData]      # NEW (from M_PATH)
    settings: SettingsRoot                           # NEW (preserves dual-level)
    schedule: ScheduleData                           # NEW
    ai_human_enabled: bool | None                    # NEW (decoded from "true"/"false")
    forbidden_node_types_by_map: dict[int, dict]     # NEW (FBD_NTYPE)
    ota_status: tuple[int, int] | None               # NEW [status, percent]
    task_id: int                                     # NEW
    props: dict[str, str]                            # NEW prop.s_* dict
    locn: tuple[float, float] | None                 # existing
    dock: dict[str, Any]                             # existing
    mapl: list[list] | None                          # existing
    mihis: dict[str, Any]                            # existing
    fetched_at_unix: int                             # bookkeeping
```

`SettingsRoot` deliberately preserves the unknown dual-level
structure — entry 0 is treated as canonical for reads, but writes
read-modify-write the FULL list to avoid corrupting whatever entry
1 means:

```python
@dataclass(frozen=True, slots=True)
class SettingsRoot:
    raw: list[dict]                       # full unmodified list
    by_map_id_canonical: dict[int, dict]  # raw[0]["settings"][str(id)] convenience

@dataclass(frozen=True, slots=True)
class MowPathData:
    map_id: int
    segments: tuple[tuple[tuple[int, int], ...], ...]  # cloud-mm pairs per segment

@dataclass(frozen=True, slots=True)
class ScheduleData:
    version: int
    slots: tuple[ScheduleSlot, ...]

@dataclass(frozen=True, slots=True)
class ScheduleSlot:
    slot_id: int
    name: str
    raw_blob_b64: str  # decoded later when format known
```

## Per-map entities (SETTINGS-driven, active-follower)

Active-follower pattern as established in a92 multi-map. All 15
fields read from `cloud_state.settings.by_map_id_canonical[active_map_id]`
and write through a `_write_setting(field, value)` helper that
read-modify-writes the full `SettingsRoot.raw` list.

| Entity | Type | Field | Notes |
|---|---|---|---|
| `number.mowing_height` | number | `mowingHeight` | cm; range 2-7 typical |
| `select.mowing_direction` | select | `mowingDirection` | discrete options 0/90/180/270 |
| `select.mowing_direction_mode` | select | `mowingDirectionMode` | catalog TBD |
| `number.cutter_position` | number | `cutterPosition` | |
| `number.cutter_position_height` | number | `cutterPositionHeight` | |
| `number.edge_mowing_num` | number | `edgeMowingNum` | passes |
| `switch.edge_mowing_auto` | switch | `edgeMowingAuto` | |
| `switch.edge_mowing_safe` | switch | `edgeMowingSafe` | |
| `switch.edge_mowing_obstacle_avoidance` | switch | `edgeMowingObstacleAvoidance` | |
| `select.edge_mowing_walk_mode` | select | `edgeMowingWalkMode` | |
| `switch.obstacle_avoidance_enabled` | switch | `obstacleAvoidanceEnabled` | |
| `number.obstacle_avoidance_height` | number | `obstacleAvoidanceHeight` | cm |
| `number.obstacle_avoidance_distance` | number | `obstacleAvoidanceDistance` | cm |
| `number.obstacle_avoidance_sensitivity` | number | `obstacleAvoidanceSensitivity` | 1-3 |
| `select.obstacle_avoidance_ai` | select | `obstacleAvoidanceAi` | bitfield → catalog TBD |

Switching `select.dreame_a2_mower_active_map` rebinds all 15 via
`_handle_coordinator_update`.

**Writability:** the cloud's set-settings action shape isn't yet
known. Phase-1 entities are read-only, with a write attempt logging
a warning and re-polling MAPL. Capturing the write wire format is
a follow-up TODO (probe procedure: change a setting in app while
probe log records; diff outbound traffic).

## M_PATH integration

Decoded via legacy upstream's regex approach
(`alternatives/dreame-mower/.../map_data_parser.py:256` —
`parse_mow_paths`):

- Regex `\[(-?\d+),(-?\d+)\]` finds all `[x,y]` pairs in the joined
  string
- `[32767,-32768]` is the segment-break sentinel
- Coordinates are 1/10th-scale (decimeters); multiply by 10 for mm
- M_PATH.info is the byte offset to skip (legacy: `raw = raw[split_pos:]`)

Result: per-map list of segments, stored as `MowPathData(map_id,
segments)` in `CloudState.mow_paths_by_map_id`.

**Renderer change:** per-map static camera (`camera.dreame_a2_mower_map_<id>`)
overlays the cloud-persisted track in **gray** (distinct from the
live-mow red trail rendered by the active-follower camera). The
active-map-follower camera shows live trail; per-map static cameras
show cloud history.

Local session-archive trails stay as-is (live capture during a
mow). They're the **fast path** (sub-second updates). M_PATH is
the **historical/durable** path (cloud-authoritative across
reboots, includes prior sessions even after the integration
restarted).

## SCHEDULE integration

Read-only entity:
- `sensor.dreame_a2_mower_schedule_count` — state = number of slots;
  attributes = `slots: [{slot_id, name, version}, ...]`

Dashboard `Schedule` view replaces the markdown placeholder with a
dynamic card showing each slot's name + version. The note "BT-only
for editing" stays as a disclaimer.

Blob decode (`raw_blob_b64`) is deferred — the format is unknown.
Possible candidates: a binary schedule encoding (cron-like rules);
investigation TBD.

## Small probes → entities

- `switch.dreame_a2_mower_ai_human_detection` — value from `AI_HUMAN`;
  read-only Phase 1; writable target = TBD setSettings action.
- `sensor.dreame_a2_mower_ota_status` — state = first int (status code);
  attribute `percent` = second int. Semantics TBD; surfaced
  as-is for now.
- `FBD_NTYPE` → diagnostic attribute on `camera.dreame_a2_mower_map`
  (per-map forbidden-node-type metadata).
- `TASKID` → diagnostic attribute on `lawn_mower.dreame_a2_mower`.
- `prop.s_*` → not surfaced as entities (Xiaomi-style auth/upgrade/
  plugin housekeeping; included in download_diagnostics blob only).

## Startup-availability audit

A separate concern: the integration today shows many sensors as
"Unknown" / "Unavailable" until specific MQTT messages arrive
(s1p1 heartbeat ~45s for wifi_rssi/battery; s1p4 telemetry ~5s for
position; s2p51 multi-config blob for various). The empty-batch
fetch returns CLOUD-AUTHORITATIVE values for many of these fields —
they could be seeded at startup so the dashboard isn't blank for
the first ~minute after install/restart.

**Audit work (part of implementation, scoped here):**

1. Walk every sensor / binary_sensor / switch / number / select
   entity. For each, identify the MowerState field it reads from
   and which cloud source could populate it (CFG, SETTINGS, MAPL,
   LOCN, DOCK, MIHIS, properties poll, MQTT push).
2. For fields where the cloud has the data: ensure
   `_refresh_cloud_state()` populates the corresponding MowerState
   field. Many already do (MIHIS seeds total_mowed_area_m2 etc., we
   added that in a91-era). New ones: SETTINGS-driven fields can be
   seeded immediately.
3. For fields that are MQTT-only (e.g., live position from s1p4,
   live battery percent from s3p1 push, real-time error_code): no
   change — these are inherently real-time.
4. **Deduplicate redundant code paths.** Several existing fields
   are populated via TWO paths: (a) seed from local archive at
   boot, (b) overwrite from cloud poll later. Examples:
   `total_lawn_area_m2` (seed from session-archive map_area_m2,
   overwrite from MIHIS), `mowing_count` (similar pattern).
   Audit and consolidate to single source of truth.

## Migration / breaking changes

- **Existing archive wiped on first install of this version.**
  Probe-log replay path rebuilds. Confirmed acceptable.
- **Existing CFG-driven entities unchanged.** No rename, no
  state-history loss.
- **15 NEW SETTINGS-driven entities have new entity_ids.** No
  collision with existing.
- **The `_refresh_*` methods are consolidated** into
  `_refresh_cloud_state()`. Internal refactor; entity contracts
  preserved. Consumers (entities, services) read `coordinator.cloud_state`
  instead of `coordinator._cached_*` properties.
- **Diagnostic attributes added** to camera + lawn_mower entities
  for SETTINGS dual-level, FBD_NTYPE, TASKID. Not user-facing UI;
  visible in more-info dialog and download_diagnostics blob.

## Files

**New:**
- `custom_components/dreame_a2_mower/cloud_state.py` — `CloudState`
  + sub-dataclasses (SettingsRoot, MowPathData, ScheduleData,
  ScheduleSlot)
- `custom_components/dreame_a2_mower/protocol/m_path.py` —
  `parse_m_path_batch()` regex decoder
- `custom_components/dreame_a2_mower/protocol/settings.py` —
  `parse_settings_batch()` + `serialise_settings_for_write()`
- `custom_components/dreame_a2_mower/protocol/schedule.py` —
  `parse_schedule_batch()` (header-only for now)
- `tests/protocol/test_m_path.py`, `test_settings.py`,
  `test_schedule.py`, `test_cloud_state.py`

**Modified:**
- `custom_components/dreame_a2_mower/cloud_client.py` — add
  `fetch_full_cloud_state()` wrapping the empty-batch + cfg fetch +
  small probes; existing `fetch_*` methods stay for backward compat
- `custom_components/dreame_a2_mower/coordinator.py` — replace 8
  `_refresh_*` with `_refresh_cloud_state()`; consume `CloudState`
  in `_on_state_update`, render path, etc.
- `custom_components/dreame_a2_mower/number.py`, `select.py`,
  `switch.py` — add 15 new SETTINGS-driven entities
- `custom_components/dreame_a2_mower/sensor.py` — add OTA + schedule
  count
- `custom_components/dreame_a2_mower/camera.py` — surface FBD_NTYPE
  + per-map M_PATH overlay rendering
- `custom_components/dreame_a2_mower/map_render.py` — gray
  cloud-track overlay function
- `custom_components/dreame_a2_mower/mower/state.py` — add fields
  populated by SETTINGS (per-map mowing config: mowing_height,
  mowing_direction, etc.) so the active-follower entities have
  state to read
- `custom_components/dreame_a2_mower/services.py` — keep
  `dump_map_diagnostics` and `discover_cloud_api` services (useful
  for future firmware-update re-discovery when new key families
  appear); update them to write to `<config>/dreame_a2_mower/`
  diagnostics dir rather than logging
- `dashboards/mower/dashboard.yaml` — Schedule view becomes dynamic;
  add SETTINGS-driven entity cards under "What to mow" section
- `docs/multi-map.md` + `docs/events.md` — update for new entities
- `README.md` — feature list update

## Out of scope (deferred TODOs — explicitly preserved here so they're not lost)

1. **SETTINGS dual-level semantic.** Two entries observed (both
   `mode: 0` in user's data). Need multi-mode test scenarios to
   determine if entries are: (a) global vs per-map, (b) active vs
   default profile, (c) something else. Without this, we read entry
   0 as canonical and preserve entry 1 unchanged on writes.
2. **SETTINGS write wire format.** The setSettings action shape
   isn't captured. Phase-1 entities are read-only; writes log a
   warning. Probe procedure: change a setting in app with probe
   log running, diff outbound traffic.
3. **SCHEDULE blob format.** `raw_blob_b64` is base64 — likely a
   binary schedule encoding. Decode + edit support deferred.
   **Reference:** `/data/claude/homeassistant/schedule-doc.txt`
   captures the user's app-side schedule UI plus concrete data
   points (3 mows in Spr & Sum Schedule, 1 mow in Aut & Win, with
   exact times and days-of-week) — gives the byte-correlation
   needed to reverse-engineer the blob format. **Reference batch
   captures:** `docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`
   (initial) and `docs/research/cloud-discovery/2026-05-08-post-schedule-toggle-batch.json`
   (after the user flipped toggles around 10:55 — same blob, suggesting
   enabled-state lives elsewhere, not in the blob).
4. **AI_HUMAN write path.** Same as SETTINGS — toggle in app while
   probing.
5. **OTA_INFO field semantics.** `[2, 100]` guessed as
   `[status, percent]` but values are guesses. Decode definitively
   when an OTA event happens (rare).
6. **Render `nav_paths` overlay on the camera** (separate TODO from
   earlier — `MapData.nav_paths` decoded but not yet drawn). Phase
   2 polish.
7. **LiDAR archive — per-map?** (separate TODO from earlier).
8. **Lifecycle event-surface PR — review-flagged cleanups**
   (separate TODO from earlier).
9. **Alert-tier event surface** (separate TODO from earlier).
10. **Novel-observation sensor floods on continuous-integer slots**
    (separate TODO from earlier).
11. **Add integration icon via home-assistant/brands PR**
    (separate TODO from earlier).
12. **Surface dock-departure repositioning UX** (separate TODO).
13. **Patrol Logs / Firmware update / Change PIN / Pathway
    Obstacle Avoidance / SUPPRESS_FAULT** (existing blocked-by-X
    TODOs).
14. **`_refresh_*` consolidation**: audit all current `_refresh_*`
    methods. After migration, individual fast-cadence probes
    (LOCN, DOCK, MAPL) keep their separate timers, but the slow
    ones (NET, DEV, MIHIS, MAPI etc.) fold into the empty-batch
    path. Document which moved and which stayed.
15. **Generalise shape-mismatch warnings** (a99 added the helper
    for `paths`; future PRs adopt it across all decoders).

## Testing

- Unit tests for each new decoder (m_path, settings, schedule) using
  fixtures captured from the user's actual data
  (`docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json`
  has the raw batch; extract per-family slices into test fixtures).
- Round-trip test for SETTINGS write: read → modify field → serialise →
  re-parse → confirm the modified field changed and others didn't.
- Test for the `_refresh_cloud_state()` method that mocks the cloud
  client and asserts the full `CloudState` populates correctly.
- Active-follower entity tests for each of the 15 SETTINGS-driven
  entities (read returns active-map's value; switching active-map
  changes the value; writes call the right helper).
- Renderer test for M_PATH overlay on per-map cameras.

## Compatibility

This is a breaking-change PR for internal architecture (replaces
the `_refresh_*` series, replaces `_cached_maps_by_id` with
`cloud_state.maps_by_id`, etc.). External entity contracts are
preserved; users see new entities appear and minor changes to
existing entity attributes (added diagnostic data).

The user's existing session archive will be wiped on first install
of this version (per design note); probe-log replay rebuilds. No
auto-migration code is included.
