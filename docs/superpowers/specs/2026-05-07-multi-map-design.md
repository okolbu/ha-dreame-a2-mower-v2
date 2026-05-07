# Multi-Map Support Design

**Status:** approved 2026-05-07
**Scope:** full reshape — fetch + parse + cache N maps, active-map awareness,
per-map cameras, archive `map_id`, `paths` decoding, dashboard updates.
Wipe-and-rebuild for old archives (this integration is dev-only, no
production migrations needed).

## Why

The user has two cloud-side maps as of 2026-05-07: an existing primary
plus a new "Map 2" with a connecting nav-path back toward the dock. The
integration today fetches and renders only the first map in the cloud
batch and silently discards the rest. The mowing on Map 2 is invisible
to HA; the live trail renders against the wrong base map; replay
sessions can't be associated with a specific map; the gray "navigation
path between maps" the app shows isn't decoded.

Cloud-side multi-map plumbing is already there: the
`get_batch_device_datas(["MAP.0", ..., "MAP.27"])` response carries all
maps concatenated, with `MAP.info` giving the byte-offset where the
second map starts. Legacy upstream's `parse_batch_map_data` at
`alternatives/dreame-mower/.../map_data_parser.py:397` splits on
`MAP.info`, parses each segment, and keys by `mapIndex`. The greenfield
just `raw_decode`s the first JSON object and stops.

## Architecture

A single full-reshape change:

```
fetch_map() ──── splits MAP.0..27 via MAP.info ───► dict[map_id, raw_dict]
                                                         │
                                                         ▼
                            parse_cloud_maps(by_id) ───► dict[map_id, MapData]
                                                         │
                                                         ▼
                                          coordinator._cached_maps_by_id
                                                         │
                                              ┌──────────┴────────┐
                                              ▼                    ▼
                               active_map_id (MAPL poll)   _render_map_id
                                                                   │
                                                                   ▼
                                                  cached_map_png (active OR replay)
```

Two map-id pointers on the coordinator:

- `_active_map_id` — the cloud-active map (from `MAPL` polling). Drives
  the live-trail render base, the zone/spot/edge selectors, and the
  default for `_render_map_id`.
- `_render_map_id` — what the camera entity is currently rendering.
  Equal to `_active_map_id` except briefly during a replay-session pick
  (when it's set to `session.map_id`); reverts to `_active_map_id` on
  the next `_refresh_map` tick.

## Data layer

### `MapData` schema additions

`map_decoder.MapData` gains:

| field | type | source |
|---|---|---|
| `map_id` | `int` | cloud `mapIndex` |
| `name` | `str | None` | cloud `name` (e.g. `"Map 1"`, `"Map 2"`) |
| `nav_paths` | `tuple[NavPath, ...]` | cloud `paths` key (the gray inter-map paths) |

New dataclass `NavPath { path_id: int, path: tuple[(x_m, y_m), ...], path_type: int }`.

### `cloud_client.fetch_map()` reshape

Returns `dict[int, dict] | None`:

1. `get_batch_device_datas(["MAP.0".."MAP.27", "MAP.info"])`
2. Reassemble `MAP.0..27` into one string (existing path).
3. Read `MAP.info`; if a positive integer, split the string at that
   byte offset (existing legacy logic).
4. Parse each part as JSON; `mapIndex` from the per-map dict keys it.
5. Return `{0: dict0, 1: dict1, ...}`.

A failure to split or parse any part still returns the parts that
succeeded — partial results beat no results.

### `map_decoder.parse_cloud_maps(by_id)`

New top-level function. Iterates the input dict, calls existing
`parse_cloud_map` per entry, stamps `map_id` and `name` and `nav_paths`
on each MapData. Returns `dict[int, MapData]`.

`paths` decoding: each entry is `{path_id: {path: [{x, y}, ...], type: N}}`.
Convert to `NavPath` list with cloud-mm → renderer-frame coords using
the same affine the boundary uses (so paths overlay correctly).

## Active-map detection + select entity

### Source of truth

`cfg_individual.MAPL` polled by the existing `_refresh_cfg` (every
10 min). Decode rule:

- Each row is `[map_id, is_active, ?, ?, ?]`.
- Active = the row whose col 1 == 1.
- If no row matches, keep previous `_active_map_id`.
- If MAPL hasn't been seen yet, default to `min(_cached_maps_by_id.keys())`.

### Re-poll triggers

- Every 10 min via `_refresh_cfg` (no change).
- On `mowing_started` event fire (so live trail lands on the right map
  immediately, not after up to 10 min lag). Implemented as an awaitable
  re-poll inside `_fire_lifecycle` or the same fire site.

### `select.dreame_a2_mower_active_map`

- Options: enumerated from `_cached_maps_by_id`. Display labels use
  `MapData.name` if set, else `"Map {map_id+1}"`.
- Current: name corresponding to `_active_map_id`.
- **Read-only initially** — `async_select_option` logs INFO ("active
  map selection is observed-only; cloud write action TBD") and
  re-resolves from MAPL.
- Class stays `SelectEntity` (no class change later when writability
  lands).

## Camera surface

### `camera.dreame_a2_mower_map` (kept, single-instance)

- Renders the PNG corresponding to `_render_map_id`.
- Live-trail re-render path uses `_cached_maps_by_id[_active_map_id]`
  as the base map (so trails follow the active map).
- `entity_picture` continues to point at `MapImageView`; the view's
  served bytes are `_cached_pngs_by_id[_render_map_id]`.
- `extra_state_attributes` adds `map_id`, `map_name`, `available_map_ids`.
- `calibration_points` reflects whichever map is currently rendered (so
  the LiDAR card's affine fit follows the camera's content).

### Per-map static cameras `camera.dreame_a2_mower_map_<id>` (new)

- One per detected map. Read-only base-map snapshots, no live trail.
- Refreshed on each `_refresh_map` tick.
- Used by the new "Maps" dashboard view to show all maps side-by-side.
- No `entity_picture` JWT; same `MapImageView` pattern with `?map_id=N&v=<sha>`
  query params.

## Replay-session picker

`select.dreame_a2_mower_replay_session` (kept entity_id):

- Options now include all archived sessions across all maps, prefixed
  with the source map's name (e.g. `[Map 2] 2026-04-30 21:14 — 306m²`).
- Sort: most recent first, regardless of map.
- On selection: `coordinator.replay_session(filename)` reads
  `session.map_id` from the archive entry and renders against
  `_cached_maps_by_id[session.map_id]`. Sets `_render_map_id` to that
  value. Calibration_points + camera image both swap to the session's
  map.
- Reverting: next `_refresh_map` tick (live trail update or 6-hourly
  re-fetch) sets `_render_map_id` back to `_active_map_id`.

## Archive schema

### Breaking change

`ArchivedSession` gains required `map_id: int`. Schema version bumps
from `1` to `2`. On boot, the index loader skips entries lacking a
`map_id` (logs a warning naming the file). Files stay on disk so
`tools/recover_sessions.py` can retro-fit them later by reading the
session-summary's `map_index` field.

No automatic migration code. The user has confirmed dev-only
deployment — wipe-and-rebuild via probe logs is preferred to migration
complexity.

### New session writes

`coordinator._do_oss_fetch` and `_run_finalize_incomplete` both have
access to the active map at finalize time. They stamp
`map_id = self._active_map_id` on the new `ArchivedSession`.

If `_active_map_id` is None at finalize time, fall back in this order:

1. `min(_cached_maps_by_id.keys())` if any maps are cached (assume the
   only / primary map).
2. `-1` if no maps are cached at all (rare — implies the coordinator
   finalized a session before any successful `_refresh_map`).

Sessions archived with `map_id == -1` render in the picker with a
`[Map ?]` prefix; the ⚠ partial-trail marker (existing) is unrelated
and stays in its own field.

## Dashboard

### Existing "Mower" view

- Header gains a card showing `select.dreame_a2_mower_active_map` so
  the user can see (and eventually pick) the active map.
- All map-tied cards (camera, zone/spot/edge selectors, replay map)
  continue to work — they auto-pivot via `_render_map_id`.

### New "Maps" view

- Iterates known map IDs (initially hard-coded for 2 maps; the bundled
  yaml gets regenerated when more maps land).
- Per-map block: a `picture-entity` for `camera.dreame_a2_mower_map_<id>`
  with the map name as title. Below: a markdown card showing key facts
  (zone count, total area, last mow date).

## Tests

### New

- `tests/protocol/test_multi_map_decoder.py` — fixture file from
  today's two-map MAPL response. `parse_cloud_maps` returns 2 MapData;
  each has correct `map_id`, `name`, `nav_paths`.
- `tests/protocol/test_nav_paths.py` — verify `paths` key decodes to
  `NavPath` list with correct point-in-renderer-coords transform.
- `tests/integration/test_active_map_routing.py` — MAPL with row-1=1
  sets `_active_map_id=0`, MAPL with row-2=1 sets `_active_map_id=1`.
- `tests/integration/test_replay_cross_map.py` — picking a replay from
  the inactive map renders against the session's map, not the active.

### Modified

- Existing `tests/protocol/test_map_decoder.py` — extend single-map
  fixtures with `map_id`/`name` assertions where applicable.
- Existing `tests/integration/test_coordinator.py` — fixtures updated
  to seed `_cached_maps_by_id` and `_active_map_id` instead of single
  `_cached_map_data`.

### Skipped

- Writability of `select.active_map` (TODO).
- LiDAR per-map (TODO).
- Per-map archive folder layout.

## Out of scope (filed as TODOs)

- **Writable `select.active_map`**: requires capturing the app's
  "set active map" action wire format. Probe procedure: enable
  in-app map switching with probe log running; diff `s2.50` /
  `setCFG` traffic; document.
- **LiDAR per-map**: today's `lidar_archive` is a flat folder. If the
  mower keeps separate LiDAR scans per map, the archive needs a
  `map_id` field. Investigate whether `s99p20`'s LiDAR push carries a
  map_id hint.
- **`paths` overlay rendering**: this PR decodes them; rendering them
  as a styled gray polyline on the camera image is Phase 2 polish.
- **Active-map switch via MQTT**: if app-side switching produces an
  MQTT push (s2p51 multi-config blob, perhaps), capture and wire it
  for sub-10-min lag.

## Migration / compatibility

This is a breaking-change PR. Specifically:

- Existing archived sessions in `<config>/dreame_a2_mower/sessions/`
  without `map_id` are skipped from the picker (kept on disk for
  retro-fit).
- `coordinator._cached_map_data` and `cached_map_png` are removed in
  favour of property accessors `active_map` and `active_map_png`.
  Internal-only attribute change; entity surface unchanged.
- `MapData.map_id` and `name` are required fields. Tests that build
  MapData manually need updating.

The user has confirmed dev-only deployment; wipe-and-rebuild via probe
logs is acceptable. No `version` migration code is included.
