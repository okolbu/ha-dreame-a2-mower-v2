# Dreame A2 Mower — Home Assistant Integration

A Home Assistant integration for the **Dreame A2** robotic lawn mower
(model `dreame.mower.g2408`). Written from scratch for the A2 — **not a
fork** of any upstream vacuum or mower project.

## Status

🟢 **Alpha pre-release (`v1.0.18a*`).** Feature-complete for a single
`dreame.mower.g2408` on one Dreame cloud account, and in daily use against
a live mower. Distributed as a HACS pre-release while protocol coverage and
live validation continue. Built greenfield for the A2 — the original F1–F7
phase rollout lives in `docs/superpowers/plans/`; since then the
coordinator, cloud client, entity platforms, and map renderer have each
been decomposed into focused packages and multi-map support was added.

## Features

### Live state
- **Lawn mower entity** with `start_mowing` / `pause` / `dock` actions.
- **Live map camera** rendered server-side from the cloud's map JSON
  + s1.4 telemetry trail. Lawn boundary, mowing zones (translucent),
  exclusion / no-obstacle / spot zones, dock pin, GPS-anchored.
- **Battery, charging status, error code, obstacle flag, rain
  protection, positioning failed, battery temp low** as native HA
  entities.
- **Position** as `device_tracker` (lat/lon via cloud LOCN) plus
  `sensor.position_x_m` / `_y_m` / `_north_m` / `_east_m` derived
  from s1.4 + station-bearing rotation.

### Control surface
- `action_mode` select (`all_areas` / `edge` / `zone` / `spot`).
- Services: `set_active_selection`, `mow_zone`, `mow_edge`, `mow_spot`,
  `recharge`, `find_bot`, `lock_bot`, `suppress_fault`,
  `set_schedule_plans`, `finalize_session`, `replay_session`,
  `refresh_cloud_state`, `show_lidar_fullscreen`.
- All routed through the cloud RPC `s2.50 aiid=50` envelope (the only
  command path that works on g2408 — direct `action()` returns 80001).

### Settings (cloud + s2.51)
- Switches: rain protection, DnD, low-speed-at-night, custom charging
  window, child lock, anti-theft (lift / off-map / realtime location),
  LED behaviour (standby / working / charging / error).
- Numbers: volume, auto-recharge battery %, resume battery %.
- Times: DnD start/end, low-speed start/end, charging start/end.
- Selects: mowing efficiency, rain-protection resume hours.

### Known sync nuances

A subset of g2408 settings is on the Dreame app's "Mowing settings" page
(the one with the explicit Save button). All of these settings DO
propagate through the cloud — verified by toggling in one app instance
and observing the change in a second app instance on a different
device, with zero Bluetooth involvement. But for some of them it's
not yet verified whether the device firmware applies HA-initiated
writes vs only the writes initiated by the Dreame app itself:

- AI Obstacle Recognition: Humans / Animals / Objects
- Mowing Direction, Mowing Pattern, Edge Walk Mode
- Edge Mowing: Auto / Safe / Obstacle Avoidance
- LiDAR Obstacle Recognition + Obstacle Avoidance Distance / Height / Sensitivity
- Mowing Height, Cutter Position, Cutter Height, Edge Passes

For these, the safe pattern today is: **toggle them in the Dreame app**.
HA picks up the change automatically within ≤2 min (cloud poll cadence;
some changes also fire MQTT and surface within seconds). Force an
immediate sync via **`button.dreame_a2_mower_refresh_from_cloud`** /
`dreame_a2_mower.refresh_cloud_state` if you don't want to wait.

If you toggle one of these in HA: the cloud accepts the write (other
app instances on cold-start will see it) but the original Dreame app
session may keep showing the pre-write value due to UI cache, and it's
not yet established whether the device firmware applies HA-side writes.
The path the Dreame app uses on Save is likely a cloud routed-action
target we haven't enumerated yet; capturing it is the open work item.

Full per-entity reference — read source and verification status for every
switch / select / number / sensor / button / service — in
[`entity-inventory.yaml`](custom_components/dreame_a2_mower/entity-inventory.yaml);
the cloud write paths are in
[`docs/research/cloud-write-reference.md`](docs/research/cloud-write-reference.md).

### Multi-map

The integration tracks every cloud-side map and exposes each as a per-map
**sub-device** (SN-keyed, namespaced under the integration prefix). The
active map drives the live camera + the zone / spot / edge / direction /
efficiency selectors; each map also gets its own static map camera, LiDAR
camera, WiFi-heatmap camera, and metadata sensors (area, segment count,
spots, exclusion / no-obstacle zones, maintenance points, and per-map
session totals). The replay picker spans all maps. See `docs/multi-map.md`.

### Session lifecycle
- **Live trail** drawn over the base map during a mow; pen-up filter
  splits legs at >5 m jumps; <20 cm segments deduped.
- **In-progress persistence** survives HA restarts.
- **Finalize gate** with bounded retry (30-min max-age, 10 attempts,
  60 s interval) — no more sessions stuck "fetching summary" forever.
- **Manual finalize button + service** as escape hatch.
- **Session archive** at `<config>/dreame_a2_mower/sessions/`,
  content-addressed by md5; replay-session select on the dashboard
  drives the live map back to any archived session.

### LiDAR
- **Top-down camera** (512² thumbnail + 1024² full-resolution popout)
  rendered from archived PCD blobs.
- **WebGL Lovelace card** at `/dreame_a2_mower/dreame-a2-lidar-card.js`
  for an interactive 3D view (orbit / zoom / splat-size slider, optional
  base-map underlay).
- **PCD archive** with retention caps (count + total MB) configurable
  in the options flow.
- HTTP endpoint `/api/dreame_a2_mower/lidar/latest.pcd` (auth-gated)
  serves the most recent archived blob for desktop tools (Open3D,
  CloudCompare, MeshLab).
- **Per-map LiDAR cameras** — a top-down camera per known map.

### WiFi heatmap

- **WiFi-signal heatmap cameras** rendered from archived WiFi-strength
  samples laid over the map: a picker-driven WiFi camera (follows the
  WiFi-archive select) plus a per-map WiFi camera for each known map.
- **WiFi archive select** chooses which captured heatmap to display;
  `input_boolean.dreame_a2_mower_wifi_flip_x` / `_flip_y` correct the
  overlay orientation when a map needs it.

### Observability
- **`sensor.dreame_a2_mower_novel_observations`** — count + attribute
  list of unfamiliar protocol shapes seen this process.
- **`sensor.dreame_a2_mower_data_freshness`** (default-disabled) —
  per-field staleness in seconds.
- **`sensor.dreame_a2_mower_api_endpoints_supported`** (default-disabled)
  — passive cloud-RPC accept/reject log.
- Raw diagnostic sensors for unmapped slots so values surface during
  ongoing protocol-RE work.
- **`download_diagnostics`** dumps state, capabilities, novel-token
  list, freshness, endpoint log, and recent NOVEL log lines (creds
  redacted per spec §5.9).

### Events and notifications

Mowing start/pause/resume/end and dock arrive/depart fire as HA event
entities (`event.dreame_a2_mower_lifecycle`). Each event carries a
payload with the action mode, area mowed, etc. — wire them to push
notifications, Logbook, automations, or your own dashboards. See
`docs/events.md` for the full event reference and recipes. The
follow-up alert tier (emergency_stop, lifted, stuck, ...) lands in
a later release.

### Showcase dashboard
An 11-view Lovelace dashboard at `dashboards/mower/dashboard.yaml`:
Mower, Map Selector, Settings & Zones, Schedule, LiDAR, WiFi Coverage,
Sessions, More Settings, Diagnostics, Tools, and Photo Privacy. Uses
standard HA cards plus the bundled custom cards (LiDAR / schedule /
replay) and a few common HACS cards (apexcharts, button-card, card-mod,
plotly).

## Architecture

Three-layer stack with strict layering:

| Layer | Path | HA imports? | Responsibility |
|---|---|---|---|
| 1 | `custom_components/dreame_a2_mower/protocol/` | ❌ | Pure-Python wire codecs (s1.1 / s1.4 / s2.51 / session_summary / PCD / cloud-map geometry / TASK envelope). Unit-testable in a vanilla pytest venv. |
| 2 | `custom_components/dreame_a2_mower/{mower,observability,archive,live_map}/` | ❌ | Typed domain layer — `MowerState` dataclass, capabilities, property mapping, novel-observation registry, archives, live-map session state machine. |
| 3 | `custom_components/dreame_a2_mower/*.py` | ✅ | HA glue — config flow, coordinator, all platforms, services, diagnostics. |

The layering invariant (`grep` runs on every CI run) prevents
upstream creep: layer-1 and layer-2 must never import `homeassistant.*`.

## Installation

Currently distributed as a HACS custom repository. After v1.0.0
graduates from `a*` pre-release, regular HACS releases will follow.

1. HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/okolbu/ha-dreame-a2-mower` with category
   **Integration**. Enable "show beta" if you want pre-release tags.
3. Install **Dreame A2 Mower** from HACS, restart HA.
4. Settings → Devices & Services → **Add Integration** → "Dreame A2
   Mower". Enter Dreame cloud credentials.
5. Configure → **Options** → set retention caps (LiDAR archive size
   defaults to 200 MB; PCDs run 2-3 MB each).

### Bundled Lovelace card

To use the WebGL LiDAR view:

1. Settings → Dashboards → Resources → **Add Resource**.
2. URL: `/dreame_a2_mower/dreame-a2-lidar-card.js`, type
   `JavaScript Module`.
3. Add `type: custom:dreame-a2-lidar-card` to a card. Example in
   `dashboards/mower/dashboard.yaml`'s LiDAR view.

### Live map / static replay refresh speed

The Mower-tab live map and the Sessions-tab static replay image are
served by HA `camera` entities. HA's built-in `picture-entity` card
delegates to `<hui-image>`, which **polls cameras every 10 seconds**
(`UPDATE_INTERVAL = 10000` in `hui-image.ts`) and ignores
`entity_picture` state-change events. That makes mode/preference
changes (e.g. picking a new Mowing target) appear to take ~5 s on
average before the preview updates.

The integration also bundles an **experimental** custom card —
`custom:dreame-mower-live-image-card` — that listens for state pushes
directly and swaps `<img src>` on every change for sub-second refresh.
It is **not registered automatically** — an earlier `add_extra_js_url`
auto-registration proved unreliable (on YAML-mode dashboards the card
rendered a red "Configuration error" because it never landed in the
dashboard's element registry), so the bundled
`dashboards/mower/dashboard.yaml` uses `picture-entity` for the live-map
and work-log images. To try the faster card on a storage-mode dashboard,
register it as a normal Lovelace resource (Settings → Dashboards →
Resources → Add:
`/dreame_a2_mower/dreame-mower-live-image-card.js`, type
`JavaScript Module`) and use:

```yaml
- type: custom:dreame-mower-live-image-card
  entity: camera.dreame_a2_mower_map
  max_width: "50%"            # optional
  # aspect_ratio: "1 / 1"     # optional; for the work-log square
  # object_fit: contain       # optional; pairs with aspect_ratio
```

If it shows "Configuration error", use `picture-entity` instead (the
~5 s poll lag is purely cosmetic).

### Animated session replay

The Sessions tab includes an optional animated replay that draws the
mower's trail over the base map at ≤30s total, with proportional
freezes during charging / stuck / faulted intervals.

To enable:

1. Add a Lovelace resource (Settings → Dashboards → Resources → Add):
   - URL: `/dreame_a2_mower/dreame-mower-replay-card.js`
   - Type: JavaScript Module
2. Create an `input_boolean.dreame_a2_mower_animate_session` toggle
   helper (Settings → Devices & Services → Helpers → Create Helper →
   Toggle, default state Off).
3. Refresh the Sessions tab. Use the new "Animate replay (≤30s SVG)"
   toggle in the Replay picker card to switch from the static
   work-log image to the animated SVG card.

The JS ships with the integration — no separate HACS install needed.

### Activity logbook (optional dedup)

The Mower tab includes an activity logbook card that surfaces the
integration's two `event` entities — lifecycle (mowing started /
paused / resumed / ended, dock arrived / departed) and alert (the
s2p2 notification codes that mirror the Dreame app's push
notifications).

Each event currently shows TWICE: once as the EventEntity state
change with a generic "detected an event" message (HA's logbook
component bypasses custom describers for entity state changes),
and once as a custom HA bus event with the formatted human message.

To suppress the duplicates, add to your `configuration.yaml`:

```yaml
logbook:
  exclude:
    entities:
      - event.dreame_a2_mower_lifecycle
      - event.dreame_a2_mower_alert
```

The entities stay live (template/automation triggers still work) —
only the duplicate generic logbook lines are filtered.

### Showcase dashboard

Copy `dashboards/mower/dashboard.yaml` to your HA config (e.g.
`/config/dashboards/mower/dashboard.yaml`) and register it in
`configuration.yaml` under `lovelace.dashboards`.

## Cutting over from the legacy

If you ran the legacy `okolbu/ha-dreame-a2-mower-legacy` integration: see
**`docs/cutover.md`** for the full runbook. Greenfield uses the same
on-disk archive paths (`/config/dreame_a2_mower/{sessions,lidar}/`)
so historical session and LiDAR data carry over without migration.

## Documentation

- **`docs/superpowers/specs/2026-04-27-greenfield-integration-design.md`**
  — full spec including the 48-item behavioral parity checklist.
- **`docs/superpowers/plans/`** — phase-by-phase implementation plans
  (F1 through F7).
- **`custom_components/dreame_a2_mower/entity-inventory.yaml`** — the
  authoritative per-entity inventory: read source + verification status
  for every entity and service. Use it to diagnose "I toggled X in HA
  but the app didn't see it".
- **`docs/research/cloud-write-reference.md`** — canonical reference
  for the chunked-batch (SETTINGS / SCHEDULE / AI_HUMAN) and
  routed-action (CFG) cloud surfaces, including the dual-entry
  semantic and propagation lag.
- **`docs/research/g2408-protocol.md`** — MQTT property mappings,
  cloud-map coordinate frame, blob layouts, session-event schema.
- **`docs/research/cloud-map-geometry.md`** — pixel ↔ cloud-frame mm
  transforms, midline reflections, lawn-polygon decoding.
- **`docs/research/webgl-lidar-card-feasibility.md`** — feasibility
  write-up for the bundled WebGL card.
- **`docs/observability.md`** — diagnostic sensors, NOVEL log prefixes,
  `download_diagnostics` schema.
- **`docs/lidar.md`** — user-facing LiDAR guide.
- **`docs/cutover.md`** — legacy → greenfield runbook.
- **`docs/data-policy.md`** — per-field persistent / volatile /
  computed split.
- **`docs/events.md`** — event reference + automation recipes for the
  lifecycle event entity.
- **`docs/multi-map.md`** — multi-map support: active-map detection,
  per-map cameras, replay picker, current limitations.

## Limitations

### Multi-mower support

This integration is tested with a single mower per Dreame account. The
internal architecture (SN-keyed identifiers, sub-devices via `via_device`)
allows multiple mowers under separate config entries, but it has not
been tested. If you have two A2/g2408 mowers, expect rough edges; please
file an issue.

### Time-window entities are read-only

The mowing schedule itself is editable from HA (the `set_schedule_plans`
service + the bundled schedule card). The per-setting time windows shown
as `time.*` entities — DnD, low-speed-at-night, and charging start/end —
are surfaced read-only; change those in the Dreame app and HA picks them
up on the next cloud sync.

## Reporting bugs

`download_diagnostics` (Settings → Devices & Services → Dreame A2
Mower → ⋮ → Download Diagnostics) produces a redacted JSON dump
suitable for attaching to GitHub issues. It includes:

- `state` — current `MowerState` snapshot (every field).
- `cloud_state` / `mqtt_state` — connection, did/uid/host (redacted).
- `novel_observations` — protocol shapes the integration didn't
  recognize.
- `freshness` — per-field last-update timestamps.
- `endpoint_log` — cloud-RPC accept / reject / 80001 outcomes.
- `recent_novel_log_lines` — tail of `[NOVEL/*]` warnings.

Issues: <https://github.com/okolbu/ha-dreame-a2-mower/issues>

## License

MIT — see `LICENSE`.
