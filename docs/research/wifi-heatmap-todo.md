# WiFi heatmap — open issues / TODO

Tracks unresolved problems in the WiFi heatmap path (cloud OBJ
`wifimap` objects → per-map camera entity + archive picker).
Created 2026-05-11 after surfacing the "second map's heatmap doesn't
appear" symptom and noticing the cell-size math doesn't match
real-world garden dimensions.

## Pipeline summary

```
device (auto)            cloud (OSS)              integration
─────────────            ───────────              ───────────────────────
generates wifimap   →    OSS object               s2.50 m=g t=OBJ d={type:wifimap}
on its own              wifimap_<unix>.json       → list of object names (newest-first)
schedule                                          get_interim_file_url + get_file
                                                  → decoded JSON body
                                                  → camera.wifi_heatmap_selected (per map)
                                                  → select.wifi_archive (cross-map picker)
```

Direct trigger path (`s6.aiid=4` "request fresh wifi map") returns
80001 closed on g2408 — read-side only.

## Decoded body shape (observed)

```
{
  "data":   list[int],   # width*height values; `1` = no data, negative = dBm
  "width":  int,         # cells across
  "height": int,         # cells down
  "resolution": int,     # value 2 observed on g2408 — units unconfirmed (see Issue #1)
  "startX": int,         # frame origin (cloud frame, units unconfirmed — see Issue #1)
  "startY": int,
}
```

There is **no** `map_id`, `mapIndex`, `mapName`, or any device-side
handle in either the JSON body or the OSS object name. Correlating a
heatmap to a base map relies entirely on geometry inference.

## Issue #1 — `resolution` unit is misinterpreted

**Current code:** `cand_w_cm = width * resolution * 10`
(`cloud_client.py:875`), i.e. treats `resolution=2` as "2 decimeters
per cell" (= 20 cm/cell).

**Why it's almost certainly wrong:** Observed heatmaps are at most
~20 cells across. With 20 cm per cell that means the heatmap covers
~4 m × 4 m of garden. The mower itself is ~50 cm wide; a garden
smaller than the mower can't be mowed. Real gardens are tens of
metres.

**Plausible candidates for the true unit:**
- **`resolution` is metres per cell** → a 16×18 grid covers 32×36 m
  (typical garden size). This is the most likely correct
  interpretation.
- **`resolution` is `2^n` cm per cell** (i.e. exponential scale) —
  less likely, no precedent in cloud format docs.
- **Different field entirely encodes scale**, and `resolution` is
  ignored — would require finding a wider context in the OSS body.

**Next step:**
1. Compare the bbox `(startX, startY) → (startX + width*res*K, …)`
   against a known base-map boundary `(bx1, by1, bx2, by2)` for
   multiple values of `K ∈ {1, 10, 100}` and see which K aligns.
2. Cross-check with `ioBroker.dreame v0.3.7 main.js:fetchWifiMap`
   (reference adapter) for how it scales heatmap cells onto base
   maps. (See `reference_iobroker_write_paths` for the reference
   repo location.)
3. Cross-check with the apk decoder if reachable.

**Impact:** the geometry-matching code in `fetch_wifi_map` and
`list_wifi_candidates` uses these wrong values, so bbox centres land
far off the real centres. This is part of why the second map's
heatmap doesn't appear — geometry matching fails, and prior to v1.0.5a9
the fallback was "newest object for everyone" (both maps showed the
same heatmap). v1.0.5a9 adds a positional tier-2 fallback that masks
the symptom but doesn't fix the underlying unit error.

## Issue #2 — heatmap-to-map correlation has no explicit ID

OSS body and object name carry no map identifier. Current ladder:
1. **Geometry match (tier 1):** does the bbox centre fall inside any
   base-map boundary? Broken until Issue #1 is fixed.
2. **Positional match (tier 2, v1.0.5a9+):** when N unmatched
   candidates == N unmatched maps, assign in API array order
   (`unix_ts` descending) to sorted `map_id`. Stable when 1:1, but
   guesswork when ambiguous.
3. **Newest-wins fallback:** if both tiers fail, every map gets the
   same (newest) heatmap. Effectively makes the second map invisible.

**Better signal candidates to investigate:**
- **Heatmap bbox shape:** width×height pair. If two maps differ in
  aspect ratio or scale, the heatmap shape should mirror them. E.g.
  16×18 maps to a 32×36 m garden but not to a 16×16 m garden.
- **Heatmap origin proximity:** `(startX, startY)` should be near the
  base map's `(bx1, by1)`. Even without scale, the origin alone may
  discriminate when maps are far apart in the cloud frame.
- **Object filename hidden prefix:** worth dumping a few full OSS
  object names to check if anything other than `wifimap_<ts>.json`
  is encoded.

## Issue #3 — heatmap may be coarser than base map cells

The base map is rendered cell-by-cell at LiDAR resolution
(~5 cm/cell). The heatmap is at ~2 m/cell (under the corrected unit).
Naïve overlay needs **upsampling**: each heatmap cell covers a
40×40 grid of base-map cells. The current camera-entity renderer
doesn't appear to do this explicitly — worth confirming once Issue
#1 is resolved.

## Issue #4 — `picture-elements` with empty `elements` doesn't render

**Symptom:** When the user toggles "show base map" off, the WiFi tab
card shows only a spinning blue circle (a Lovelace placeholder for a
card that has no concrete element to display).

**Cause:** `picture-elements` with `elements: []` renders nothing —
even though the underlying `image_entity` is valid. Lovelace
requires at least one element for the camera to display.

**Fix (deployed v1.0.5a9 dashboard):** When `show_base=off`, use
`picture-entity` (which renders the camera image natively) instead
of `picture-elements`. The base+overlay branch retains
`picture-elements` because it needs the overlay layer.

## Issue #5 — trigger path returns 80001

`s6.aiid=4` "request fresh wifi map" returns 80001 (cloud-tunnel
closed) on g2408. The integration's `button.request_wifi_map` is
therefore informational only. The device auto-generates wifi maps
on its own schedule. Confirmed in matrix
`entity-validation-matrix.md`.

## Resolution plan

1. **First:** decode the `resolution` unit (Issue #1). Without this,
   geometry matching is structurally wrong and the camera overlay
   alignment is broken.
2. **Second:** improve heatmap-to-map correlation (Issue #2) using
   shape signature + origin proximity rather than centre-in-bbox
   alone.
3. **Third:** verify upsampling for overlay (Issue #3) once base
   geometry is correct.
4. **Track:** Issue #5 stays in the validation matrix as a known
   read-only gap.

## Related code

- `custom_components/dreame_a2_mower/cloud_client.py:750-1100` —
  `fetch_wifi_map`, `_download_wifi_object`, `list_wifi_candidates`.
- `custom_components/dreame_a2_mower/coordinator.py:1507-1600` —
  `_refresh_wifi_map`, including `_build_map_extents` and archive
  cache wiring.
- `custom_components/dreame_a2_mower/camera.py` — per-map
  `DreameA2WifiHeatmapCamera`.
- `custom_components/dreame_a2_mower/select.py` —
  `DreameA2WifiArchiveSelect` cross-map picker.
- `dashboards/mower/dashboard.yaml` — WiFi tab layout.

## Related references

- `reference_iobroker_write_paths.md` — TA2k's adapter is the closest
  third-party reference for wifimap handling; grep
  `fetchWifiMap` / `resolution` / `startX` there before live testing.
- `docs/research/entity-validation-matrix.md` —
  `button.request_wifi_map` row documents the 80001 trigger gap.
