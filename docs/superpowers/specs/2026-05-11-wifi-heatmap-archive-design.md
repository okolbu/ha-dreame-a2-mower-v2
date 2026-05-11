# WiFi Heatmap Archive — Design

**Created:** 2026-05-11
**Status:** Approved (brainstorm complete; awaiting plan)
**Scope:** Local archive of cloud-side WiFi heatmaps + canonical-orientation
renderer + honest labelling. Replaces the current live-cloud snapshot model.

## Goals

1. **Local archive on refresh.** When the user taps "Refresh heatmaps",
   the integration fetches every wifimap OSS object the cloud holds and
   writes new ones to disk. The picker reads from the disk archive, not
   from live cloud. Old entries persist across reboots.
2. **`[Map ?]` honest labels.** Heatmap → base-map correlation is
   unsolved; labels reflect that until it is.
3. **Canonical-orientation renderer.** The camera draws the heatmap in
   the project's coordinate convention (origin at dock, +X right, +Y
   up). Flip toggles stay as escape hatches.
4. **Map-1 base under everything (scaffold).** Until per-heatmap base
   correlation is solved, the "Show Base Map" toggle uses Map 1's base
   under any selected heatmap — proves the overlay + opacity plumbing
   works.

## Out of scope

- Resolution-unit fix (the cm-vs-m bug in geometry math).
  See `docs/research/wifi-heatmap-todo.md` Issue #1.
- Trigger investigation — can we request fresh device-side generation?
  `s6.aiid=4` is closed; alternative aiids unexplored.
  See `docs/research/wifi-heatmap-todo.md` Issue #5.
- Heatmap → map_id correlation algorithm beyond `[Map ?]`.
- Per-heatmap correct base-map matching.
- LiDAR work (already correct after prior refactor).
- Heatmap retention/size cap. Files are ~5 KB each; defer.

## Coordinate convention (framing)

The heatmap renderer renders into the project's canonical map view:

- **Origin** at the docking station.
- **+X →** to the right of the map view (= behind the mower stationed
  nose-in at dock).
- **+Y ↑** to the top of the map view (standard math convention).

A heatmap cell at array position `(col, row)` therefore maps to image
position `(col, h - 1 - row)` — i.e. row 0 in the array (smallest Y)
lands at the bottom of the image; row h-1 (largest Y) lands at the top.

This is **not** "flipping what we did wrong"; it is rendering in the
documented coordinate system. The empirical observation that the
current default needs a Flip-Y toggle to look right means the renderer
currently lays out cells in array-storage order without inversion,
which is wrong for the canonical view.

## Architecture

```
User taps "Refresh heatmaps"
    ↓
coordinator.refresh_wifi_archive()
    ↓
1. Cloud OBJ probe — s2.50 m=g t=OBJ d={type:wifimap}
2. For each object_name NOT on disk: download + write to disk
3. Append metadata to index.json
4. Notify picker
    ↓
select.wifi_archive rebuilds options from disk index
    ↓
User selects entry → camera renders that file
                     with canonical-orientation drawing
```

## Components

### `wifi_archive/` on disk

```
/config/dreame_a2_mower/wifi_archive/
    index.json
    <object_name>.json    # one per unique OSS object
    ...
```

- `<object_name>` is the cloud's OSS filename verbatim (e.g.
  `wifimap_1700000001.json`). Dedup = "does this file exist?".
- Cloud filenames embed a unix timestamp; the existing
  `_parse_unix_ts` regex (`_(\d{9,11})(?:[._]|$)`) extracts it.

### `index.json` schema

```json
[
  {
    "object_name": "wifimap_1700000001.json",
    "unix_ts": 1700000001,
    "width": 16,
    "height": 18,
    "resolution": 2,
    "startX": -1100,
    "startY": -1500,
    "first_seen_unix": 1747000000
  }
]
```

- `unix_ts`: parsed from OSS filename (authoritative source-time).
- `first_seen_unix`: when the integration first downloaded this
  object (diagnostic only).
- No content hash; the cloud filename is unique per generation.

### `coordinator.refresh_wifi_archive()`

```python
async def refresh_wifi_archive(self) -> dict:
    """Fetch all cloud wifimap objects and archive new ones to disk.

    Idempotent: objects already on disk are skipped. Returns a
    summary dict {'fetched': N, 'new': M, 'archive_total': K} for
    diagnostics.
    """
```

Behaviour:
1. Calls cloud OBJ probe via `cloud_client.list_wifi_candidates`.
2. For each candidate whose `object_name` is not already in the
   on-disk archive: downloads the body, writes to
   `wifi_archive/<object_name>.json`, appends to `index.json`.
3. Reads back the full index, sets `_wifi_archive_index` (in-memory
   mirror), notifies coordinator listeners.
4. Objects on disk but absent from cloud are KEPT — the archive is
   the long-term record.

All I/O on executor; no blocking on event loop.

### `select.wifi_archive`

- Reads `coordinator._wifi_archive_index` (in-memory mirror of disk).
- Sorts newest-first by `unix_ts`.
- Every label: `[Map ?] YYYY-MM-DD HH:MM`.
- On select → sets `coordinator._wifi_render_entry = (None, object_name)`.
- Rebuilds on every coordinator update (covers refresh-button flow).

### `camera.wifi_heatmap_selected`

- Reads selected `object_name` from `coordinator._wifi_render_entry`,
  loads `wifi_archive/<object_name>.json` from disk.
- Iterates cells in canonical orientation: for `row in range(h)`, for
  `col in range(w)`, draws into image pixel `(col, h - 1 - row)`.
- **Flip X** toggle ON: mirror column → `(w - 1 - col, h - 1 - row)`.
- **Flip Y** toggle ON: **inverts** the canonical orientation —
  i.e. draws into `(col, row)` instead of `(col, h - 1 - row)`. This
  is an escape hatch in case the coordinate-convention assumption is
  wrong for some firmware variant.
- Default toggle state: both OFF.

### `button.refresh_wifi_heatmaps`

- Single button on the mower device (not per-map).
- Action: `coordinator.refresh_wifi_archive()`.
- Replaces any existing per-map refresh buttons.

## Dashboard changes

- Single combined WiFi card (no map-id specific cards).
- `input_boolean.dreame_a2_mower_wifi_show_base` ON →
  `picture-elements` with Map 1's base camera underneath,
  heatmap camera on top with opacity from slider.
- `input_boolean.dreame_a2_mower_wifi_show_base` OFF →
  `picture-entity` showing heatmap camera alone (already shipped).
- Flip X / Flip Y toggles kept; relabel as "override" not "flip".
- Opacity slider unchanged.

## Tests

- **Unit: archive dedup.** `refresh_wifi_archive` called twice in a
  row with identical cloud state produces no duplicate index entries.
- **Unit: archive append.** When cloud adds a new object,
  `refresh_wifi_archive` writes the new file and appends to index;
  existing entries unchanged.
- **Unit: archive persistence.** After write, reading
  `index.json` returns the full list (including `first_seen_unix`).
- **Unit: renderer canonical Y orientation.** Cell at array `(0, 0)`
  appears at image pixel `(0, h-1)` (bottom-left), not `(0, 0)`
  (top-left).
- **Unit: Flip Y escape hatch.** With Flip-Y ON, cell `(0, 0)`
  appears at image pixel `(0, 0)` (top-left).
- **Unit: Flip X.** With Flip-X ON, cell at array `(0, 0)` appears at
  image pixel `(w-1, h-1)`.
- **Unit: picker label format.** Every label is `[Map ?] YYYY-MM-DD
  HH:MM`, regardless of any inferred `map_id`.
- **Integration: picker rebuilds on refresh.** After
  `refresh_wifi_archive` adds a new entry, the picker's options list
  includes it on the next coordinator update.

## Related files

- `custom_components/dreame_a2_mower/cloud_client.py:750-1100` —
  `fetch_wifi_map`, `list_wifi_candidates`, `_download_wifi_object`.
- `custom_components/dreame_a2_mower/coordinator.py:1500-1600` —
  current per-map `_refresh_wifi_map`.
- `custom_components/dreame_a2_mower/camera.py` —
  `DreameA2WifiHeatmapCamera`, `DreameA2WifiSelectedCamera`.
- `custom_components/dreame_a2_mower/select.py:1590-1690` —
  `DreameA2WifiArchiveSelect`.
- `custom_components/dreame_a2_mower/button.py` — refresh button.
- `dashboards/mower/dashboard.yaml` — WiFi tab layout.
- `docs/research/wifi-heatmap-todo.md` — open research items.

## Migration

- Existing in-memory `_wifi_map_by_id` and `_wifi_archive_cache` get
  replaced by `_wifi_archive_index` (disk-backed).
- Existing per-map refresh button removed; single
  `button.refresh_wifi_heatmaps` replaces it.
- Existing entity unique_ids preserved where possible; entity-rename
  orphans (see `feedback_entity_rename_orphan`) handled via
  `async_migrate_entry`.
