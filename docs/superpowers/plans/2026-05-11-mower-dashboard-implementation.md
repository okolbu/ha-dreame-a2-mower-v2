# Showcase Mower Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the showcase dashboard at `dashboards/mower/dashboard.yaml` around Phase 2's per-map entity model — 5 per-map flipping views (Mower, Settings & Zones, Schedule, LiDAR, WiFi Coverage), 1 Map Selector swap surface, 1 cross-map Sessions view, plus 4 mower-level singular views (More Settings, Diagnostics, Tools, Photo Privacy).

**Architecture:** Hand-written Lovelace YAML. Per-map flipping via `conditional` cards keyed on a new `current_map_id` integer attribute on `DreameA2ActiveMapSelect` (one-line integration tweak, stable across map renames). Plan 2/3 entities ship as labeled `markdown` placeholder cards. WiFi overlay uses `picture-elements` + `card-mod` opacity binding to an `input_number` helper.

**Tech Stack:** Home Assistant Lovelace YAML, Python 3.13 (the integration tweak), pytest. One custom-card dependency added: `card-mod` (widely-deployed HACS frontend card). No new third-party deps for the integration.

**Spec:** [`docs/superpowers/specs/2026-05-11-mower-dashboard-design.md`](../specs/2026-05-11-mower-dashboard-design.md)

**Live HA paths:**
- Repo source: `/data/claude/homeassistant/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml`
- HA box live: `/config/dashboards/mower/dashboard.yaml` (SCP'd manually; HACS does NOT auto-deploy dashboard yaml)

**Build order rationale:** Task 1 ships the integration prerequisite (must release before dashboard can rely on it). Tasks 2-13 build the dashboard incrementally; each view-task is self-contained YAML + SCP + smoke-test. Task 14 is the final commit + push.

---

## File Structure

**Files to modify (integration):**
- `custom_components/dreame_a2_mower/select.py` — add `extra_state_attributes` to `DreameA2ActiveMapSelect`
- `tests/integration/test_active_map_select.py` — extend with attribute test

**Files to modify (dashboard, single source file):**
- `dashboards/mower/dashboard.yaml` — rewrite

**Files referenced (read-only):**
- Existing `dashboards/mower/dashboard.yaml` — source of current entity refs and view layouts to adapt

**Files to create (helpers — documented but user-installed):**
- `docs/superpowers/helpers/dreame-a2-helpers.yaml` — example `input_number` configuration that the user copies into their `configuration.yaml`

---

## Conventions

- **Per-task workflow:** for YAML tasks, the cycle is: write YAML → `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"` → commit → user SCP's to HA → user reloads dashboard. The implementer commits; the SCP+reload step is documented but executed by the user (or the final smoke-test task does it from this session).
- **Conditional pattern (used 5+ times):** ALL per-map flipping uses this exact shape, copy-paste it. Do NOT use template entities or Jinja in the dashboard — the spec mandates hand-written transparent YAML.

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

- **Placeholder pattern (used for Plan 2/3 entities not yet built):**

  ```yaml
  - type: markdown
    content: |
      ### 🚧 Mowing mode (Plan 2)

      `select.dreame_a2_mower_map_N_mowing_type` — picker for all-area / edger /
      zone / spot / manual mowing. Lands when the per-map mowing-type select
      entity is implemented.
  ```

- **Header on every per-map view** (Tasks 4-9 reuse this verbatim; Task 3 defines it).

- **Each view-task commits standalone.** YAML is added incrementally so a partial result still validates and renders.

---

## Task 1: `current_map_id` attribute on `DreameA2ActiveMapSelect`

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py` — find `class DreameA2ActiveMapSelect` (around line 1212)
- Test: `tests/integration/test_active_map_select.py` (extend existing)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_active_map_select.py`:

```python
def test_active_map_select_exposes_current_map_id_attribute(
    coordinator_with_two_maps,
):
    """Dashboard `conditional` cards key off attributes.current_map_id.

    The select's state is the user-renameable friendly name; the
    attribute is a stable integer that survives renames.
    """
    coord = coordinator_with_two_maps
    coord._active_map_id = 1

    from custom_components.dreame_a2_mower.select import (
        DreameA2ActiveMapSelect,
    )
    e = DreameA2ActiveMapSelect(coord)
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] == 1

    coord._active_map_id = 0
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] == 0

    coord._active_map_id = None
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_active_map_select.py::test_active_map_select_exposes_current_map_id_attribute -v`
Expected: FAIL with `AttributeError` or `KeyError: 'current_map_id'`.

- [ ] **Step 3: Implement the attribute**

In `custom_components/dreame_a2_mower/select.py`, inside `class DreameA2ActiveMapSelect`, add:

```python
@property
def extra_state_attributes(self) -> dict[str, Any]:
    """Expose `current_map_id` for dashboard conditional cards.

    Cards key off this stable integer rather than the select's state
    (the friendly name), so the dashboard survives the user renaming
    a map in the Dreame app.
    """
    return {"current_map_id": self.coordinator._active_map_id}
```

If `DreameA2ActiveMapSelect` already defines `extra_state_attributes`, merge the `"current_map_id"` key into the existing return dict.

If `Any` isn't already imported, add to the file's imports: `from typing import Any`.

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/integration/test_active_map_select.py -v`
Expected: PASS, all tests (existing + new).

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -x`
Expected: PASS clean.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/select.py tests/integration/test_active_map_select.py
git commit -m "feat(select): expose current_map_id attribute for dashboard conditionals"
```

- [ ] **Step 7: Push + cut release**

Per the user-memory convention (`feedback_subagent_release_pipeline.md`):

```bash
git push origin main
./tools/release.sh
```

The release.sh will auto-bump (likely `1.0.4a2`). Capture the new version from the script's output.

The dashboard's `conditional` cards reference this attribute, so the integration must be installed via HACS BEFORE the new dashboard is SCP'd. If `release.sh` fails or HACS doesn't refresh, the dashboard will not function — surface this and STOP.

---

## Task 2: Back up existing dashboard + scaffold new file

**Files:**
- Backup: `dashboards/mower/dashboard.pre-phase2.yaml.bak` (snapshot of current)
- Rewrite: `dashboards/mower/dashboard.yaml` (scaffolded skeleton, populated in subsequent tasks)

- [ ] **Step 1: Snapshot the existing dashboard**

```bash
cp dashboards/mower/dashboard.yaml dashboards/mower/dashboard.pre-phase2.yaml.bak
```

This preserves the pre-rewrite version on disk and in git so subsequent task-tasks can reference it (especially Tasks 10-12 which adapt views, not rewrite them).

- [ ] **Step 2: Scaffold the new `dashboard.yaml`**

Write the file with all 11 view headers and empty `cards:` arrays. Tasks 3-12 fill in the cards.

```yaml
# Dreame A2 Mower — showcase dashboard
# Generated 2026-05-11 (Phase 2 Foundation).
#
# Per-map flipping uses `select.dreame_a2_mower_active_map`'s
# `current_map_id` attribute (added in Task 1 of this plan, released
# alongside v1.0.4a2 of the integration).
#
# Required helpers (add via Settings → Devices → Helpers, or copy
# `docs/superpowers/helpers/dreame-a2-helpers.yaml` into configuration.yaml):
#   - input_number.dreame_a2_mower_wifi_overlay_opacity
#   - input_number.dreame_a2_mower_lidar_tilt
#
# Required custom cards (install via HACS Frontend):
#   - card-mod      (for WiFi overlay opacity binding)
#   - dreame-a2-lidar-card  (bundled with the integration)
#
# Map count is 2 (live mower). Adding a 3rd map: copy any
# `conditional` block, change the state value to 2, and update the
# entity references from `_map_1_` to `_map_2_`.

title: Dreame A2 Mower
views:
  - title: Mower
    path: mower
    icon: mdi:robot-mower-outline
    cards: []  # Task 4

  - title: Map Selector
    path: maps
    icon: mdi:map-marker-multiple
    cards: []  # Task 5

  - title: Settings & Zones
    path: settings-zones
    icon: mdi:tune
    cards: []  # Task 6

  - title: Schedule
    path: schedule
    icon: mdi:calendar-clock
    cards: []  # Task 9

  - title: LiDAR
    path: lidar
    icon: mdi:radar
    cards: []  # Task 7

  - title: WiFi Coverage
    path: wifi
    icon: mdi:wifi
    cards: []  # Task 8

  - title: Sessions
    path: sessions
    icon: mdi:history
    cards: []  # Task 10

  - title: More Settings
    path: more-settings
    icon: mdi:cog
    cards: []  # Task 11

  - title: Diagnostics
    path: diagnostics
    icon: mdi:wrench
    cards: []  # Task 12

  - title: Tools
    path: tools
    icon: mdi:tools
    cards: []  # Task 12

  - title: Photo Privacy
    path: privacy
    icon: mdi:shield-account
    cards: []  # Task 12
```

- [ ] **Step 3: Validate YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: no output (parse OK).

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.pre-phase2.yaml.bak dashboards/mower/dashboard.yaml
git commit -m "dashboard: scaffold 11-view skeleton; backup pre-phase2 yaml"
```

---

## Task 3: Per-map view header snippet (defined as anchor reference)

YAML supports `&anchor` / `*alias` for DRY. We define the per-map header once and alias it from each per-map view. This keeps Tasks 4, 6, 7, 8, 9 from each duplicating ~25 lines.

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — add a top-level `_anchors:` section (Lovelace ignores keys it doesn't recognize, so this is safe)

- [ ] **Step 1: Add the anchor block at the top of the file (after the comment header, before `title:`)**

```yaml
# Per-map view header: thumbnail of the active map's base snapshot
# plus an entity card linking to the Map Selector view. Anchored so
# the 5 per-map views can `<<: *per_map_header` it without duplication.
_per_map_header: &per_map_header
  type: horizontal-stack
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
        name: "Map 1"
        camera_view: live
        show_state: false
        aspect_ratio: 16:9
    - type: conditional
      conditions:
        - condition: state
          entity: select.dreame_a2_mower_active_map
          attribute: current_map_id
          state: 1
      card:
        type: picture-entity
        entity: camera.dreame_a2_mower_map_1_map
        name: "Map 2"
        camera_view: live
        show_state: false
        aspect_ratio: 16:9
    - type: entities
      title: Active map
      show_header_toggle: false
      entities:
        - entity: select.dreame_a2_mower_active_map
          name: Switch
```

YAML anchors work at the document level. The `_per_map_header:` key is at the same indent level as `title:` and `views:`. HA's Lovelace parser ignores unknown top-level keys, so this is a legal location.

For each subsequent per-map view-task (4, 6, 7, 8, 9), the FIRST card in the view's `cards:` array will be `*per_map_header`.

- [ ] **Step 2: Validate YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean parse.

- [ ] **Step 3: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: define per-map header anchor for reuse across 5 views"
```

---

## Task 4: Mower view content

**Files:** `dashboards/mower/dashboard.yaml` — populate the `Mower` view's `cards:` array.

The Mower view is the most-trafficked. Header + main map (large) + state + action row + per-map mowing-mode placeholder.

- [ ] **Step 1: Replace the Mower view's `cards: []` with the populated content**

```yaml
  - title: Mower
    path: mower
    icon: mdi:robot-mower-outline
    cards:
      # Header: thumbnail + nav to Map Selector
      - *per_map_header

      # PIN-required emergency-stop banner — only visible when the mower
      # is locked out pending PIN entry on the device LCD.
      - type: conditional
        conditions:
          - entity: binary_sensor.dreame_a2_mower_emergency_stop_activated
            state: "on"
        card:
          type: markdown
          content: |
            ## ⚠️ Emergency stop activated
            Enter the PIN code on the robot to unlock it. The mower
            will not mow until the PIN is accepted.

      # Hero: live map for the active map. Live trail overlays via the
      # camera entity's server-side render.
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 0
        card:
          type: picture-entity
          entity: camera.dreame_a2_mower_map_0_map
          name: Live Map
          camera_view: live
          show_state: false
          aspect_ratio: 637x717
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 1
        card:
          type: picture-entity
          entity: camera.dreame_a2_mower_map_1_map
          name: Live Map
          camera_view: live
          show_state: false
          aspect_ratio: 637x717

      # State + sensors
      - type: entities
        title: State
        entities:
          - entity: lawn_mower.dreame_a2_mower
          - entity: sensor.dreame_a2_mower_battery
          - entity: sensor.dreame_a2_mower_charging_status
          - entity: binary_sensor.dreame_a2_mower_mower_in_dock
            name: In dock
          - entity: binary_sensor.dreame_a2_mower_obstacle_detected
          - entity: binary_sensor.dreame_a2_mower_rain_protection_active
          - entity: sensor.dreame_a2_mower_active_selection
          - entity: sensor.dreame_a2_mower_session_area_mowed_sqm
            name: Session area mowed (m²)

      # Action row — buttons that operate on the active map
      - type: horizontal-stack
        cards:
          - type: button
            entity: button.dreame_a2_mower_start_mowing
            icon: mdi:play
            name: Start
            show_state: false
          - type: button
            entity: button.dreame_a2_mower_pause
            icon: mdi:pause
            name: Pause
            show_state: false
          - type: button
            entity: button.dreame_a2_mower_stop
            icon: mdi:stop
            name: Stop
            show_state: false
          - type: button
            entity: button.dreame_a2_mower_recharge
            icon: mdi:battery-charging
            name: Recharge
            show_state: false
          - type: button
            entity: button.dreame_a2_mower_find_my_robot
            icon: mdi:radar
            name: Find
            show_state: false

      # Plan 2 placeholders
      - type: markdown
        content: |
          ### 🚧 Mowing mode (Plan 2)

          `select.dreame_a2_mower_map_N_mowing_type` — picker for
          all-area / edger / zone / spot / manual. Determines what
          the Start button triggers. Per-map.

      - type: markdown
        content: |
          ### 🚧 Head to Maintenance Point (Plan 2)

          `button.dreame_a2_mower_head_to_maintenance_point` — sends
          the mower to the active map's currently-selected maintenance
          point. Requires per-map maintenance point storage.

      # GPS map — only useful when anti-theft realtime location is on
      - type: conditional
        conditions:
          - entity: switch.dreame_a2_mower_anti_theft_realtime_location
            state: "on"
        card:
          type: map
          entities:
            - entity: device_tracker.dreame_a2_mower_location
          aspect_ratio: 16:9
          default_zoom: 19
```

- [ ] **Step 2: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard(mower): populate main view — hero map + state + actions"
```

---

## Task 5: Map Selector view content

**Files:** `dashboards/mower/dashboard.yaml` — populate the `Map Selector` view.

The selector mirrors the app's map-list screen. Grid of pictures with tap_action setting the active map.

- [ ] **Step 1: Populate the Map Selector view**

```yaml
  - title: Map Selector
    path: maps
    icon: mdi:map-marker-multiple
    cards:
      - type: markdown
        content: |
          # Pick the active map

          Tapping a map sets `select.dreame_a2_mower_active_map`,
          which dispatches the mower's "change active map" command.
          Other per-map views (Mower, Settings & Zones, Schedule,
          LiDAR, WiFi Coverage) flip to show the new selection.

      - type: grid
        square: false
        columns: 2
        cards:
          - type: picture-entity
            entity: camera.dreame_a2_mower_map_0_map
            name: "Map 1"
            camera_view: live
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
            camera_view: live
            show_state: false
            tap_action:
              action: call-service
              service: select.select_option
              data:
                entity_id: select.dreame_a2_mower_active_map
                option: "Map 2"

      - type: entities
        title: Current active map
        entities:
          - entity: select.dreame_a2_mower_active_map
            name: Active map (dropdown)

      # Optional Plan 2 placeholder for map metadata
      - type: markdown
        content: |
          ### 🚧 Map metadata (Plan 2)

          Per-map sensors: name, area (m²), segment count, last-mow
          timestamp. Will render as a small stats card next to each
          map snapshot above.
```

- [ ] **Step 2: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard(maps): populate Map Selector view"
```

---

## Task 6: Settings & Zones view content

**Files:** `dashboards/mower/dashboard.yaml` — populate the `Settings & Zones` view.

This view contains ALL per-map configuration: header + General Mode settings + Custom Mode placeholder + zone editor + Plan 2 placeholders for Pathway OA / Ignore Zones / Maintenance Points.

- [ ] **Step 1: Populate the Settings & Zones view**

```yaml
  - title: Settings & Zones
    path: settings-zones
    icon: mdi:tune
    cards:
      - *per_map_header

      # General Mode — the 7 per-map settings switches from T8
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 0
        card:
          type: entities
          title: General Mode (Map 1)
          entities:
            - entity: switch.dreame_a2_mower_map_0_settings_edge_mowing_auto
            - entity: switch.dreame_a2_mower_map_0_settings_edge_mowing_safe
            - entity: switch.dreame_a2_mower_map_0_settings_edge_mowing_obstacle_avoidance
            - entity: switch.dreame_a2_mower_map_0_settings_obstacle_avoidance_enabled
            - entity: switch.dreame_a2_mower_map_0_ai_recognition_humans
            - entity: switch.dreame_a2_mower_map_0_ai_recognition_animals
            - entity: switch.dreame_a2_mower_map_0_ai_recognition_objects
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 1
        card:
          type: entities
          title: General Mode (Map 2)
          entities:
            - entity: switch.dreame_a2_mower_map_1_settings_edge_mowing_auto
            - entity: switch.dreame_a2_mower_map_1_settings_edge_mowing_safe
            - entity: switch.dreame_a2_mower_map_1_settings_edge_mowing_obstacle_avoidance
            - entity: switch.dreame_a2_mower_map_1_settings_obstacle_avoidance_enabled
            - entity: switch.dreame_a2_mower_map_1_ai_recognition_humans
            - entity: switch.dreame_a2_mower_map_1_ai_recognition_animals
            - entity: switch.dreame_a2_mower_map_1_ai_recognition_objects

      # Zone editor — per-map zone/spot/edge targets
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 0
        card:
          type: entities
          title: Zone editor (Map 1)
          entities:
            - entity: select.dreame_a2_mower_map_0_zone_target
              name: Zone target
            - entity: select.dreame_a2_mower_map_0_spot_target
              name: Spot target
            - entity: select.dreame_a2_mower_map_0_edge_target
              name: Edge target
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 1
        card:
          type: entities
          title: Zone editor (Map 2)
          entities:
            - entity: select.dreame_a2_mower_map_1_zone_target
              name: Zone target
            - entity: select.dreame_a2_mower_map_1_spot_target
              name: Spot target
            - entity: select.dreame_a2_mower_map_1_edge_target
              name: Edge target

      # Plan 2 placeholders
      - type: markdown
        content: |
          ### 🚧 Custom Mode (Plan 2)

          Per-zone settings overrides. Read via
          `sensor.dreame_a2_mower_map_N_custom_mode_overrides` (state
          attributes list zones with overrides). Write via services
          `dreame_a2_mower.set_zone_setting(map_id, zone_id, key,
          value)` and `dreame_a2_mower.clear_zone_setting(map_id,
          zone_id, key)`.

      - type: markdown
        content: |
          ### 🚧 Pathway Obstacle Avoidance (Plan 2)

          Per-map switch + sub-numbers for sensitivity/threshold.

      - type: markdown
        content: |
          ### 🚧 Ignore Obstacle Zones (Plan 2)

          Per-map list of rectangles. Read sensor with rectangles in
          attributes; write via `dreame_a2_mower.add_ignore_zone` /
          `dreame_a2_mower.remove_ignore_zone` services.

      - type: markdown
        content: |
          ### 🚧 Maintenance Points (Plan 2)

          Per-map list of named maintenance points placed on the map.
          Will render as a `picture-elements` with positioned pins
          over the map snapshot.
```

- [ ] **Step 2: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard(settings-zones): populate per-map settings + zone editor"
```

---

## Task 7: LiDAR view content

**Files:** `dashboards/mower/dashboard.yaml` — populate the `LiDAR` view.

- [ ] **Step 1: Populate the LiDAR view**

```yaml
  - title: LiDAR
    path: lidar
    icon: mdi:radar
    cards:
      - *per_map_header

      - type: markdown
        content: |
          # LiDAR point cloud
          The 3D scan for the active map. Rotate/zoom with mouse drag.

      # Custom card — per-map LiDAR (T13 made per-map)
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 0
        card:
          type: custom:dreame-a2-lidar-card
          map_id: 0
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 1
        card:
          type: custom:dreame-a2-lidar-card
          map_id: 1

      # Top-down snapshot cameras for the active map
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 0
        card:
          type: vertical-stack
          cards:
            - type: picture-entity
              entity: camera.dreame_a2_mower_map_0_lidar_top_down
              name: LiDAR top-down (Map 1)
              show_state: false
            - type: picture-entity
              entity: camera.dreame_a2_mower_map_0_lidar_top_down_full
              name: LiDAR top-down — full resolution (Map 1)
              show_state: false
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 1
        card:
          type: vertical-stack
          cards:
            - type: picture-entity
              entity: camera.dreame_a2_mower_map_1_lidar_top_down
              name: LiDAR top-down (Map 2)
              show_state: false
            - type: picture-entity
              entity: camera.dreame_a2_mower_map_1_lidar_top_down_full
              name: LiDAR top-down — full resolution (Map 2)
              show_state: false

      - type: entities
        title: LiDAR archive
        entities:
          - entity: sensor.dreame_a2_mower_lidar_archive_count
          - entity: sensor.dreame_a2_mower_lidar_archive_size_mb
            name: Archive size (MB)
```

- [ ] **Step 2: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard(lidar): populate per-map LiDAR view"
```

---

## Task 8: WiFi Coverage view + helpers documentation

**Files:**
- Modify: `dashboards/mower/dashboard.yaml` — populate WiFi view
- Create: `docs/superpowers/helpers/dreame-a2-helpers.yaml` — example helper config

The WiFi view stacks the heatmap on top of the base map with `card-mod` opacity binding. This is the only view that depends on `card-mod`.

- [ ] **Step 1: Create the helpers documentation file**

```yaml
# /data/claude/homeassistant/ha-dreame-a2-mower/docs/superpowers/helpers/dreame-a2-helpers.yaml
#
# Copy these into your HA configuration.yaml (or create them via
# Settings → Devices → Helpers in the HA UI). Both are required by
# the showcase dashboard at dashboards/mower/dashboard.yaml.

input_number:
  dreame_a2_mower_wifi_overlay_opacity:
    name: WiFi heatmap opacity
    min: 0
    max: 100
    step: 5
    initial: 50
    unit_of_measurement: "%"
    icon: mdi:wifi-strength-outline

  dreame_a2_mower_lidar_tilt:
    name: LiDAR view tilt
    min: 0
    max: 90
    step: 5
    initial: 30
    unit_of_measurement: "°"
    icon: mdi:angle-acute
```

- [ ] **Step 2: Populate the WiFi Coverage view**

```yaml
  - title: WiFi Coverage
    path: wifi
    icon: mdi:wifi
    cards:
      - *per_map_header

      - type: markdown
        content: |
          # WiFi heatmap

          Mower-recorded signal strength overlaid on the active map's
          base. Slide opacity below to balance heatmap visibility
          against map detail.

          Refresh: the mower regenerates the heatmap during mowing.
          Use the refresh button below to fetch the latest one from
          the cloud manually.

      # Opacity slider for the overlay
      - type: entities
        entities:
          - entity: input_number.dreame_a2_mower_wifi_overlay_opacity
            name: Heatmap opacity

      # Stacked picture-elements: base map + heatmap (opacity bound via card-mod)
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 0
        card:
          type: picture-elements
          image: /api/camera_proxy/camera.dreame_a2_mower_map_0_map
          elements:
            - type: image
              entity: camera.dreame_a2_mower_map_0_wifi_map
              image: /api/camera_proxy/camera.dreame_a2_mower_map_0_wifi_map
              style:
                top: 50%
                left: 50%
                width: 100%
                height: 100%
              card_mod:
                style: |
                  :host {
                    opacity: {{ states('input_number.dreame_a2_mower_wifi_overlay_opacity') | float / 100 }};
                  }
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 1
        card:
          type: picture-elements
          image: /api/camera_proxy/camera.dreame_a2_mower_map_1_map
          elements:
            - type: image
              entity: camera.dreame_a2_mower_map_1_wifi_map
              image: /api/camera_proxy/camera.dreame_a2_mower_map_1_wifi_map
              style:
                top: 50%
                left: 50%
                width: 100%
                height: 100%
              card_mod:
                style: |
                  :host {
                    opacity: {{ states('input_number.dreame_a2_mower_wifi_overlay_opacity') | float / 100 }};
                  }

      # Refresh button (per-map after T11)
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 0
        card:
          type: entities
          entities:
            - entity: button.dreame_a2_mower_map_0_request_wifi_map
              name: Refresh heatmap (Map 1)
      - type: conditional
        conditions:
          - condition: state
            entity: select.dreame_a2_mower_active_map
            attribute: current_map_id
            state: 1
        card:
          type: entities
          entities:
            - entity: button.dreame_a2_mower_map_1_request_wifi_map
              name: Refresh heatmap (Map 2)
```

- [ ] **Step 3: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml docs/superpowers/helpers/dreame-a2-helpers.yaml
git commit -m "dashboard(wifi): per-map heatmap overlay with card-mod opacity binding"
```

---

## Task 9: Schedule view content

**Files:** `dashboards/mower/dashboard.yaml` — populate the `Schedule` view.

Read-only today (T7 was deferred). View shows the count sensor + a markdown rendering of attributes.

- [ ] **Step 1: Populate the Schedule view**

```yaml
  - title: Schedule
    path: schedule
    icon: mdi:calendar-clock
    cards:
      - *per_map_header

      - type: markdown
        content: |
          # Schedule

          The g2408's schedule is read-only over cloud (BT-only writes
          per firmware 4.3.6_0550). Schedule editing is a Plan 2
          deliverable — slot data is currently per-mower not per-map,
          so the integration shows total slot count and the per-slot
          attributes for inspection.

      - type: entities
        entities:
          - entity: sensor.dreame_a2_mower_schedule_count
            name: Slot count

      # Slot details via attributes — markdown rendering keeps it
      # readable until a real per-map schedule entity lands.
      - type: markdown
        content: |
          ### Slot inspection

          Slot details are exposed as state attributes of
          `sensor.dreame_a2_mower_schedule_count`. Open the entity
          (More Info dialog) to view raw slots until Plan 2 ships a
          per-map schedule entity.

      # DnD / charging / low-speed windows (device-wide, not per-map)
      - type: entities
        title: Device-wide time windows
        entities:
          - entity: time.dreame_a2_mower_dnd_start_time
            name: DnD start
          - entity: time.dreame_a2_mower_dnd_end_time
            name: DnD end
          - entity: time.dreame_a2_mower_low_speed_at_night_start_time
            name: Low-speed start
          - entity: time.dreame_a2_mower_low_speed_at_night_end_time
            name: Low-speed end
          - entity: time.dreame_a2_mower_charging_start_time
            name: Charging start
          - entity: time.dreame_a2_mower_charging_end_time
            name: Charging end

      - type: markdown
        content: |
          ### 🚧 Per-map schedule slots (Plan 2)

          Each map's slot list with start/end times and which days
          of the week are active. Will render as a horizontal-stack
          of slot cards per map.
```

- [ ] **Step 2: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard(schedule): read-only slot + time-window display"
```

---

## Task 10: Sessions view content

**Files:** `dashboards/mower/dashboard.yaml` — populate the `Sessions` view.

The session-replay map is bound to the picker's selection (server-side via `_render_map_id`), so the dashboard YAML doesn't need conditionals here.

- [ ] **Step 1: Populate the Sessions view**

```yaml
  - title: Sessions
    path: sessions
    icon: mdi:history
    cards:
      - type: markdown
        content: |
          # Mowing session history

          All sessions, across both maps, sorted recent-first. The
          map below renders the session's recorded map_id (NOT the
          active map). Picking a Map 2 session shows Map 2's geometry
          regardless of which map is currently active.

      - type: entities
        title: Replay picker
        entities:
          - entity: select.dreame_a2_mower_replay_session
            name: Session

      # Replay camera — render swaps server-side per coord._render_map_id
      - type: picture-entity
        entity: camera.dreame_a2_mower_work_log
        name: Session replay
        camera_view: live
        show_state: false

      # Session stats
      - type: entities
        title: Selected session details
        entities:
          - entity: sensor.dreame_a2_mower_last_session_duration
            name: Duration
          - entity: sensor.dreame_a2_mower_last_session_area_mowed_sqm
            name: Area mowed (m²)
          - entity: sensor.dreame_a2_mower_last_session_end_reason
            name: End reason

      - type: markdown
        content: |
          ### 🚧 Per-map session totals (Plan 2)

          Per-map lifetime totals: area mowed, total mowing time,
          session count. Will render as a horizontal-stack of
          map-tagged stats cards next to the picker above.
```

- [ ] **Step 2: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard(sessions): cross-map history + replay map"
```

---

## Task 11: More Settings view content

**Files:** `dashboards/mower/dashboard.yaml` — populate the `More Settings` view with global config only.

This adapts the existing dashboard's More Settings view but drops the three per-map exceptions (Head to Maintenance Point, Pathway OA, Ignore Zones) which moved to Settings & Zones.

- [ ] **Step 1: Reference the existing layout**

Open `dashboards/mower/dashboard.pre-phase2.yaml.bak` and locate the `More Settings` view (look around line 372 of the original). Note which entities are listed under each section. Verify they're mower-level (not per-map) — anything per-map gets removed.

- [ ] **Step 2: Populate the More Settings view**

The structure mirrors the app's "More" page sections.

```yaml
  - title: More Settings
    path: more-settings
    icon: mdi:cog
    cards:
      - type: markdown
        content: |
          # More Settings
          Device-wide settings. Per-map settings (Pathway Obstacle
          Avoidance, Ignore Obstacle Zones, Maintenance Points) live
          on the **Settings & Zones** tab.

      # === [Work Management] ===
      - type: entities
        title: Work Management
        entities:
          - entity: switch.dreame_a2_mower_ai_obstacle_photos
            name: Capture photos of AI obstacles

      - type: markdown
        content: |
          ### 🚧 Consumables & Maintenance (Plan 3)

          Blade-hours and other consumable counters. Display per
          consumable with replacement reminders.

      # === [Functions] ===
      - type: markdown
        content: |
          ## Functions
          *Most entities below are Plan 3 placeholders — the app
          surfaces these on its "More" page but the integration
          hasn't yet implemented the underlying switches/numbers.*

      - type: markdown
        content: |
          ### 🚧 Rain Protection / Frost Protection (Plan 3)
          Switch + sub-numbers for activation thresholds.

      - type: markdown
        content: |
          ### 🚧 Do Not Disturb / Low-speed at Nighttime (Plan 3)
          Switch + time windows (already partially via `time.*`
          entities on the Schedule tab).

      - type: markdown
        content: |
          ### 🚧 Navigation Path / Charging / Start from Stop Point /
          Auto Recharge / Light (Plan 3)
          Mostly switches with the occasional sub-number.

      # === [Security] ===
      - type: entities
        title: Security
        entities:
          - entity: switch.dreame_a2_mower_anti_theft_realtime_location
            name: Anti-theft realtime location

      - type: markdown
        content: |
          ### 🚧 Anti-theft Alarm / Human Presence Detection / Child
          Lock / Change PIN Code (Plan 3)

      # === [General] ===
      - type: entities
        title: General — Language & Voice
        entities:
          - entity: select.dreame_a2_mower_voice_language
            name: Voice
          - entity: select.dreame_a2_mower_lcd_language
            name: LCD language
          - entity: number.dreame_a2_mower_volume
            name: Volume

      - type: markdown
        content: |
          ### 🚧 Time Zone / Switch Unit / Notifications (Plan 3)
```

- [ ] **Step 3: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard(more-settings): global-only config; per-map moved to Settings & Zones"
```

---

## Task 12: Diagnostics + Tools + Photo Privacy views

These are mostly adapted from the existing dashboard. Combine into one task since each is a copy-edit, not a redesign.

**Files:** `dashboards/mower/dashboard.yaml` — populate the three remaining views.

- [ ] **Step 1: Reference the existing layouts**

Open `dashboards/mower/dashboard.pre-phase2.yaml.bak`. Locate the `Diagnostics` view (~line 667), `Tools` view (~line 637), and `Photo Privacy Policy` view (~line 764). Copy each view's `cards:` content into the new file.

- [ ] **Step 2: Populate Diagnostics**

```yaml
  - title: Diagnostics
    path: diagnostics
    icon: mdi:wrench
    cards:
      - type: markdown
        content: |
          # Diagnostics
          Internal state of the integration. Useful for debugging
          and confirming hardware/firmware identity.

      - type: entities
        title: Device identity
        entities:
          - entity: sensor.dreame_a2_mower_hardware_serial
            name: Serial number
          - entity: sensor.dreame_a2_mower_firmware_version
            name: Firmware version
          - entity: sensor.dreame_a2_mower_model
            name: Model

      - type: entities
        title: Connectivity
        entities:
          - entity: binary_sensor.dreame_a2_mower_mqtt_connected
            name: MQTT connected
          - entity: binary_sensor.dreame_a2_mower_online
            name: Online (cloud)
          - entity: sensor.dreame_a2_mower_wifi_rssi_dbm
            name: WiFi RSSI (dBm)
          - entity: sensor.dreame_a2_mower_wifi_ssid
            name: WiFi SSID

      - type: entities
        title: Cloud refresh
        entities:
          - entity: sensor.dreame_a2_mower_last_cloud_refresh
            name: Last refresh
          - entity: sensor.dreame_a2_mower_cloud_state_version
            name: Cloud-state version
          - entity: sensor.dreame_a2_mower_settings_version_canonical
            name: Settings entry-0 version
          - entity: sensor.dreame_a2_mower_settings_version_applied
            name: Settings entry-1 version

      - type: markdown
        content: |
          ### Novel-log buffer

          The integration captures unknown-property and unknown-value
          events into a ring buffer of 200 entries. Use
          `dreame_a2_mower.download_diagnostics` (Tools tab) to
          download.
```

- [ ] **Step 3: Populate Tools**

```yaml
  - title: Tools
    path: tools
    icon: mdi:tools
    cards:
      - type: markdown
        content: |
          # Tools
          Manual triggers and recovery actions.

      - type: entities
        title: Manual refresh
        entities:
          - entity: button.dreame_a2_mower_refresh_cloud_state
            name: Refresh cloud state
          - entity: button.dreame_a2_mower_finalize_session
            name: Finalize pending session

      - type: markdown
        content: |
          ### Configuration files

          To install the dashboard or its required helpers:

          - Dashboard yaml lives at `/config/dashboards/mower/dashboard.yaml`.
            SCP from this repo's `dashboards/mower/dashboard.yaml`.
          - Helpers (`input_number.*` for WiFi opacity and LiDAR tilt):
            see `docs/superpowers/helpers/dreame-a2-helpers.yaml`.

      - type: markdown
        content: |
          ### Diagnostics download

          Service `dreame_a2_mower.download_diagnostics` writes a JSON
          bundle (state, novel-log, recent sessions). Call from Developer
          Tools → Services, or attach to an automation. File is written
          under the config dir.
```

- [ ] **Step 4: Populate Photo Privacy**

```yaml
  - title: Photo Privacy
    path: privacy
    icon: mdi:shield-account
    cards:
      - type: markdown
        content: |
          # Photo Privacy Policy
          The Dreame A2 captures photos of AI-detected obstacles
          when `switch.dreame_a2_mower_ai_obstacle_photos` is on.
          These photos are uploaded to Dreame's cloud and visible in
          the app under "Captured Photos."

          - Photos stay on Dreame's servers; this integration does
            not download or relay them.
          - Privacy controls live in the Dreame app's account
            settings.
          - Disabling AI obstacle photos prevents future captures
            but does NOT delete past captures from the cloud.
```

- [ ] **Step 5: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml'))"`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: adapt Diagnostics, Tools, Photo Privacy views"
```

---

## Task 13: Final YAML validation + structural smoke checks

Now that all 11 views are populated, do a structural cross-check before SCP.

**Files:** `dashboards/mower/dashboard.yaml` (validation only, no edits unless issues found).

- [ ] **Step 1: Re-validate full YAML**

```bash
python3 -c "import yaml; d = yaml.safe_load(open('dashboards/mower/dashboard.yaml')); print(f'views: {len(d[\"views\"])}')"
```

Expected: `views: 11`.

- [ ] **Step 2: Check each view has at least one card**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('dashboards/mower/dashboard.yaml'))
for v in d['views']:
    n = len(v.get('cards', []))
    print(f'  {v[\"title\"]:20s} → {n} cards')
    assert n > 0, f'empty view: {v[\"title\"]}'
"
```

Expected: each view has ≥1 card.

- [ ] **Step 3: Check anchor was correctly aliased**

```bash
python3 -c "
import yaml
text = open('dashboards/mower/dashboard.yaml').read()
assert '*per_map_header' in text, 'anchor not aliased anywhere'
count = text.count('*per_map_header')
print(f'anchor used in {count} views')
assert count >= 5, f'expected anchor in >=5 views, got {count}'
"
```

Expected: `anchor used in 5 views` (or more, if extra usage).

- [ ] **Step 4: Spot-check entity references resolve to known shapes**

```bash
grep -oE "(switch|sensor|binary_sensor|camera|select|button|number|input_number|time|device_tracker|lawn_mower)\.dreame_a2_mower[a-z0-9_]*" dashboards/mower/dashboard.yaml | sort -u | head -60
```

Manually skim for typos. Per-map entity refs should match `*_map_[01]_*`. The integration must have shipped Phase 2 Foundation (v1.0.4a1+); if a referenced entity doesn't exist after install, the card renders blank — that's expected for Plan 2/3 placeholders, NOT expected for entities that should exist.

If any reference looks suspicious, cross-check against the integration's source in `custom_components/dreame_a2_mower/`.

- [ ] **Step 5: Commit any fixes**

If Steps 1-4 flag issues, fix and commit:

```bash
git add dashboards/mower/dashboard.yaml
git commit -m "dashboard: structural fixes from validation"
```

If no fixes needed, no commit.

---

## Task 14: Push + manual SCP smoke test

The integration prerequisite (Task 1) shipped via release.sh. The dashboard YAML needs SCP — HACS does NOT deploy `dashboards/` content automatically.

- [ ] **Step 1: Push pending commits**

```bash
git push origin main
```

- [ ] **Step 2: User SCP's the dashboard to live HA**

Provide the user with the SCP command they'll run themselves (this is a user-action step, not automated):

```bash
# User runs from their workstation:
scp /path/to/ha-dreame-a2-mower/dashboards/mower/dashboard.yaml \
    hassio@hass:/config/dashboards/mower/dashboard.yaml
```

(Substitute the user's actual HA host / path as configured.)

- [ ] **Step 3: User restarts HA frontend**

The user reloads the dashboard (browser refresh) or restarts HA. After Lovelace picks up the new yaml, all 11 tabs should appear in the dashboard sidebar.

- [ ] **Step 4: Smoke-test each view**

Per the user-memory note (`feedback_dashboard_lovelace_cards.md`): if a view renders blank, grep the HA log for `createErrorCardElement` to find the failing card.

Expected results on each view:
- **Mower** — header thumbnail shows active map; hero map renders; action buttons clickable; state sensors populated; Plan 2 placeholders render as markdown
- **Map Selector** — 2-column grid shows both map snapshots; tapping a card switches active map (verify by going to Mower and confirming the thumbnail swapped)
- **Settings & Zones** — header swaps with active map; one set of General Mode + Zone Editor cards visible at a time
- **Schedule** — slot count + time windows render
- **LiDAR** — custom card loads for active map; top-down cameras render
- **WiFi Coverage** — opacity slider responds; picture-elements overlay loads (heatmap may be blank if no scan recorded yet for the active map)
- **Sessions** — picker dropdown populated; replay map renders selected session
- **More Settings** — sections render; Plan 3 placeholders visible
- **Diagnostics, Tools, Photo Privacy** — content renders

- [ ] **Step 5: Document any issues**

If any view fails to render, document in `docs/research/g2408-research-journal.md` under a 2026-05-11 entry. If all pass, append a one-liner confirming the dashboard rebuild shipped clean.

```bash
git add docs/research/g2408-research-journal.md
git commit -m "docs: phase 2 dashboard rebuild ship note"
git push origin main
```

The dashboard is YAML-only and SCP'd; no second release.sh needed for Task 14.

---

## Self-Review Checklist

After all tasks land:

- [ ] **Spec coverage**: every view in the spec is implemented in a task (Tasks 4-12 cover all 11 views). The prerequisite (Task 1) ships the `current_map_id` attribute. The placeholder pattern is used uniformly for Plan 2/3 entities. ✅
- [ ] **No placeholders in plan**: every step contains complete YAML or commands. No "TBD" / "implement later" / "similar to" references.
- [ ] **Type consistency**: entity ID patterns match between tasks (`switch.dreame_a2_mower_map_N_*`, `camera.dreame_a2_mower_map_N_*`). Anchor name `per_map_header` consistent. `current_map_id` integer attribute consistent.
- [ ] **One small spec deviation to flag**: the spec says "11 views"; this plan implements all 11 in Tasks 2 (scaffold) + 4-12 (content). The order in Task 2's scaffold (Mower, Map Selector, Settings & Zones, Schedule, LiDAR, WiFi Coverage, Sessions, More Settings, Diagnostics, Tools, Photo Privacy) reflects intended sidebar order — confirmed against spec.

---

## Out of scope (per spec; explicitly NOT in this plan)

- `tools/generate_dashboard.py` codegen script — hand-written yaml stays the spec's choice
- Tab-style view-within-view custom cards
- Mobile-specific layout breakpoints
- Active-map highlight border on Map Selector grid (spec open question #2 — deferred unless user asks)
- LiDAR tilt control wired to the WebGL card (spec open question #5 — `input_number` is documented in the helpers file but the WebGL card may not consume it yet)
- Map renaming UI
- Plan 2 entities (mowing-mode select, live video camera, map metadata sensors, maintenance points, pathway/ignore zones, custom mode services, per-map session sensors, per-map schedule)
- Plan 3 entities (Rain/Frost/DnD/Anti-theft/Child Lock/Find My Robot/Change PIN/etc.)
