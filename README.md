# Dreame A2 Mower — Home Assistant Integration

A Home Assistant integration for the **Dreame A2** robotic lawn mower
(model `dreame.mower.g2408`). Written from scratch for the A2 — **not a
fork** of any upstream vacuum or mower project.

## Status

🟢 **v1.0.0a — release candidate.** All seven phases of the greenfield
rewrite have shipped. The integration covers the spec's 48-item
behavioral parity checklist; live verification is in progress.

| Phase | Scope | Status | Tag |
|---|---|---|---|
| F1 | Foundation (config flow, coordinator, MQTT, lawn_mower) | ✅ | `v0.1.0a*` |
| F2 | Core state (all §2.1 sensors, GPS, base map render) | ✅ | `v0.2.0a*` |
| F3 | Action surface (services, action_mode select) | ✅ | `v0.3.0a*` |
| F4 | Settings (s2.51-derived switches/numbers/selects) | ✅ | `v0.4.0a*` |
| F5 | Session lifecycle (in-progress restore, finalize gate) | ✅ | `v0.5.0a*` |
| F6 | Observability (novel-token registry, diagnostics) | ✅ | `v0.6.0a*` |
| F7 | LiDAR + dashboard polish + cutover | ✅ | `v1.0.0a*` |

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
  `finalize_session`, `replay_session`, `show_lidar_fullscreen`.
- All routed through the cloud RPC `s2.50 aiid=50` envelope (the only
  command path that works on g2408 — direct `action()` returns 80001).

### Settings (cloud + s2.51)
- Switches: rain protection, DnD, low-speed-at-night, custom charging
  window, child lock, anti-theft (lift / off-map / realtime location),
  LED behaviour (standby / working / charging / error).
- Numbers: volume, auto-recharge battery %, resume battery %.
- Times: DnD start/end, low-speed start/end, charging start/end.
- Selects: mowing efficiency, rain-protection resume hours.

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

### Observability
- **`sensor.novel_observations`** — count + attribute list of
  unfamiliar protocol shapes seen this process.
- **`sensor.dreame_a2_mower_data_freshness`** (default-disabled) —
  per-field staleness in seconds.
- **`sensor.api_endpoints_supported`** (default-disabled) — passive
  cloud-RPC accept/reject log.
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
A 7-view Lovelace dashboard at `dashboards/mower/dashboard.yaml`
mirroring the Dreame app's organization: Mower / Mowing Settings /
More Settings / Schedule / LiDAR / Sessions / Diagnostics. Uses only
standard HA cards plus the bundled WebGL LiDAR card.

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
