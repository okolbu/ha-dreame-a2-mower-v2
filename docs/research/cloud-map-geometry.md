# Cloud-Map Geometry Reference

How the Dreame cloud represents the user's lawn map, and the exact sequence of
transformations our integration applies before handing the data to the
`DreameMowerMapRenderer`. Single source of truth for any future overlay work
(live-mowing path animation, maintenance-point markers, session replay, extra
zone types).

Related:
- [`g2408-protocol.md`](./g2408-protocol.md) — MQTT + cloud API protocol summary.
- `custom_components/dreame_a2_mower/dreame/device.py::_build_map_from_cloud` —
  the code that implements everything below.
- `custom_components/dreame_a2_mower/protocol/cloud_map_geom.py` —
  `_rotate_path_around_centroid` helper.

All coordinates below are **in millimetres** unless otherwise stated. All
transformations are confirmed against the user's live g2408 mower and the
Dreame app's rendering (sample captures 2026-04-19).

---

## 1. Cloud JSON structure

The integration pulls the base map as 28 concatenated strings under the cloud
keys `MAP.0` … `MAP.27`. Once joined and JSON-decoded, the top-level object
looks like this:

```
{
  "boundary":       { "x1": -10920, "y1": -14080, "x2": 20890, "y2": 20961.15 },
  "mowingAreas":    { "value": [[1, { "path": [...], "name": "Zone 1", "shapeType": 0 }]] },
  "forbiddenAreas": { "value": [[101, { "path": [...4 corners...], "angle": -30.77, "shapeType": 2 }]] },
  "contours":       { "value": [[[1, 0], { "path": [...], "shapeType": 0 }]] },
  "spotAreas":      { "value": [...] },      # "extra mow here" markers (user hasn't used)
  "cleanPoints":    { "value": [...] },      # per-point go-to targets
  "cruisePoints":   { "value": [...] },      # probably "Maintenance Points" — unconfirmed
  "obstacles":      { "value": [...] },      # same shape as session-summary JSON
  "notObsAreas":    { "value": [...] },      # "not-obstacle" regions
  "paths":          { "value": [...] },      # preferred inter-zone pathways (usually empty)
  "totalArea":      383.74,                  # m²
  "md5sum":         "...",
  "mapIndex":       0,
  "hasBack":        1,
  "name":           "",
  "cut":            [],
  "merged":         false
}
```

`boundary` is the axis-aligned min/max of the map in cloud coordinates. It is
**NOT** guaranteed to cover every overlay — rotated forbidden zones can extend
past it (see §4 below). `totalArea` is the mowable area in m² and matches what
the app displays in the "A2 - Standby" header.

---

## 2. Two coordinate frames

### 2.1 Cloud frame

- Origin `(0, 0)` = where the mower's nose meets the charging station as it
  docks. **Not** the geometric centre of the station; the station body extends
  further along +X (see §5 below).
- `+X` = toward the house (the direction the mower faces when docked).
- `+Y` = perpendicular to +X. Sign is consistent with the `s1p4` telemetry
  stream's Y, i.e. one side of the lawn has positive Y, the other negative.
  Visual orientation is user-dependent: for our test mower, +Y lands on the
  "north" side of the lawn in both the cloud JSON and `s1p4`.
- Units: **millimetres**. So `boundary.x2 - boundary.x1 = 31810 mm ≈ 31.8 m`
  across for our test lawn.

### 2.2 Image frame

The `DreameMowerMapRenderer` works in a PIL image. Image-row index grows
downward; image-column index grows rightward. That is HA / Lovelace's
convention, and it's the same as every map card we ship.

**Crucial fact**: the cloud frame's +Y is visual "north" in the app's map
view, so to make HA match the app we must render with +Y at the top of the
image. The renderer's `Point.to_img` encodes this flip (see §3.2). Our
pixel-mask code encodes it differently (see §3.1), and the two formulas
look very different while actually being the same isometry — the reason we
need midline reflections explained below.

---

## 3. The two transforms that must agree

`_build_map_from_cloud` populates **two** data surfaces that the renderer
consumes:

1. `map_data.pixel_type` — a 2-D numpy array, one cell per `grid_size` (50 mm)
   in the map. We paint this directly, one pixel per segment/contour point.
2. `map_data.no_go_areas` (list of `Area`), `map_data.charger_position`
   (a `Point`), and any other rich-geometry fields. The renderer translates
   these via its own `Point.to_img` / `Area.to_img` when it paints overlays.

These two go through different formulas, and **they do not naturally agree**.
The Pixel mask uses midline-reflection arithmetic, the renderer does
naive-origin arithmetic. Any object that has to line up with the pixel mask
must be reflected before being placed into `Area` or `Point`.

### 3.1 Pixel mask formula (our side)

```python
px = (bx2 - x) // grid_size        # X-flipped
py = (by2 - y) // grid_size        # Y-flipped
```

Where `bx1, by1, bx2, by2` are the **expanded** bbox min/max (not the raw
`boundary`; see §4). A world point at cloud `(0, 0)` lands at
`px = bx2/grid, py = by2/grid`.

Why flipped both ways:

- `px = (bx2 - x)/grid` mirrors horizontally so the lawn polygon is oriented
  the same way the app shows it. Without this, the lawn appears mirrored
  left-right compared to the app.
- `py = (by2 - y)/grid` puts high-Y at the top of the image (low `py`). This
  matches the app's "north-up" convention.

### 3.2 Renderer formula (their side)

Inside `types.py::MapImageDimensions.to_img`:

```python
img_x = (x - bx1) / grid_size
img_y = (height - 1) - (y - by1) / grid_size
```

The X is NOT flipped. The Y IS flipped but through a different origin than our
mask uses (`by1` instead of `by2`). Algebraically, the renderer's Y formula is
equivalent to `(by2 - y)/grid_size` — they're the same. But the X formulas are
**different** mirrors, and that's what causes everything we hand to the
renderer as a raw cloud point to come out on the wrong side.

### 3.3 Bridge: reflect through the cloud midlines

For every piece of geometry we hand to the renderer as raw cloud coords, we
must reflect it through the midlines of the expanded bbox so that after the
renderer's formula runs, the object lands on the same pixel our pixel mask
used for it:

```python
x_reflect = bx1 + bx2        # midline × 2
y_reflect = by1 + by2

# For any cloud point (x, y) we want rendered at the same pixel our mask
# placed it, pass (x_reflect - x, y_reflect - y) to the renderer.
```

Worked X example (charger at cloud `(0, 0)`):

- Pixel mask places `(0, 0)` at `(bx2/50, by2/50) = (417.8, 419.2)`.
- If we pass raw `Point(0, 0, 0)` to the renderer: `img_x = (0 - bx1)/50 = 218.4`.
  That's on the **opposite** side of the image.
- If we pass `Point(bx1+bx2, by1+by2, 0) = Point(9970, 6881, 0)`:
  `img_x = (9970 - (-10920))/50 = 417.8`. Matches. ✅

This reflection applies to **charger_position**, **every no-go area corner**,
and will apply to any future raw-cloud-coord overlay (live mower position,
maintenance-point marker, etc.).

---

## 4. Forbidden-zone rotation

Forbidden-area entries carry their path as an **axis-aligned** 4-corner
rectangle plus a separate `angle` field in degrees. The angle describes
rotation around the polygon centroid. Ignoring the angle renders the zone
upright instead of tilted.

```json
{
  "path": [
    { "x": 12819.85, "y": 12543.97 },
    { "x":  1425.42, "y": 12543.97 },
    { "x":  1430.15, "y": 20956.03 },
    { "x": 12815.99, "y": 20961.15 }
  ],
  "angle": -30.77
}
```

`protocol/cloud_map_geom.py::_rotate_path_around_centroid` does the rotation.

### 4.1 Negate the angle

The cloud's angle convention is **mirror-flipped** relative to how the app
renders, in exactly the same way `+X` is mirrored. After we apply the midline
reflection above, the zone is in the right position but its rotation
handedness is from the cloud — producing a shape that's mirrored along the
image's X axis relative to what the app shows.

Fix: pass `-angle_deg` to `_rotate_path_around_centroid`. `mowingAreas` and
`contours` use full point-by-point paths (no `angle` field), so they're
unaffected.

### 4.2 Bbox expansion

The raw `boundary` does not always cover a rotated forbidden zone (the zone's
corners can extend past `by2` or `bx2`). Before sizing the `pixel_type` grid,
we:

1. Pre-rotate every forbidden path with the negated angle.
2. Sweep all rotated corners against `bx1/by1/bx2/by2` and expand.

The `pixel_type` grid is then sized from the expanded bbox, so every overlay
fits without clipping.

### 4.3 Crop-bbox trick

The renderer auto-crops the final image to the bbox of non-`OUTSIDE` pixels in
`pixel_type`. Forbidden zones are drawn as `Area` overlays, not into the
pixel mask, so by default the crop shrinks to the mowing zone and the
forbidden overlay clips at the edge.

We paint each **rotated forbidden corner** as a single `WALL` pixel in the
pixel mask. Four pixels per zone is enough to stretch the crop bbox to cover
the overlay, and each sits **under** the semi-transparent red `no_go` overlay
drawn by the renderer, so it's invisible in the final output.

---

## 5. Charger offset — cloud (0, 0) vs physical station centre

Cloud `(0, 0)` is where the mower's nose meets the dock, i.e. the edge of the
mowing area where the mower transitions from mowing to charging. The physical
charging station extends `80 cm` along the mower's +X direction (away from
the lawn). The app places its charger glyph at the physical centre of the
station, i.e. `400 mm` past the mower-nose-entry point.

We expose this as `CHARGER_OFFSET_MM` inside `_build_map_from_cloud`. Current
value: `800` (= full station length, not half — see commit history for why
the tuning landed on full length empirically; seems the mower also reports
a small offset into the station body).

After reflection, the offset reverses sign (same way `+X` does). The final
`charger_position` becomes:

```python
Point(bx1 + bx2 - CHARGER_OFFSET_MM, by1 + by2, 0)
```

---

## 6. Opacity — use the renderer's overlay path

Don't paint forbidden zones into `pixel_type` as `WALL` (opaque grey). Instead:

1. Populate `map_data.no_go_areas` with `Area` objects (using the reflection
   from §3.3).
2. Leave `map_data.saved_map = False` — this is the renderer's "draw overlays"
   branch. `saved_map=True` skips overlay rendering entirely, which is why
   the earliest iterations painted the zones as opaque grey.

The renderer then uses `color_scheme.no_go` (default `(177, 0, 0, 50)` — red,
~20 % alpha) so the lawn below stays visible. Matches the app's pink-overlay
look.

---

## 7. Worked example — one forbidden-zone corner

Using the real 2026-04-19 fixture. Boundary already expanded so
`bx1 = -10920`, `by1 = -14080`, `bx2 = 20890`, `by2 = 20961`.

Input corner (pre-rotation):

```
(12819.85, 12543.97)
```

### Step 1 — rotate around centroid

Centroid of the 4 raw corners: `(7123, 16751)`.

Negate the angle: `-(-30.77) = 30.77°`. Rotate the corner by +30.77° around
the centroid:

```
dx = 12819.85 - 7123   = 5696.85
dy = 12543.97 - 16751  = -4207.03
cos_θ =  0.859
sin_θ =  0.512
new_dx =  dx * cos_θ - dy * sin_θ = 4894.9 + 2154.0 = 7048.9
new_dy =  dx * sin_θ + dy * cos_θ = 2916.9 + -3612.9 = -696.0
rotated = (7123 + 7048.9, 16751 + -696.0) = (14171.9, 16055.0)
```

### Step 2 — reflect through bbox midlines

```
x_reflect = bx1 + bx2 = -10920 + 20890 = 9970
y_reflect = by1 + by2 = -14080 + 20961 = 6881
reflected = (9970 - 14171.9, 6881 - 16055.0) = (-4201.9, -9174.0)
```

This is what we hand to `Area(...)`.

### Step 3 — renderer's pixel placement

When the renderer paints the overlay, it calls `Point.to_img(-4201.9, -9174.0)`:

```
img_x = (-4201.9 - (-10920)) / 50 = 6718.1 / 50 = 134.4
img_y = 700 - (-9174.0 - (-14080)) / 50 = 700 - 4906 / 50 = 700 - 98.1 = 601.9
```

Corner lands at pixel `(134, 602)` in the post-crop image — confirmed
visually to be the lower-left of the rendered exclusion rectangle in the
dashboard's `camera.dreame_a2_mower_map`.

---

## 8. Applying this to future overlays

When you add a new overlay (live mower position, obstacle marker,
maintenance-point glyph, replay trail, …):

1. Is it a **single** point or line drawn by the renderer on top of the
   pixel mask? → use §3.3 reflection so its raw cloud coords land where the
   mask placed the corresponding area.
2. Is it a **filled area** you want the renderer to paint with alpha? →
   populate the appropriate `map_data.<layer>` list (same pattern as
   `no_go_areas`), keep `saved_map=False`, and rely on the colour scheme.
3. Is it a **pixelised fill** (zone colour, obstacle texture, coverage
   trail)? → paint directly into `pixel_type` using the `(bx2-x, by2-y)`
   mask formula.
4. Does the new geometry potentially exceed the current bbox? → expand
   `bx1/by1/bx2/by2` the same way §4.2 does for rotated forbidden zones.

Any rotation field attached to a shape is probably cloud-handedness and will
need the same negate-before-rotating trick as `forbiddenAreas.angle`.
