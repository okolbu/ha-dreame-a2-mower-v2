# Greenfield Dreame A2 Mower HA Integration — Design Spec

**Date**: 2026-04-27
**Status**: Approved for implementation planning.
**Replaces**: Priorities P3–P7 of the parent spec
`docs/superpowers/specs/2026-04-27-pre-launch-review-design.md`.
P1 (delete dead code) and P2 (entity audit) are retained as the
inputs to this greenfield work; P3–P7 are no longer applicable on
the legacy repo.

## 1. Why greenfield

The current integration is a fork of an upstream version that
catered to Dreame vacuum cleaners and Dreame lawn mowers. The
upstream did not support our Dreame A2 (g2408) mower; everything
g2408-specific was added later.

Three weeks of P1+P2 cleanup work surfaced the structural problem:
g2408 shares too little with other Dreame devices for the
multi-model scaffolding to add value. The integration is
permanently single-model (parent spec §8 resolution 3). The
cleanup also surfaced ~219 vacuum-vocabulary references in
helpers and scaffolding that surgical entity-deletion alone
won't sweep, and a number of GUI surfaces that grew convoluted
as protocol understanding accreted.

The shared decision (`plan1.txt` 2026-04-27): start a brand new
GitHub repo, build the A2 integration from scratch, lift only
known-working g2408-related code into the new repo as needed.
The legacy repo stays alive as a reference until behavioral
parity is achieved, then renames to `ha-dreame-a2-mower-legacy`
and is archived.

## 2. Repo and naming

- **New repo**: `ha-dreame-a2-mower` (new, not a GitHub fork —
  avoids the misleading "fork of" indicator on a from-scratch
  reimplementation).
- **Legacy repo**: renamed to `ha-dreame-a2-mower-legacy` at
  cutover; archived.
- **HA domain**: `dreame_a2_mower` (kept identical so
  config-flow paths look familiar).
- **License**: MIT.
- **HACS**: pre-release flag set from day 1; the user controls
  when it transitions to stable.
- **Side-by-side install during rebuild**: not required. The
  user accepts running with the app for mower control during
  the rebuild; cutover is one-shot at end of phase F7.

## 3. Architecture rules — the three-layer stack

The integration is a stack: **wire codecs → typed domain state →
HA platform glue**. The user's note that "as long as read/write
upstream works, GUI is downstream" is the architectural
direction — invest below the GUI line.

### Layer 1 — Pure Python protocol (`protocol/`, no HA imports)

- No `homeassistant.*` imports anywhere in this layer. Tests
  run in a vanilla `pytest` venv.
- Wire codecs only: `decode_s1p4(blob) -> MowingTelemetry`,
  `decode_s1p1(blob) -> Heartbeat`, `decode_s2p51(value) ->
  ConfigSet`, `parse_session_summary(json) -> SessionSummary`,
  etc. One module per blob; each has a focused
  `@dataclass(frozen=True)` output.
- Typed everywhere. No `dict` returns from this layer.
- Schema-validated structured blobs live here (the layer-2 of
  the parent spec's three-layer observability — schema
  validators belong with the codecs).
- **Lift posture**: copy from legacy `protocol/` package
  wholesale; clean up any HA-dependent leaks during lift.

### Layer 2 — Domain model (`mower/`, no HA imports)

- `MowerState` — single typed dataclass holding the
  integration's view of the mower. Fields for every piece of
  state any entity reads (`battery_level`, `state`,
  `error_code`, `position_xy`, `position_ne`, `position_latlon`,
  `area_mowed_m2`, etc.). Authoritative source cited in
  docstring per §8.
- `MowerCommand` — typed action descriptors
  (`StartMowing(mode=ALL_AREAS)`, `MowZones([3,1,2])`,
  `Recharge`, etc.) decoupled from how they get sent.
- `Capabilities` — frozen g2408 constants. No per-model
  lookup machinery, no model-string parsing.
- One single `(siid, piid) → field_name` mapping table; no
  upstream-vs-overlay split.
- Unit-tested without HA: feed wire bytes in, assert
  `MowerState` field values out.

### Layer 3 — HA glue (`custom_components/dreame_a2_mower/`)

- `DataUpdateCoordinator[MowerState]` — modern, properly typed.
  Owns the MQTT client + cloud client + state. Invokes layer-1
  codecs on inbound MQTT, updates `MowerState`, fires
  dispatcher on changed fields.
- Every entity is a frozen `EntityDescription` dataclass with
  `value_fn=lambda state: state.X` and (where applicable)
  `exists_fn=lambda state: state.capabilities.X`. No imperative
  `if` chains in entity setup.
- Async-first throughout. Executor offload only for the cloud
  HTTP client.
- `config_flow` with options flow.
- `download_diagnostics` from day 1, with credential redaction
  per §4.8.
- `strings.json` + `translations/` populated from day 1; no
  orphaned vacuum strings.
- Per-module `_LOGGER`. Consistent log prefixes —
  `[NOVEL/{category}]`, `[EVENT]`, `[SESSION]`, `[MAP]` —
  defined as constants in one place.

### Cross-cutting commitments

- **Single source of truth for siid/piid mapping, with named
  ambiguity handlers**: one Python dict, one place, no
  overlay/merge gymnastics. **However**, at least one (siid,
  piid) pair on g2408 is multi-purpose — the same slot carries
  either "robot voice" or "notification type" depending on
  payload shape or device state, and there may be more such
  pairs in the protocol that haven't been catalogued yet.
  Pattern: each mapping entry has a primary `field_name` plus
  an optional `disambiguator` callable that inspects the
  payload and returns an alternate field name when the primary
  isn't right. Disambiguators are explicit, named, and tested.
  The `mower/property_mapping.py` table stays the single
  source — disambiguation is data, not scattered logic.
- **Async-first I/O discipline**: any disk read/write
  (archive index reads, archive entry writes, in-progress.json,
  PCD downloads, MQTT-archive append) goes through
  `hass.async_add_executor_job`. The `protocol/` layer is
  pure CPU work — no disk I/O — so it doesn't need this
  discipline; the HA-glue and `archive/` layers do. HA's
  blocking-I/O detector is the linter; if it logs a warning
  during integration setup, that's a bug to fix, not a noise
  source to ignore.
- **Lessons from legacy referenced inline, not extracted
  upfront**: when a new module is being built, the planner
  refers to the corresponding legacy module to crib edge-case
  handlers. Each lift gets a comment `# Edge case: see legacy
  device.py:NNNN — <one-line rationale>`. The legacy repo stays
  alive as the reference for as long as the planner needs it
  (lift-on-demand).
- **Internal Python identifier names with vacuum flavor are
  fine** — no rename pass. Focus is on no vacuum *concepts*,
  not no vacuum *names*. (`MowerState.cleaning_paused` stays
  as `cleaning_paused`.)

### What we explicitly do NOT do

- No `dreame/` package. The whole vacuum-derived legacy package
  goes away; nothing carries over from it as a unit.
- No `DREAME_MODEL_CAPABILITIES` blob, no model-string parsing,
  no per-model branches.
- No upstream encrypted-blob map decoder (`MapFrameType.I/P`,
  `_decode_map_partial`, `_queue_partial_map`). g2408 cloud-JSON
  only.
- No `_check_consumable` helper for vacuum consumables. Only
  blade/side-brush life from CFG.

## 4. Module structure

```
ha-dreame-a2-mower/
├── README.md                    # rewritten — explicitly NOT a fork
├── LICENSE                      # MIT
├── pyproject.toml
├── hacs.json
├── custom_components/
│   └── dreame_a2_mower/
│       ├── __init__.py          # async_setup_entry / async_unload_entry
│       ├── manifest.json
│       ├── config_flow.py
│       ├── coordinator.py       # DataUpdateCoordinator[MowerState]
│       ├── const.py             # domain consts, log prefixes
│       ├── diagnostics.py       # download_diagnostics
│       ├── strings.json
│       ├── translations/
│       │   └── en.json
│       ├── services.yaml
│       ├── lawn_mower.py
│       ├── sensor.py
│       ├── binary_sensor.py
│       ├── select.py
│       ├── button.py
│       ├── number.py
│       ├── switch.py
│       ├── time.py
│       ├── camera.py
│       ├── device_tracker.py
│       ├── live_map/            # session-finalize state machine
│       │   ├── __init__.py
│       │   ├── state.py
│       │   ├── finalize.py
│       │   └── trail.py
│       ├── archive/             # session/lidar/mqtt archives
│       │   ├── __init__.py
│       │   ├── session.py
│       │   ├── lidar.py
│       │   └── mqtt.py
│       ├── observability/       # novel-token registry, schemas, diagnostic sensor
│       │   ├── __init__.py
│       │   ├── registry.py
│       │   ├── schemas.py
│       │   └── diagnostic_sensor.py
│       ├── www/                 # Lovelace card resources (LiDAR top-down)
│       └── mower/               # domain layer (NO HA imports)
│           ├── __init__.py
│           ├── state.py         # MowerState, MowerCommand
│           ├── capabilities.py
│           ├── property_mapping.py
│           ├── error_codes.py
│           └── side_effects.py
├── protocol/                    # pure-Python codecs, NO HA imports
│   ├── __init__.py
│   ├── telemetry.py
│   ├── heartbeat.py
│   ├── config_s2p51.py
│   ├── session_summary.py
│   ├── pcd.py
│   ├── pcd_render.py
│   ├── trail_overlay.py
│   ├── cloud_map_geom.py
│   ├── cfg_action.py
│   ├── pose.py
│   ├── replay.py
│   ├── unknown_watchdog.py
│   ├── api_log.py
│   ├── mqtt_archive.py
│   └── properties_g2408.py
├── docs/
│   ├── research/                # carried over from legacy
│   │   ├── g2408-protocol.md
│   │   ├── cloud-map-geometry.md
│   │   ├── 2026-04-23-iobroker-cross-reference.md
│   │   └── webgl-lidar-card-feasibility.md
│   ├── superpowers/specs/, superpowers/plans/
│   ├── dashboard-setup.md
│   ├── data-policy.md           # NEW: persistent/volatile/computed split
│   └── lessons-from-legacy.md   # NEW: populated lazily by the planner
├── dashboards/
│   └── mower/
│       └── dashboard.yaml
├── tests/
│   ├── conftest.py
│   ├── protocol/                # lifted verbatim
│   ├── mower/                   # NEW
│   └── integration/             # NEW (pytest-homeassistant-custom-component)
└── scripts/
    ├── mower_tail.py
    └── replay_probe_log.py
```

Notable: `protocol/` is a sibling of `custom_components/`, not
nested. Allows it to be installable as a standalone Python
library if ever desired. `mower/` lives inside the integration
package because it's tightly bound to the integration's runtime,
but imports nothing from `homeassistant.*`.

`live_map/`, `archive/`, `observability/` are subpackages, not
flat modules — each was a 1.7 K+ LOC monolith in legacy; each
becomes a focused 300–600 LOC × N-files package.

## 5. Entity layer + service surface

### 5.1 Top-level "Actions" page (mirrors app main screen)

| Entity | Type | Source | Purpose |
|---|---|---|---|
| `lawn_mower.dreame_a2_mower` | LawnMower | s2.1 + s2.2 | State-aware platform entity. `start_mowing` / `pause` / `dock`. |
| `select.dreame_a2_mower_action_mode` | select | integration state | Options: `all_areas`, `edge`, `zone`, `spot`. |
| `sensor.dreame_a2_mower_active_selection` | sensor | integration state | Read-only display of currently-selected zones/spots in order. |
| `button.dreame_a2_mower_recharge` | button | s2.50 op=… | Equivalent of app's Recharge button. |
| `binary_sensor.dreame_a2_mower_obstacle_detected` | binary_sensor | s1.53 | OBSTACLE_FLAG. |
| `binary_sensor.dreame_a2_mower_rain_protection_active` | binary_sensor | s2.2 = 56 | Rain detected. |
| `binary_sensor.dreame_a2_mower_positioning_failed` | binary_sensor | s2.2 = 71 | SLAM relocation needed. |
| `binary_sensor.dreame_a2_mower_battery_temp_low` | binary_sensor | s1.1 byte[6] bit | Charging refused due to cold. |
| `sensor.battery_level` | sensor | s3.1 | 0..100% |
| `sensor.charging_status` | sensor | s3.2 | enum |
| `sensor.area_mowed_m2` | sensor | s1.4 | Live counter. |
| `sensor.session_distance_m` | sensor | s1.4 | Live counter. |
| `sensor.position_x_m`, `position_y_m` | sensor | s1.4 | Mower-frame coords. |
| `sensor.position_north_m`, `position_east_m` | sensor | computed | Compass-projected via station_bearing option. |
| `device_tracker.dreame_a2_mower_gps` | device_tracker | LOCN | HA Map card support. |
| `camera.dreame_a2_mower_map` | camera | MAP_DATA + s1.4 | Live map with trail overlay. |

### 5.2 Service surface

```yaml
set_active_selection:
  description: Set the ordered list of zones or spots to be mowed by the next "Start" when action_mode is zone/spot/edge.
  fields:
    zones: { example: "[3, 1, 2]" }
    spots: { example: "[1]" }

mow_zone:
  description: One-shot — set selection then start.
  fields:
    zone_ids: { required: true, example: "[3, 1, 2]" }

mow_edge:
  description: Edge-mow on a specific zone or all zones.
  fields:
    zone_id: { example: 3 }

mow_spot:
  description: Spot-mow at a coordinate.
  fields:
    point: { required: true, example: "[12.5, -3.4]" }

recharge:
suppress_fault:
finalize_session:
find_bot:
lock_bot:
```

**No standalone "Start Selected Zone/Spot/Edge" buttons.** Per
the brainstorm: actions belong in service calls; entities
should be state. The current button pile is a misuse of the
entity model.

### 5.3 "Mowing settings" group (CONFIG, app page #2)

| Entity | Type | App label | Source |
|---|---|---|---|
| `number.mowing_height_cm` | number (3.0–7.0, 0.5 step) | Mowing Height | s6.2[0] |
| `select.mowing_efficiency` | select (Standard/Efficient) | Mowing Efficiency | s6.2[1] |
| `switch.edgemaster` | switch | EdgeMaster | s6.2[2] |
| `switch.automatic_edge_mowing` | switch | Automatic Edge Mowing | s2.51 sub-bool |
| `switch.safe_edge_mowing` | switch | Safe Edge Mowing | s2.51 |
| `switch.obstacle_avoidance_on_edges` | switch | Obstacle Avoidance on Edges | s2.51 |
| `switch.lidar_obstacle_recognition` | switch | LiDAR Obstacle Recognition | s2.51 |
| `select.obstacle_avoidance_height` | select (5/10/15/20 cm) | Obstacle Avoidance Height | s2.51 |
| `select.obstacle_avoidance_distance` | select (10/15/20 cm) | Obstacle Avoidance Distance | s2.51 |
| `switch.ai_recognition_humans` | switch | AI Recognition: Humans | s2.51 / s4.62 |
| `switch.ai_recognition_animals` | switch | AI Recognition: Animals | s2.51 / s4.62 |
| `switch.ai_recognition_objects` | switch | AI Recognition: Objects | s2.51 / s4.62 |
| `select.mowing_direction` | select | Mowing Direction | s2.51 |

The s2.51 multiplexed-config sub-fields are decoded by
`protocol/config_s2p51.py`. Settable-sensor reclassification:
anything the app exposes as a toggle/dropdown becomes a
switch/select here, not a sensor.

### 5.4 "More settings" group (CONFIG, app page #3)

| Entity | Type | App label |
|---|---|---|
| `switch.rain_protection` | switch | Rain Protection |
| `select.rain_protection_resume_hours` | select | Rain protection resume time |
| `switch.frost_protection` | switch | Frost Protection |
| `switch.pathway_obstacle_avoidance` | switch | Pathway Obstacle Avoidance |
| `switch.dnd` | switch | Do Not Disturb |
| `switch.quiet_at_night` | switch | Low-Speed at Nighttime |
| `select.navigation_path` | select (Direct/Smart) | Navigation Path |
| `switch.custom_charging_period` | switch | Custom Charging Period |
| `number.auto_recharge_battery_pct` | number (10–25%, 5% step) | Battery for Auto-Recharge |
| `number.resume_battery_pct` | number (80–100%, 5% step) | Battery for Resuming Tasks |
| `switch.start_from_stop_point` | switch | Start from Stop Point |
| `number.stop_point_term_days` | number (1–7) | Stop Point Term |
| `switch.auto_recharge_after_standby` | switch | Auto-Recharge after Extended Standby |
| `switch.capture_obstacle_photos` | switch | Capture AI-Detected Obstacle Photos |
| `switch.light_custom_period` | switch | LED Light: Custom Period |
| `switch.light_in_standby` | switch | LED Light: In Standby |
| `switch.light_in_working` | switch | LED Light: In Working |
| `switch.light_in_charging` | switch | LED Light: In Charging |
| `switch.light_in_error` | switch | LED Light: In Error State |

### 5.5 Schedule (app page #4)

| Entity | Type | What |
|---|---|---|
| `switch.schedule_spring_summer` | switch | Master toggle for Spring/Summer schedule |
| `switch.schedule_autumn_winter` | switch | Master toggle for Autumn/Winter schedule |
| `time.schedule_*_time` (per slot) | time | Per-slot times (where exposable) |
| `text.schedule_summary` | text | Read-only summary built from CFG |

Schedule create/edit is likely BT-only on g2408. The
integration may only **display** schedules and offer master
enable/disable.

### 5.6 Diagnostic / Observability layer

All marked `EntityCategory.DIAGNOSTIC`. Examples:

- `sensor.s5p107_raw`, `sensor.s5p106_raw`, `sensor.s2p2_code`,
  `sensor.mower_status_raw`, `sensor.slam_activity` — raw
  protocol sensors for ongoing protocol-RE.
- `sensor.novel_observations` — count + attribute list of
  unfamiliar (siid, piid)/value/blob-key tokens encountered
  this process. Backed by the registry from §3 Layer 1
  observability.
- `sensor.archived_sessions_count`, `sensor.lidar_archive_count`.
- `sensor.api_endpoints_supported` — diagnostic of which
  routed actions g2408 accepts.
- `sensor.dreame_a2_mower_data_freshness` — per-field
  staleness indicator (see §8).

EXPERIMENTAL entries get
`entity_registry_enabled_default=False` + suffix
`_experimental` and live in this group.

### 5.7 LiDAR popout

| Entity | Resolution | Use |
|---|---|---|
| `camera.dreame_a2_mower_lidar_top_down` | 512×512 | Dashboard thumbnail. |
| `camera.dreame_a2_mower_lidar_top_down_full` | original | Popout / full-resolution view. |

3D interactive view: existing pure-WebGL Lovelace card lifted
from legacy `www/`, updated to point at the new entities.

Service `dreame_a2_mower.show_lidar_fullscreen` is a
convenience wrapper a Lovelace card can invoke.

### 5.8 Archive retention policy

LiDAR PCD files can be large (megabytes each); session JSONs
are smaller but a multi-month accumulation produces dropdown
lists that crash Lovelace selector cards. Each archive class
needs both retention caps **and** user-configurable limits via
the config_flow options.

| Archive | Default cap | Default size cap | Config option |
|---|---:|---:|---|
| Session archive | 50 entries | unbounded by default | `CONF_SESSION_ARCHIVE_KEEP` (count) — already exists in legacy, carry forward |
| LiDAR archive | 20 entries | 200 MB | `CONF_LIDAR_ARCHIVE_KEEP` (count), `CONF_LIDAR_ARCHIVE_MAX_MB` (size) — count exists, add size cap |
| MQTT archive | 14 days (rotation) | unbounded | `CONF_MQTT_ARCHIVE_RETAIN_DAYS` — already exists |
| In-progress | 1 entry (always) | n/a | not user-configurable; the in-progress entry is the working set |

**Eviction policy**: oldest-first by `last_update_ts`. When
either cap is reached, evict the oldest entry until both caps
are satisfied. Eviction logs at INFO so users see what's
disappearing.

**UI safeguards**: the replay-session select entity caps its
options at the configured count even if the on-disk archive
has more (a paranoia layer; the eviction policy should keep
on-disk count in sync, but if a user manually drops files in
the archive dir, the dropdown stays sane).

**Config-flow surface**: each cap appears in the options flow
with sensible bounds (e.g., session count 1..200, LiDAR count
1..50, LiDAR MB 50..2000, MQTT retention 1..90 days). Defaults
chosen so a fresh install never crashes the UI.

### 5.9 Credential discipline

- Cloud creds (`username`, `password`, `country`) entered via
  config_flow, stored in HA's encrypted-at-rest config-entry
  secrets via `CONF_USERNAME` / `CONF_PASSWORD`. Never written
  to disk by the integration outside that mechanism.
- `download_diagnostics` redacts `username`, `password`,
  `token`, `did`, `mac`.
- MQTT archive output: defensive scan; if any log line
  contains `password=` / `token=`, the archive writer skips
  that line and emits a WARNING.
- `.gitignore` from day 1 covers: `*credentials*`, `*.env`,
  `*.pem`, `*.key`, `secrets.yaml`,
  `<config>/dreame_a2_mower/`.
- `CONTRIBUTING.md` includes a "do not commit secrets"
  section.

## 6. Behavioral parity checklist

The success criterion. The legacy integration is retired only
when every item in this checklist demonstrably works in the
greenfield integration. Each item is a regression-test
target.

### Session lifecycle (the area legacy doesn't currently work)

- [ ] Session starts: `lawn_mower` enters `mowing`, `session_active` flips True, in-progress entry written to disk.
- [ ] In-progress survives HA restart: on boot, in_progress.json restored, dashboard picker shows "still running".
- [ ] Mid-run recharge leg merges: track_segments accumulate; in_progress entry updated, NOT promoted-and-recreated.
- [ ] Session ends cleanly: `event_occured siid=4 eiid=1` arrives, summary downloaded, in-progress promoted to archive entry.
- [ ] Session ended while HA was down: on boot, gate detects `s2p56=ended`, in-progress promoted to "(incomplete)" archive.
- [ ] Cloud OSS download fails permanently: after N retries OR T minutes max-age, in-progress promoted to "(incomplete)", `_pending_session_object_name` cleared.
- [ ] Manual finalize service works for the stuck case.

### Map behaviors

- [ ] Initial map fetch on integration setup: dock pin at correct lat/lon, exclusion zones rendered at correct rotation.
- [ ] Live trail draws during mowing: red segments per s1.4 tick, pen-up filter at >5m jumps.
- [ ] Map MD5 dedupe.
- [ ] Zone CRUD via app reflects within 6h periodic refresh OR immediately on s2p50 op=201/215/234.
- [ ] Camera entity_picture updates on map change.

### Action surface

- [ ] `lawn_mower.start_mowing` with `action_mode=all_areas` → whole-lawn mow (op=100).
- [ ] `lawn_mower.start_mowing` with `action_mode=zone` + selection → zone-mow (op=101 with region_id list).
- [ ] `lawn_mower.start_mowing` with `action_mode=zone` + empty selection → log WARN, no-op.
- [ ] `lawn_mower.pause` from mowing state → paused.
- [ ] `lawn_mower.dock` → returns to charger.
- [ ] `recharge` button distinct from "stop" (immediate dock vs cancel session).
- [ ] Service `mow_zone(zone_ids=…)` is one-shot equivalent of set_active_selection + start.
- [ ] `find_bot` makes mower beep.
- [ ] `lock_bot` toggles child lock.
- [ ] `suppress_fault` clears recoverable error.

### Cloud robustness

- [ ] Cloud RPC code 80001: WARN once per process per call type, no propagation as ERROR.
- [ ] OSS session-summary download success: populates `latest_session_summary`.
- [ ] OSS session-summary download failure: retries with backoff + bounded max-age.
- [ ] LOCN sentinel `[-1, -1]`: entity unavailable, not literal `-1`.

### State accuracy

- [ ] s2.2 = 56 → `rain_protection_active` True.
- [ ] s2.2 = 71 → `positioning_failed` True.
- [ ] s2.2 ≠ those codes → both binary sensors False.
- [ ] s1.1 battery_temp_low byte: rising-edge fires WARNING notification; falling-edge dismisses.
- [ ] Manual-mode detection: 15s no s1.4 while `s2.1=mowing` → `manual_mode` True, banner on map.
- [ ] Manual mode resumes telemetry → `manual_mode` False within one tick.

### Archive behaviors

- [ ] Session archive: every completed session's summary persists to `<config>/dreame_a2_mower/sessions/`.
- [ ] LiDAR archive: every `s99.20` OSS key triggers fetch + dedup + write to `<config>/dreame_a2_mower/lidar/`.
- [ ] MQTT archive when enabled: every MQTT message appends to `<config>/dreame_a2_mower/mqtt_archive/YYYY-MM-DD.jsonl`, daily rotation.
- [ ] Archive count sensors increment correctly.
- [ ] **Retention caps enforced**: when `CONF_SESSION_ARCHIVE_KEEP=N` is reached, oldest session evicted; replay-session dropdown never exceeds N options.
- [ ] **LiDAR size cap enforced**: when `CONF_LIDAR_ARCHIVE_MAX_MB` is exceeded, oldest scans evicted until under cap.
- [ ] **All archive disk I/O is async**: integration setup completes without HA logging "blocking call to … in event loop". Confirmed via `pytest-homeassistant-custom-component`'s blocking-I/O detector.

### Settings reflection

- [ ] App-side change to mowing height: `s6.2[0]` push arrives, `number.mowing_height_cm` updates within 1 tick.
- [ ] App-side change to rain protection: `s2.51` push arrives, `switch.rain_protection` updates.
- [ ] Integration-side write via routed action: visible in next CFG read.
- [ ] BT-only-write settings: writable from app, reflected in HA via the s6.2 settings-saved tripwire.

### Observability layer

- [ ] Novel `(siid, piid)` arrival fires `[NOVEL/property]` WARNING once per process.
- [ ] Novel value for known property fires `[NOVEL/value]` WARNING once.
- [ ] Novel key in session_summary JSON fires `[NOVEL_KEY/session_summary]` WARNING.
- [ ] `sensor.novel_observations` count increments on each novel hit.
- [ ] `download_diagnostics` produces a file with state + capabilities + novel-token list + recent log lines, with creds redacted.

**Total: 48 acceptance items.** Each gets a corresponding
integration test using `pytest-homeassistant-custom-component`
or, where automation isn't feasible, a manual checklist entry.

## 7. Phased delivery

| Phase | Scope | What works after | Est |
|---|---|---|---|
| **F1 — Foundation** | `protocol/` lifted; `mower/` domain layer fresh; HA scaffold; config_flow; coordinator minimal; lawn_mower platform; battery sensor. | Integration installs. Mower visible. Battery shows. State (idle/mowing/charging) shows. | 1 wk |
| **F2 — Core state** | All §2.1-confirmed properties surfaced as sensors. Position X/Y, station-bearing-derived N/E, GPS device_tracker. Live map base render (no trail yet). | Dashboard shows everything read-only. | 1 wk |
| **F3 — Action surface** | `select.action_mode`, `sensor.active_selection`, services (set_active_selection, mow_zone, mow_edge, mow_spot, recharge, find_bot, lock_bot, suppress_fault). | User controls mower from HA. | 1 wk |
| **F4 — Settings** | All CONFIG-category switches/numbers/selects backed by s2.51 + CFG. Settable-sensor reclassification done. | App-mirror settings surface. | 2 wk |
| **F5 — Session lifecycle** | `live_map/state.py`, `finalize.py`, `trail.py`. In-progress restore on boot, leg-merge, finalize gate, cloud retry with max-age, manual finalize service. | The "doesn't currently work" area is rebuilt clean. | 1 wk |
| **F6 — Archives + observability** | `archive/` package. `observability/` package with novel-token registry, schema validators, diagnostic sensor, `download_diagnostics`. | Integration self-reports gaps; clean bug reports. | 1 wk |
| **F7 — LiDAR + dashboard polish** | LiDAR popout entity pair, WebGL card lifted, showcase `dashboards/mower/dashboard.yaml` redesigned per app-grouping. | Visual experience matches/exceeds legacy. | 1 wk |

**Total: ~8 weeks of focused work.** Lift-heavy phases (F1, F5,
F7) faster; rewrite-heavy phases (F3, F4) slower.

**Cutover:** at end of F7, run §6 behavioral parity checklist.
Pass = uninstall legacy, install greenfield, rename old repo
to `-legacy`. Fail = identify gap, address, re-run checklist.

## 8. Authoritative data + coherent unknowns policy

### Rule 1 — One authoritative source per field

Every `MowerState` field declares its preferred source via
docstring + §2.1 citation. Where the legacy integration carries
calculated/guessed implementations that newer protocol
understanding has obsoleted, greenfield uses the master
variable.

| Field | Legacy | Greenfield |
|---|---|---|
| `state` | hand-derived from {s2.1, s2.2, charging_status, started, cleaning_paused} | s2.1 alone (apk-confirmed enum) |
| `error_code` | s2.2 read as "STATE codes" | s2.2 as error per apk fault index; phase codes redirected to phase-binary-sensor pair |
| `mowing_phase` | s1.4 byte[8] | s1.4 byte[8] (unchanged — confirmed) |
| `area_mowed_m2` | computed from session telemetry | s1.4 bytes[29-30] (confirmed) |
| `mowing_height_cm` | inferred from CFG | s6.2[0] (confirmed) |
| `wifi_rssi` | none | s6.3[1] (confirmed g2408 overlay) |
| `cloud_connected` | derived from connection state | s6.3[0] (confirmed) |
| `position_*` | s1.4 (already authoritative) | s1.4 (unchanged) |

**Where new authority is unclear, surface for discussion.** No
silent picking among multiple plausible sources.

### Rule 2 — Coherent unknowns policy per field

Three modes, applied per-field:

a) **Persistent (last known across HA boot)** — slow-changing state where "last known" beats "unavailable":
- mower position (X/Y, N/E, lat/lon)
- map data
- settings values (CFG-derived)
- latest session summary
- station bearing
- archive counts

b) **Volatile (unavailable when no fresh data)** — fast-changing state where stale beats misleading:
- battery level
- charging status
- mowing state
- live trail
- obstacle flag

c) **Computed (derives from a source field, inherits its policy)** — error_description from error_code, etc.

### Rule 3 — Mechanism

- HA's `RestoreEntity` mixin for Persistent fields.
- Each Persistent field exposes a `last_updated` attribute so
  dashboards can show "last known: X (5 min ago)".
- Volatile fields use `_attr_available = False` when source is
  None.
- `sensor.dreame_a2_mower_data_freshness` (diagnostic) reports
  per-field staleness for the user's debugging.

### Documentation

- `docs/research/g2408-protocol.md` §2.1 gains a column:
  "authoritative / calculated / guessed" + integration's source
  choice per field.
- `mower/state.py` dataclass docstrings cite §2.1 row +
  persistence mode for each field.
- `docs/data-policy.md` documents the persistent/volatile/computed
  split.

## 9. Showcase dashboard scope

Lovelace dashboard `dashboards/mower/dashboard.yaml` redesigned
against the rationalized entity set, mirroring `APP_INFO.txt`
organization.

```
views:
  - title: Mower            # app's main "Actions" page
    cards: live map | state strip | action strip | active selection | alerts
  - title: Mowing settings  # app page #2
    cards: General Mode setting cards
  - title: More settings    # app page #3
    cards: rain/frost/DND/charging/lighting/photo settings
  - title: Schedule         # app page #4
    cards: master toggles + summary
  - title: LiDAR
    cards: 3D interactive WebGL + popout button + archive count
  - title: Sessions
    cards: latest session summary + archived sessions list + replay/finalize service buttons
  - title: Diagnostics      # opt-in for power users
    cards: novel observations + raw protocol sensors + archive counts + endpoints
```

Lovelace cards used: standard HA cards + the existing WebGL
LiDAR card. No `xiaomi-vacuum-map-card` (per memory).

## 10. Out of scope (deferred)

- Migration from legacy on-disk archives. The user accepts
  delete-on-cutover; old archives can be regenerated from
  `probe_log_*.jsonl` if ever needed.
- Auto-detection of g2408 vs other Dreame mower models. The
  integration is permanently single-model; refusing to set up
  on a non-g2408 device is a config_flow validation step.
- Multi-mower-per-account. Single-mower until requested.
- Voice-pack and stream-camera integration (vacuum-only on
  upstream; g2408 has no front camera).

## 11. Open questions for review

None. All architectural sections converged during brainstorm:

1. Repo strategy → new repo, no fork. ✅
2. Lift posture → lift-on-demand, legacy stays as reference. ✅
3. Parity criterion → behavioral parity (§6). ✅
4. GUI redesign scope → §5. ✅
5. Action surface → service-driven + action_mode select. ✅
6. Settable-sensor reclassification → §5.3 / §5.4. ✅
7. Authoritative-data policy → §8. ✅
8. Identifier renames → no rename pass; vacuum-flavored names
   in internal Python identifiers are fine. ✅
9. Multi-purpose siid/piid pairs (e.g., the robot-voice /
   notification-type slot) → primary `field_name` + named
   `disambiguator` callable, in a single mapping table. §3. ✅
10. Async I/O discipline → all archive/disk reads + writes go
    through `hass.async_add_executor_job`. §3 + §6. ✅
11. Archive retention caps → per-archive count and (LiDAR-only)
    size caps with config-flow options; UI dropdown safeguards.
    §5.8. ✅

Implementation plan to follow via writing-plans skill.
