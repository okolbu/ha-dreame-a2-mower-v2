# Showcase Mower Dashboard — Per-Map UX

**Status:** draft 2026-05-11
**Predecessor:** existing single-file dashboard at `dashboards/mower/dashboard.yaml` (971 lines, 10 views). This redesign reshapes it around Phase 2's per-map entity model.
**Scope:** YAML-only dashboard work + one small integration tweak (expose `current_map_id` attribute on `select.active_map`). No new entity types. Placeholder cards for entities that ship later in Plans 2/3.

## Why

Phase 2 Foundation (shipped 2026-05-10 as v1.0.4a1) reshaped the entity surface so per-map entities live on their map sub-devices with stable per-map semantics. The existing dashboard predates this; its per-map cards bind to old `entry_id`-keyed entities and have no map context awareness — settings on the Mowing Settings page read whichever map's settings the mower is currently following, with no UI indication of which map that is.

The showcase dashboard should:

1. Mirror the Dreame app's UX as closely as practical (the app's "main screen + map selector + per-map subscreens" pattern translates well to HA views).
2. Take advantage of the per-map entity model where the app can't (e.g., per-map LiDAR is now distinct, not a flipping overlay).
3. Be transparent YAML — readable enough to copy-edit by hand, without depending on uncommon custom cards.
4. Survive future map additions (2 → 3+ maps) with copy-paste, not refactor.

## Goal

A multi-view Lovelace dashboard at `dashboards/mower/dashboard.yaml` where:

- One **Map Selector** view is the canonical "switch active map" surface (mirrors the app's map-list screen).
- Five **per-map flipping** views (Mower, Settings & Zones, Schedule, LiDAR, WiFi Coverage) show only the active map's content, swapping when active map changes.
- One **Sessions** view shows a cross-map flat list with the replay map bound to the selected session (independent of active map).
- Mower-level singular views (More Settings, Diagnostics, Tools, Photo Privacy) unchanged in purpose.
- Every per-map view has a header **thumbnail of the active map's base snapshot** so the user always knows which map they're viewing.

## Non-goals

- New entity types (mowing-type select, live video, etc.) — those land in Plan 2; placeholder cards reserve their slots.
- Schedule editing (Plan 2).
- Custom-card dependencies beyond what's already in use (`dreame-a2-lidar-card` is in; `tabbed-card` etc. are out).
- A `tools/generate_dashboard.py` codegen step — hand-written YAML for transparency.
- Multi-mower dashboard layout (one mower per HA config entry assumption stands).

## Prerequisite — integration tweak

Add a `current_map_id` integer attribute on `DreameA2ActiveMapSelect`, exposing `coordinator._active_map_id`. Conditional cards key on this attribute (stable int) instead of the select's state (a user-renameable friendly name).

```python
# select.py — inside DreameA2ActiveMapSelect
@property
def extra_state_attributes(self) -> dict[str, Any]:
    return {"current_map_id": self.coordinator._active_map_id}
```

This becomes a one-task prerequisite in the implementation plan.

## Mapping to the app

| App screen | Dashboard view | Notes |
|---|---|---|
| Main (map + mode + actions) | **Mower** | Active-map's snapshot, live trail, action buttons, mowing-mode picker |
| Map list (the switcher screen) | **Map Selector** | Grid of all maps; tapping sets active |
| Mowing Settings (General/Custom tabs) | **Settings & Zones** | General Mode in-line; Custom Mode panel (Plan 2 service-call form) |
| Schedule | **Schedule** | Read-only today; editing in Plan 2 |
| LiDAR | **LiDAR** | 3D point cloud per-map (already in T13) |
| Work Logs | **Sessions** | Flat list cross-map; replay map follows picker (matches app behavior — single list, but rendered map is correct per session's `map_id`) |
| Settings → More | **More Settings** | Global only ([Functions], [Security], [General]); the three per-map exceptions moved into Settings & Zones |
| — | **WiFi Coverage** | HA bonus — heatmap overlaid on active map's base, with opacity slider |
| — | **Diagnostics**, **Tools**, **Photo Privacy** | HA-specific, unchanged |

## View architecture

### Per-map flipping views (5)

Each renders only the **active map's** content via `conditional` cards keyed on `state_attr('select.dreame_a2_mower_active_map', 'current_map_id')`. One conditional block per `map_id`. For the live mower (2 maps), each per-map card renders as exactly two `conditional` blocks (only one shown at a time).

Header on every per-map view is a horizontal-stack:

```yaml
- type: horizontal-stack
  cards:
    - type: conditional
      conditions:
        - condition: state
          entity: select.dreame_a2_mower_active_map
          attribute: current_map_id
          state: 0
      card:
        type: picture-entity
        entity: camera.dreame_a2_mower_map_0_map
        camera_view: live
        aspect_ratio: 16:9
        show_state: false
    - type: conditional
      conditions:
        - condition: state
          entity: select.dreame_a2_mower_active_map
          attribute: current_map_id
          state: 1
      card:
        type: picture-entity
        entity: camera.dreame_a2_mower_map_1_map
        camera_view: live
        aspect_ratio: 16:9
        show_state: false
    - type: entity
      entity: select.dreame_a2_mower_active_map
      name: Active map
      tap_action:
        action: navigate
        navigation_path: /dashboards/mower/maps
```

Tap on the active-map entity card navigates to the Map Selector view.

### 1. Mower view

- Header: thumbnail + active-map label
- Hero: large `picture-entity` of the active map's snapshot (live mode — animates with live trail / mower position)
- Below: `entities` card with mower state, battery, error, current zone, current session sqm, current task type
- Action row: horizontal-stack of buttons
  - `button.dreame_a2_mower_start`
  - `button.dreame_a2_mower_stop`
  - `button.dreame_a2_mower_pause`
  - `button.dreame_a2_mower_return`
  - `button.dreame_a2_mower_find_my_robot` *(Plan 3 placeholder)*
  - `button.dreame_a2_mower_head_to_maintenance_point` *(Plan 2 placeholder)*
- Below actions: per-map mowing-mode picker *(Plan 2 placeholder — `select.dreame_a2_mower_map_N_mowing_type`)*

### 2. Settings & Zones view

- Header: thumbnail + active-map label
- General Mode card (`entities`): the 7 settings switches that exist today, for the active map
- Custom Mode card *(Plan 2 placeholder)*: `sensor.dreame_a2_mower_map_N_custom_mode_overrides` + button row to launch service-call dialogs
- Zone Editor: `select.dreame_a2_mower_map_N_zone_target/spot_target/edge_target` entities
- Pathway Obstacle Avoidance *(Plan 2 placeholder)*
- Ignore Obstacle Zones *(Plan 2 placeholder)*
- Maintenance Points *(Plan 2 placeholder — picture-elements with positioned pins over the active map snapshot)*

### 3. Schedule view

- Header: thumbnail + active-map label
- Schedule slots panel (read-only `sensor.schedule_count` + `markdown` rendering slot details from attributes)
- "Schedule editing not yet supported on g2408" footnote
- Editing UI ships in Plan 2

### 4. LiDAR view

- Header: thumbnail + active-map label
- `custom:dreame-a2-lidar-card` for the active map, configured with `map_id: 0` or `map_id: 1` via conditional swap (one card per map_id, only one shown)
- `input_number.dreame_a2_mower_lidar_tilt` (HA helper) — controls the WebGL card's tilt; the card JS already supports a config field for this if available, otherwise a markdown card explaining the helper is decoration-only

### 5. WiFi Coverage view

- Header: thumbnail + active-map label
- Hero: `picture-elements` card overlaying the heatmap on the active map's base snapshot. Two elements: bottom is `camera.dreame_a2_mower_map_N_map`, top is `camera.dreame_a2_mower_map_N_wifi_map` with opacity styled via `card-mod`.
- `input_number.dreame_a2_mower_wifi_overlay_opacity` (0-100, step 5) — bound to the heatmap element's `style.opacity` as `value/100`.
- Refresh button: `button.dreame_a2_mower_map_N_request_wifi_map` (the per-map refresh button after T11)

`input_number` opacity helper requires a one-line HA `configuration.yaml` snippet (or UI-helper creation) shown in the dashboard's setup notes.

### 6. Map Selector view

Mirrors the app's map-list screen:

```yaml
- title: Map Selector
  path: maps
  cards:
    - type: heading
      heading: "Pick the active map"
    - type: grid
      square: false
      columns: 2
      cards:
        - type: picture-entity
          entity: camera.dreame_a2_mower_map_0_map
          name: "Map 1"
          show_state: false
          tap_action:
            action: call-service
            service: select.select_option
            data:
              entity_id: select.dreame_a2_mower_active_map
              option: "Map 1"
        - type: picture-entity
          entity: camera.dreame_a2_mower_map_1_map
          name: "Map 2"
          show_state: false
          tap_action:
            action: call-service
            service: select.select_option
            data:
              entity_id: select.dreame_a2_mower_active_map
              option: "Map 2"
    - type: entities
      title: "Current active map"
      entities:
        - select.dreame_a2_mower_active_map
```

A future enhancement could highlight the active map in the grid (via `card-mod` border styling keyed on `current_map_id`), but base showcase ships without it.

### 7. Sessions view

- Header: small markdown card explaining "All sessions, across both maps. The map shown below is the one this session was recorded on."
- Session picker: `select.dreame_a2_mower_replay_session` (existing, cross-map, sorted recent-first with `[Map N]` prefix)
- Replay map: `camera.dreame_a2_mower_work_log` — bound to the picker's selection; renders the session's map_id geometry + trail (no active-map dependency)
- Session stats: `entities` card showing duration, sqm, end-reason, etc.

### 8. More Settings view

Same as today's "More Settings" minus the per-map exceptions:

- [Functions]: Rain Protection, Frost Protection, Do Not Disturb, Low-speed at Night, Navigation Path, Charging, Start from Stop Point, Auto Recharge, Capture AI Photos, Light (most are Plan 3 placeholders)
- [Security]: Anti-theft Alarm, Human Presence Detection, Child Lock, Change PIN Code (all Plan 3 placeholders)
- [General]: Time Zone, Switch Unit, Robot Voice (exists), Notifications

Per-map items removed: Head to Maintenance Point (in Mower view's action row + per-map points in Settings & Zones), Pathway Obstacle Avoidance (in Settings & Zones), Ignore Obstacle Zones (in Settings & Zones).

### 9. Diagnostics view

Unchanged: firmware, SN, MAC, MQTT connection, novel-log buffer, etc.

### 10. Tools view

Unchanged: refresh-cloud, finalize-session, archive-recovery, refresh-wifi-map etc.

### 11. Photo Privacy Policy view

Unchanged.

## Placeholder card pattern

Any card referencing an entity that doesn't exist yet (Plan 2/3 deliverables) ships as a `markdown` card with a clear visual cue and a one-line description of what's expected. Example:

```yaml
- type: markdown
  content: |
    ### 🚧 Mowing mode (Plan 2)

    `select.dreame_a2_mower_map_N_mowing_type` — picker for all-area / edger /
    zone / spot / manual mowing. Lands when the per-map mowing-type select
    entity is implemented.
```

This keeps every per-map view's structure visible end-to-end even before Plans 2/3 land. When a real entity ships, the markdown card is swapped for the real entity card in a one-line YAML edit.

## Per-map flipping mechanism

Two patterns coexist:

**Pattern A — Conditional cards** (preferred, used for everything):

```yaml
- type: conditional
  conditions:
    - condition: state
      entity: select.dreame_a2_mower_active_map
      attribute: current_map_id
      state: 0
  card:
    # card for map 0
- type: conditional
  conditions:
    - condition: state
      entity: select.dreame_a2_mower_active_map
      attribute: current_map_id
      state: 1
  card:
    # card for map 1
```

For a 3rd map: copy the block and edit the state + entity refs. No template logic, no helpers, transparent.

**Pattern B — Sessions view's selection-bound map**: the replay camera entity (`camera.dreame_a2_mower_work_log`) already swaps its rendered map based on `select.dreame_a2_mower_replay_session`. No dashboard logic needed — coordinator handles the swap server-side via `_render_map_id`.

## HA helpers required

The dashboard depends on three user-created HA helpers (added once via UI → Settings → Devices → Helpers, or in `configuration.yaml`):

```yaml
input_number:
  dreame_a2_mower_wifi_overlay_opacity:
    name: WiFi heatmap opacity
    min: 0
    max: 100
    step: 5
    initial: 50
    unit_of_measurement: "%"
  dreame_a2_mower_lidar_tilt:
    name: LiDAR view tilt
    min: 0
    max: 90
    step: 5
    initial: 30
    unit_of_measurement: "°"
```

The dashboard's setup notes (a markdown card on the Tools view or a top-level README section) list these.

## Build order

Suggested implementation plan order:

1. Integration prerequisite — `current_map_id` attribute on `DreameA2ActiveMapSelect` (one task)
2. Per-map view header template — thumbnail + active-map indicator + nav-to-Maps (reusable header used across 5 per-map views)
3. Map Selector view
4. Mower view
5. Settings & Zones view (with Plan 2 placeholders)
6. LiDAR view (uses existing `dreame-a2-lidar-card`)
7. WiFi Coverage view (depends on `input_number` opacity helper)
8. Schedule view (read-only)
9. Sessions view (mostly an adapt of existing Work Logs view)
10. More Settings view (drop per-map exceptions from current; relocate to Settings & Zones)
11. Diagnostics, Tools, Photo Privacy — copy-edit from current
12. SCP to live HA; verify each view loads (per the user-memory note about `createErrorCardElement` for diagnosing blank views)

Total: ~12 tasks. Plan 2/3 entities are referenced but their dashboard cards land as markdown placeholders today and get swapped to real entity cards as the Plans 2/3 work lands.

## Open questions

1. **`card-mod` dependency for WiFi overlay opacity binding.** Standard Lovelace `picture-elements` doesn't natively bind `style.opacity` to an entity state. Options: (a) require `card-mod` (a very common custom card already used by many HA users), (b) use a Jinja-template-rendered HTML string in a `markdown` card (ugly but no dep), (c) build a small custom card in `www/` that does the binding (heaviest). **Recommend (a)** unless the user objects — `card-mod` is widely deployed.

2. **Highlight active map in the Map Selector grid.** Pure-YAML can't draw a border around just the active card. Options: (a) `card-mod` styling on the picture-entity, (b) accept "active map is shown in the entities card below," (c) add a small `markdown` overlay element via `picture-elements`. **Recommend (b)** for v1 — adds zero dependencies.

3. **Mowing-mode picker location (Plan 2).** Today's plan places it on the Mower view's main action row. Alternative: as a setting on Settings & Zones (since it's a per-map config that affects "what Start does"). **Recommend Mower view** — it's an operational choice the user makes before pressing Start.

4. **Schedule view editing — surface a service-call dialog or wait for Plan 2 entities?** Today the schedule blob is read-only on g2408 (BT-only writes per the existing docstring). The dashboard can ship read-only and the editing UI is a Plan 2 deliverable once the data-layer per-map slots land. **Recommend ship read-only now.**

5. **LiDAR view tilt control — is `dreame-a2-lidar-card.js` actually wired to read a tilt config?** If not, the `input_number.lidar_tilt` is decorative. Need to verify; if it's not wired today, drop the helper and skip the tilt control until the card supports it.

## Out of scope (filed as TODOs)

- Tab-style view-within-view (HA's native views are flat; no nested tabs without custom cards).
- Touch-optimized mobile layout (HA's Lovelace handles responsive sizing reasonably with `grid` and `vertical-stack`; explicit mobile breakpoints are Plan 4 if at all).
- Active-map highlight border on the Map Selector grid (open question #2 above).
- Real-time mini-thumbnails of other maps on the Mower view (user explicitly dropped earlier — Map Selector view replaces this need).
- Dashboard generation script (`tools/generate_dashboard.py`) — hand-written for transparency.
- Map renaming UI (the user renames in the Dreame app; HA picks up the new name via `MapData.name`).
