# Dashboard Cleanup — Design Spec

> **Status — DRAFT.** Decisions consolidated 2026-05-13 from Q&A. See
> `/data/claude/homeassistant/cleanups.txt` for the raw item list.

## Goal

Clean up the 11-tab Mower dashboard so each tab has clear ownership: one
active-map switcher (Maps tab only), state-aware action buttons on the
Mower tab, base maps with read-only zone overlays on Settings & Zones,
weekly schedule visualisation, calendar view of archived sessions, and a
fuller Diagnostics tab. Surface every state-machine entity added in the
v1.0.8 series. Investigate and fix the WiFi-heatmap initial-render bug.

## Architecture

Two work surfaces:

1. **Integration code** (Python in `custom_components/dreame_a2_mower/`):
   small additions — one new sensor (cloud device-id), one new
   calendar-entity domain, one new sensor field (`session_distance_m`
   persisted on archive), one new renderer pass (maintenance points +
   spots on base map), one new map-action source (per-map "Select"
   button helper). Plus the WiFi-heatmap initial-render fix.
2. **Lovelace YAML** (`dashboards/mower/dashboard.yaml`): the bulk of
   the work — rename cards, replace per-tab map selectors with
   info-only cards, build state-conditional button grids on the Mower
   tab, add base-map cards to Settings & Zones, dig up & adapt the
   weekly schedule view, add the calendar card to Sessions.

The integration changes are scoped tightly — the dashboard is the main
deliverable. No state machine changes; v1.0.8a8 already covers the
charging→at-dock invariant brought up during brainstorming.

## Per-tab design

### Mower tab

- **Title card:** Rename "Start mowing" → "Mowing target". Remove the
  per-map duplicate dropdowns. Show a SINGLE dropdown bound to the
  active map's zone/spot/edge picker. (P2-4's unified picker exists at
  the entity level but isn't wired into this tab the way the user
  expected — wire it in.)
- **State card:** Surface the v1.0.8 state-machine entities
  (`current_activity`, `location`, `positioning_health`,
  `mqtt_connectivity`, `charging_status`). Group with existing battery,
  area_mowed, session_distance.
- **Action buttons (state-aware):** Conditional Lovelace cards keyed off
  `current_activity` + `location` + `charging`. Button set by state:
  - **Charging in mow:** Continue · End · Find
  - **Charging not in mow:** Start · Find
  - **In dock, not charging:** Start · Recharge · Find
  - **Mowing / cruising / mapping / returning:** Pause · End · Recharge · Find
  - **Paused in any session:** Continue · End · Recharge · Find
  - **Stopped on lawn idle** (error / maintenance-point arrival): Recharge · Find
  - **Find** is always shown. Single "Recharge" label everywhere.
- **Map card:** Live base-map renderer with trails + ALL overlays
  (exclusion, ignore-obstacle, spots, maintenance points). The
  maintenance-point overlay is new — a light-brown circle 2× the
  blue-dock-circle size with an "M" glyph.
- **GPS map card:** Comment out the existing card, keep in source.
  Replace with markdown placeholder "GPS tracking — work in progress".
- **Head-to-Maintenance-Point card:** Same treatment — markdown
  placeholder.

### Map Selector tab

- **Tile rows:** Tap-to-zoom stays. Add a **Select Map N** button below
  each tile. The currently-selected tile/button is visually highlighted
  (border colour + button variant).
- **Render mode:** Base-map only — no live trails on this tab.
- **Map 2 clipping fix:** Either set `aspect_ratio: none` on the
  picture-card so it sizes to the image, or pre-compute the actual
  per-map bbox and stamp it as `aspect_ratio: WxH` per card. Pick
  whichever holds up across both maps without scrollbars.
- **Notification on mid-mow switch:** the integration's
  `select.active_map_select` already refuses with a
  `persistent_notification`. Confirm the new Select buttons route
  through that same select entity so the guard fires unchanged.

### Settings & Zones tab

- **Add a base-map card** (renderer same as Mower tab, NO trails) with
  ALL read-only overlays: exclusion, ignore-obstacle, spots,
  maintenance points.
- **Per-zone-type list cards** for the active map:
  - Exclusion zones (count + per-zone details)
  - Ignore-obstacle zones (same)
  - Spots (same)
  - Maintenance points (same — already exists)
- **Drop the in-tab "active map" selector** — replace with an
  info-only card showing the currently-selected map name. Switching
  happens on the Map Selector tab.

### Schedule tab

- **Weekly grid view:** Dig up the prior implementation from git
  history (likely in `dashboard.pre-phase2.yaml.bak` or earlier
  commits), port to current entity names.
- **Per-slot list:** Each schedule slot shown with mowing-mode
  (zone/edge/spot/all), start time, days-of-week. Slots that share an
  underlying schedule item should visually group.
- **Active map only:** Use the unified `select.active_map` to filter
  which map's schedule entities are displayed.
- **Device-wide time windows section:** Unchanged.

### LiDAR tab

- No code changes (user confirmed acceptable).

### WiFi Coverage tab

- **Bug fix:** Camera doesn't render until the dropdown is changed.
  Investigation hypothesis: the camera entity's `async_added_to_hass`
  doesn't trigger an initial render against the default input_select
  value. Likely fix is in `camera.py` — force a refresh on entity
  setup tied to the current input_select state.

### Sessions tab

- **Calendar:** New `calendar.dreame_a2_mower_sessions` entity domain
  exposing each archived session as a calendar event (start/end times,
  summary = "Mow {map_name} – {area} m²", description = additional
  metadata). Lovelace calendar card on the tab supports
  agenda/day/week/month views natively.
- **Maintenance-point overlay:** Same renderer addition as the Mower
  and Settings tabs; the session-replay map uses the same renderer so
  it gets it for free.
- **Session metadata expansion:**
  - **New:** persist `session_distance_m` on archive (already
    computed live).
  - **Defer:** trigger source (scheduled vs manual), completion code
    (why incomplete). These need additional firmware signals or a
    longer reverse-engineering pass.
- **Entity review:** audit `sensor.py` for any session-related entities
  not yet on the dashboard. Add to the Sessions tab where they belong.

### More Settings tab

- **Inventory + populate:** Walk through every existing setting entity
  (read-only and read-write). Place each on a card grouped by
  function (mowing behaviour, edge mowing, AI/obstacles, charging,
  notifications, etc.). Read-only entities show their value but are
  not interactive; flag with a "(read-only)" subtitle where useful.
- **No new write surfaces** — the map-edit write path is unknown (see
  `docs/research/map-edit-write-todo.md`).

### Diagnostics tab

- **Add:**
  - Cloud device-id sensor (`BM169439`-style; surfaces
    `cloud.device_id` from the integration).
  - API endpoint DNS (`eu.iot.dreame.tech:19973`) — constant from
    `const.py`, exposed as a sensor.
  - Integration version — from `manifest.json`.
  - Note: "Cellular: WiFi-only on g2408" (no cellular radio).
- **Confirmed-present already** (don't re-do):
  - Firmware version
  - Serial number
  - MAC address
- **Confirmed not available** (note on tab):
  - IP address (Dreame cloud doesn't expose)
  - MQTT / API version (not surfaced by cloud)
- **Defer:** log-warnings sensor (polling overhead not worth it).

### Tools tab

- Inventory all "tool-style" entities (refresh-wifi-archive button,
  dump-cloud-state button, find-mower, force-reload, etc.). Place each
  on a card with a short description.

### Photo Privacy tab

- **Privacy policy text:** Surface the Dreame privacy policy in a
  markdown card. Source the text from `const.py` / `docs/` (locate
  during implementation).
- **AI Photo toggle:** Show the existing `switch.ai_human` entity with
  a markdown caveat: "Capture only works if you've accepted the
  privacy policy in the Dreame app first."

## Components

### Integration code

| File | Change |
|---|---|
| `custom_components/dreame_a2_mower/sensor.py` | New: `DreameA2CloudDeviceIdSensor`, `DreameA2ApiEndpointSensor`, `DreameA2IntegrationVersionSensor`. Audit existing for session-tab gaps. |
| `custom_components/dreame_a2_mower/calendar.py` (new) | `DreameA2SessionCalendar` entity — exposes archived sessions as calendar events. |
| `custom_components/dreame_a2_mower/session_archive.py` (or equivalent) | Add `session_distance_m` field; persist on archive write. |
| `custom_components/dreame_a2_mower/map_render.py` | Add maintenance-point glyphs (light-brown 2×-dock-circle "M"); add spots if not already rendered. |
| `custom_components/dreame_a2_mower/camera.py` | Force initial render on `async_added_to_hass` to fix WiFi-heatmap blank-on-load bug. |
| `custom_components/dreame_a2_mower/manifest.json` | (no change — pulled by IntegrationVersionSensor) |

### Dashboard YAML

Single file: `dashboards/mower/dashboard.yaml`. All edits in place;
prior view kept in `dashboard.pre-phase2.yaml.bak`. No new files.

## Data flow

- Active-map selection: tap-on-tile (zoom) and Select-button (switch)
  both route through `select.active_map_select`. The guard for
  "refuse during mowing" already lives there and surfaces a
  `persistent_notification`.
- Calendar events: `DreameA2SessionCalendar.async_get_events()` reads
  archived sessions from disk via the existing session-archive store,
  returns them as `CalendarEvent` objects.
- Maintenance-point overlay: `map_render.render_base_map()` reads
  `MapData.maintenance_points`, draws each at its (x_mm, y_mm) in
  renderer coords.

## Testing

- **Integration code:** unit tests for each new sensor's `native_value`
  resolution; round-trip test for the calendar entity (mock archive,
  assert events); renderer test for maintenance-point glyph (pixel
  presence on a known-good fixture).
- **WiFi camera fix:** test that `async_added_to_hass` triggers
  `async_write_ha_state` after setting up against a non-empty
  input_select default.
- **Dashboard YAML:** lint via `yamllint`. Manual smoke test in HA UI
  (tabs render, conditional buttons appear in the right state).

## Out of scope

- Map-edit write surface (separate research; tracked in
  `docs/research/map-edit-write-todo.md`).
- Cellular signal sensors (not present on g2408).
- IP-address sensor (not exposed by Dreame cloud).
- Live-stream from HA log of warnings/errors (polling overhead).
- Trigger-source / completion-code metadata in archive (defer).

## Risks

- **Conditional card visibility** — the action-button state table has
  six rows. Each row gets its own conditional card. If the conditions
  overlap (multiple cards visible at once), the buttons grid will look
  wrong. Need careful predicate ordering and a default fallback.
- **Calendar entity scope** — exposing archives as calendar events is
  one-way and read-only. The user might later ask for editing — that's
  a much bigger change.
- **Maintenance-point glyph collision** — if a maintenance point sits
  on top of the docking-station circle, the overlay can become
  unreadable. Pick a glyph offset / draw order that avoids this.
