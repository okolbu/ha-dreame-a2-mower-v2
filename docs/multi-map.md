# Multi-map support

The integration supports multiple cloud-side maps. Each map has its
own zones, contours, and replay sessions; the live trail follows
whichever map the mower is currently using.

## Entities

| entity_id | Purpose |
|---|---|
| `select.dreame_a2_mower_active_map` | Reflects the mower's firmware-selected active map. **Read-only** for now — switching maps requires the app. |
| `camera.dreame_a2_mower_map` | Active-map follower. Renders the active map's base + live trail (or replay during session-pick). |
| `camera.dreame_a2_mower_map_<id>` | Static per-map snapshot for the "Maps" dashboard view. |
| `select.dreame_a2_mower_replay_session` | Replay picker — entries from all maps, prefixed with `[Map N]`. |

## How active-map detection works

The integration polls `cfg_individual.MAPL` every 10 minutes (and on
each `mowing_started` event) to determine which map the mower is
actively using. MAPL is a 2D array with one row per map; the row
whose second column is `1` is the active map.

If you switch maps in the Dreame app, HA picks up the change within
~10 minutes (or on the next mow start). Manually triggering an
update is not exposed today.

## Adding a new map

The Dreame app's "Add map" / "Edit map" flow creates a new map slot.
After creating one:

1. Wait for the next CFG poll (or restart HA) so the integration
   sees `MAPL` with the new entry.
2. The per-map camera entity for the new map (`camera.map_<id>`) is
   created on the next HA restart. (Phase 1 doesn't auto-register
   entities at runtime — restart is required.)
3. The Maps dashboard view shows a hard-coded slot for the first 2
   maps; edit `dashboards/mower/dashboard.yaml` to add more.

## Replays across maps

The replay picker shows all archived sessions across all maps,
prefixed with `[Map 1]` / `[Map 2]` / etc. Picking a session from
the inactive map temporarily flips `camera.dreame_a2_mower_map` to
that map for the duration of the replay; the next live update reverts
it to the active map.

## Limitations

- Active-map switching is observed-only in HA — use the app to switch.
- Per-map LiDAR archives are not yet investigated; today's LiDAR
  archive is shared across maps.
- Inter-map "navigation paths" (the gray polyline the app draws between
  maps) are decoded into `MapData.nav_paths` but not yet rendered.
