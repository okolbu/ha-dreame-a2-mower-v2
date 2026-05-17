# Mower Path Render Styling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Match the Dreame app's two-tone green aesthetic across static work_log.png + replay-card animation, add a fat/thin toggle, traversal-distinct rendering, dynamic pre-start visualization, and a smooth icon-traverses-with-progressive-reveal animation engine.

**Architecture:** Three phases shipped as independent releases. P1 is pure palette + render-layer changes (low risk). P2 rewrites the JS animation engine. P3 adds per-map direction tracking + stripe overlay rendering for idle-mode pre-start preview.

**Tech Stack:** Python 3.14, Pillow for raster rendering, Home Assistant 2026.5, vanilla JS + SVG for the replay card.

**Spec:** `docs/superpowers/specs/2026-05-17-mower-path-render-styling-design.md`

**Closes:** `project_render_styling_todo` (after P3 ships)

---

## Naming reference (used throughout the plan)

| Concept | Concrete value / name |
|---|---|
| `light_green` | `(178, 223, 138, 255)` — lawn baseline, post-mow stroke color |
| `dark_green` | `(100, 160, 70, 255)` — pre-mow / cutting-target color, active-mow background |
| `ignore_fill` (NEW) | `(90, 140, 230, 90)` — blueish-green, semi-transparent |
| `ignore_outline` (NEW) | `(60, 110, 200, 220)` — blueish-green outline |
| `mow_trail_color` (NEW) | `(178, 223, 138, 255)` — same as `light_green`; explicit name for the trail use case |
| `mow_trail_thin_color` (NEW) | `(50, 100, 30, 220)` — dark-green α220, used in JS "thin" mode |
| `traversal_color` (NEW) | `(130, 130, 130, 220)` — medium grey, drawn last (always on top) |
| `STRIPE_WIDTH_MM` (NEW) | `400` (tunable) — pre-start stripe band width in cloud-frame mm |
| `ActionMode` (existing) | enum: `ALL_AREAS`, `EDGE`, `ZONE`, `SPOT` (from `mower/state.py`) |
| Mowing-pattern values (existing) | int: 0=Striped (=same as last), 1=Crisscross (+45°), 2=Chequerboard (+90°) |
| `MowSession` (existing) | enum from `mower/state_snapshot.py`: includes `IN_SESSION` member |

---

# Phase 1 — Color palette + traversal layer split

Low-risk visual refresh. Touches `map_render.py` + tests only.

## Task 1: Add new palette keys (additive only)

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` (extend `_DEFAULT_PALETTE` ~line 56)
- Test: `tests/protocol/test_map_render_palette.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_map_render_palette.py`:

```python
"""Palette constants for the new mower-path render styling (Phase 1)."""
from custom_components.dreame_a2_mower.map_render import _DEFAULT_PALETTE


def test_dark_green_key_present():
    assert _DEFAULT_PALETTE["dark_green"] == (100, 160, 70, 255)


def test_mow_trail_color_matches_light_green_lawn():
    """Trail strokes should be the same color as the lawn baseline so the
    'mowed area becomes light green' visual works."""
    assert _DEFAULT_PALETTE["mow_trail_color"] == (178, 223, 138, 255)


def test_mow_trail_thin_color_dark_green_alpha():
    """Thin mode in the replay card uses dark-green α220 for visibility
    of individual passes."""
    assert _DEFAULT_PALETTE["mow_trail_thin_color"] == (50, 100, 30, 220)


def test_traversal_color_medium_grey():
    """Dock-return / cross-map traversal rendered in muted grey, drawn
    last so it stays on top."""
    assert _DEFAULT_PALETTE["traversal_color"] == (130, 130, 130, 220)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/protocol/test_map_render_palette.py -v
```
Expected: 4 FAIL — keys missing from `_DEFAULT_PALETTE`.

- [ ] **Step 3: Add the keys to `_DEFAULT_PALETTE`**

In `map_render.py`, just before the closing `}` of `_DEFAULT_PALETTE` (right after the `mp_text` line):

```python
    # ------ Phase 1 (2026-05-17 render-styling refresh) ------
    # Dark green — alias of zone_outline RGB but used as a fill color in
    # the pre-mow / cutting-target / active-mow-background contexts.
    "dark_green": (100, 160, 70, 255),
    # Mowing trail strokes — same RGB as lawn (light-green); a session's
    # mowed area visually merges with the lawn baseline when on top of
    # dark_green backgrounds.
    "mow_trail_color": (178, 223, 138, 255),
    # Thin-mode mowing trail — used by the replay card's "thin" toggle so
    # individual passes stand out. Dark green α220 for high contrast on
    # the light-green lawn.
    "mow_trail_thin_color": (50, 100, 30, 220),
    # Traversal segments (dock-return / cross-map navigation). Drawn LAST
    # in render_with_trail so it stays visible over mowing strokes.
    "traversal_color": (130, 130, 130, 220),
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/protocol/test_map_render_palette.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py tests/protocol/test_map_render_palette.py
git commit -m "map_render: add palette keys for Phase 1 render-styling refresh"
```

---

## Task 2: Bump lawn opacity + recolor ignore-obstacle zones

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` (`_DEFAULT_PALETTE`: `zone_fills[0]`, `ignore_fill`, `ignore_outline`)
- Test: `tests/protocol/test_map_render_palette.py` (extend)

- [ ] **Step 1: Append failing tests**

Append to `tests/protocol/test_map_render_palette.py`:

```python
def test_zone_fills_lawn_opaque():
    """The primary lawn fill (zone 0) is fully opaque so the bbox-grey
    background never bleeds through. Pre-refresh value was α200."""
    assert _DEFAULT_PALETTE["zone_fills"][0] == (178, 223, 138, 255)


def test_ignore_fill_blueish_green():
    """Ignore-obstacle zones recoloured to semi-transparent blueish-green
    to match the Dreame app. Pre-refresh value was greenish (0,177,0,50)."""
    assert _DEFAULT_PALETTE["ignore_fill"] == (90, 140, 230, 90)


def test_ignore_outline_blueish_green():
    assert _DEFAULT_PALETTE["ignore_outline"] == (60, 110, 200, 220)
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/protocol/test_map_render_palette.py -v
```
Expected: 3 new tests FAIL (lawn α=200 not 255; ignore is greenish, not blueish).

- [ ] **Step 3: Apply the palette edits**

In `map_render.py`, change the existing keys:

```python
    "zone_fills": [
        (178, 223, 138, 255),   # zone 0: light grass-green (was α200)
        (249, 224, 125, 200),   # zone 1: warm yellow-green
        (184, 227, 255, 200),   # zone 2: light blue
        (184, 217, 141, 200),   # zone 3: muted green
    ],
```

```python
    "ignore_fill": (90, 140, 230, 90),
    "ignore_outline": (60, 110, 200, 220),
```

- [ ] **Step 4: Run all palette tests**

```bash
python3 -m pytest tests/protocol/test_map_render_palette.py -v
```
Expected: 7 PASS.

- [ ] **Step 5: Run broader render tests to check no regressions**

```bash
python3 -m pytest tests/protocol -q --tb=line 2>&1 | tail -5
```
Expected: all pass. If a pixel-sampling test asserted the old `(0, 177, 0, 50)` color for ignore zones, update it to the new blueish value — that test was pinning a color choice, not a behavior.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py tests/protocol/test_map_render_palette.py
git commit -m "map_render: lawn fully opaque + ignore-obstacle zones recoloured blueish-green (matches app)"
```

---

## Task 3: Pure trail-segment splitter

**Files:**
- Create: `custom_components/dreame_a2_mower/_render_trail_split.py`
- Test: `tests/unit/test_render_trail_split.py` (NEW)

The splitter takes the union of `_local_legs` (full motion) + cloud `track_segments` (mowing-only) and returns two lists: mowing-points and traversal-points. Pure-Python, no HA, no PIL. Reusable from the static renderer + the replay card's preprocessing.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_render_trail_split.py`:

```python
"""Pure splitter — local legs union cloud track-segments → (mowing, traversal)."""
from custom_components.dreame_a2_mower._render_trail_split import split_trail


def test_no_local_legs_all_cloud_mowing():
    """If only cloud segments exist (older session), everything is mowing."""
    mowing, traversal = split_trail(
        local_legs=[],
        cloud_segments=[[(0.0, 0.0), (1.0, 1.0)]],
    )
    assert mowing == [[(0.0, 0.0), (1.0, 1.0)]]
    assert traversal == []


def test_no_cloud_all_local_traversal():
    """If only local legs exist (cloud truncated), everything is traversal —
    we cannot tell what was mowing vs not, so default to grey."""
    mowing, traversal = split_trail(
        local_legs=[[(0.0, 0.0), (1.0, 1.0)]],
        cloud_segments=[],
    )
    assert mowing == []
    assert traversal == [[(0.0, 0.0), (1.0, 1.0)]]


def test_local_points_overlapping_cloud_are_mowing():
    """Local legs that touch cloud segments are reclassified as mowing —
    the cloud is authoritative about what counts as a cut."""
    local = [[(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]]
    cloud = [[(0.0, 0.0), (1.0, 1.0)]]
    mowing, traversal = split_trail(local_legs=local, cloud_segments=cloud)
    # The first two points overlap cloud → mowing; the third (2,2) doesn't → traversal.
    # split_trail's contract: contiguous overlapping runs go into mowing;
    # the post-overlap tail becomes a traversal segment starting from the
    # last mowing point (so the visual line is continuous).
    assert mowing == [[(0.0, 0.0), (1.0, 1.0)]]
    assert traversal == [[(1.0, 1.0), (2.0, 2.0)]]


def test_dock_return_at_end_is_traversal():
    """Realistic case: mow a leg, then drive back to dock at end."""
    local = [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (5.0, 5.0)]]
    cloud = [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]
    mowing, traversal = split_trail(local_legs=local, cloud_segments=cloud)
    assert mowing == [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]
    assert traversal == [[(2.0, 0.0), (5.0, 5.0)]]


def test_multiple_legs_handled_independently():
    local = [
        [(0.0, 0.0), (1.0, 0.0), (10.0, 10.0)],
        [(20.0, 20.0), (21.0, 20.0), (30.0, 30.0)],
    ]
    cloud = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(20.0, 20.0), (21.0, 20.0)],
    ]
    mowing, traversal = split_trail(local_legs=local, cloud_segments=cloud)
    assert len(mowing) == 2
    assert len(traversal) == 2
    assert traversal[0] == [(1.0, 0.0), (10.0, 10.0)]
    assert traversal[1] == [(21.0, 20.0), (30.0, 30.0)]


def test_point_match_tolerance():
    """Local point within 1cm (10mm) of a cloud point is treated as the same."""
    local = [[(0.0, 0.0), (1000.005, 1000.005), (2000.0, 2000.0)]]  # mm coords
    cloud = [[(0.0, 0.0), (1000.0, 1000.0)]]
    mowing, traversal = split_trail(local_legs=local, cloud_segments=cloud, tol_mm=10.0)
    # The (1000.005, 1000.005) local point should be matched to (1000, 1000) cloud point.
    assert mowing == [[(0.0, 0.0), (1000.005, 1000.005)]]
    assert traversal == [[(1000.005, 1000.005), (2000.0, 2000.0)]]
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/unit/test_render_trail_split.py -v
```
Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Implement the splitter**

Create `custom_components/dreame_a2_mower/_render_trail_split.py`:

```python
"""Pure splitter: local trail legs ∪ cloud mowing segments → (mowing, traversal).

The integration captures TWO views of motion:
- ``_local_legs``: full per-tick s1p4 trail samples; includes dock-return,
  cross-map traversal, AND mowing strokes.
- cloud ``track_segments``: cloud-curated, mowing-only fragments.

The render layers want to draw mowing strokes in light green and
traversal in grey-on-top. This module classifies each local-leg point
as mowing (overlaps the cloud) or traversal (doesn't), preserving
visual continuity at the boundary.
"""
from __future__ import annotations

from typing import Iterable


def _build_cloud_point_set(
    cloud_segments: Iterable[Iterable[tuple[float, float]]],
    tol_mm: float,
) -> set[tuple[int, int]]:
    """Index cloud points into a tolerance-quantized hash set for O(1) lookup."""
    out: set[tuple[int, int]] = set()
    if not cloud_segments:
        return out
    q = max(1.0, tol_mm)
    for seg in cloud_segments:
        for x, y in seg:
            out.add((int(x / q), int(y / q)))
    return out


def _point_in_cloud(pt: tuple[float, float], cloud_set: set, tol_mm: float) -> bool:
    if not cloud_set:
        return False
    q = max(1.0, tol_mm)
    return (int(pt[0] / q), int(pt[1] / q)) in cloud_set


def split_trail(
    *,
    local_legs: list[list[tuple[float, float]]],
    cloud_segments: list[list[tuple[float, float]]],
    tol_mm: float = 10.0,
) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
    """Return (mowing_segments, traversal_segments).

    Decision rules:
    - No local legs → every cloud segment is mowing.
    - No cloud segments → every local leg is traversal (cloud is the
      authoritative "this was a cut" signal; without it we can't tell).
    - Otherwise: walk each local leg, mark each point as cloud-or-not,
      split into contiguous mowing runs and contiguous non-cloud runs.
      Non-cloud runs prepend the last mowing point as their start so the
      visual line stays continuous at the boundary.
    """
    if not local_legs:
        return ([list(s) for s in cloud_segments], [])
    if not cloud_segments:
        return ([], [list(leg) for leg in local_legs])

    cloud_set = _build_cloud_point_set(cloud_segments, tol_mm)
    mowing: list[list[tuple[float, float]]] = []
    traversal: list[list[tuple[float, float]]] = []

    for leg in local_legs:
        if not leg:
            continue
        cur_mode: bool | None = None  # True=mowing, False=traversal
        cur_run: list[tuple[float, float]] = []
        last_mowing_pt: tuple[float, float] | None = None

        for pt in leg:
            is_mow = _point_in_cloud(pt, cloud_set, tol_mm)
            if cur_mode is None:
                cur_mode = is_mow
                cur_run = [pt]
                if is_mow:
                    last_mowing_pt = pt
                continue
            if is_mow == cur_mode:
                cur_run.append(pt)
                if is_mow:
                    last_mowing_pt = pt
                continue
            # Mode flip — flush current run, start new one.
            if cur_mode:
                mowing.append(cur_run)
            else:
                traversal.append(cur_run)
            # Bridge: traversal runs always start from the previous
            # mowing point (visual continuity); mowing runs start fresh.
            if is_mow:
                cur_run = [pt]
                last_mowing_pt = pt
            else:
                cur_run = [last_mowing_pt, pt] if last_mowing_pt else [pt]
            cur_mode = is_mow
        # Flush the final run.
        if cur_mode is True:
            mowing.append(cur_run)
        elif cur_mode is False:
            traversal.append(cur_run)

    return mowing, traversal
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/unit/test_render_trail_split.py -v
```
Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_render_trail_split.py tests/unit/test_render_trail_split.py
git commit -m "_render_trail_split: pure helper to classify local-leg points as mowing vs traversal"
```

---

## Task 4: Use the splitter in `render_with_trail`

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` (`render_with_trail` around line 596)
- Test: `tests/protocol/test_render_traversal_visible.py` (NEW)

- [ ] **Step 1: Find the current trail-drawing block**

```bash
grep -n "_TRAIL_COLOR\|_TRAIL_LINE_WIDTH\|render_with_trail\|draw\.line.*trail\|draw_trail" custom_components/dreame_a2_mower/map_render.py | head -10
```

Read `render_with_trail` and the trail-drawing block it contains. Note the current signature — it likely takes `legs`, `cloud_segments` (or similar) and renders one combined color.

- [ ] **Step 2: Write the failing integration test**

Create `tests/protocol/test_render_traversal_visible.py`:

```python
"""End-to-end: render_with_trail draws mowing in light-green and traversal in grey."""
from PIL import Image
from custom_components.dreame_a2_mower.map_render import (
    render_with_trail, _DEFAULT_PALETTE,
)
from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone


def _tiny_map() -> MapData:
    """Build a 10m × 10m map with a single mowing zone."""
    return MapData(
        bx1=0, by1=0, bx2=10000, by2=10000,
        pixel_size_mm=50,
        boundary_path=((0, 0), (10000, 0), (10000, 10000), (0, 10000)),
        mowing_zones=(
            MowingZone(zone_id=0, name="lawn", path=((0, 0), (10000, 0), (10000, 10000), (0, 10000)), area_m2=100.0),
        ),
    )


def _collect_pixels(png_bytes: bytes) -> set[tuple[int, int, int, int]]:
    img = Image.open(__import__("io").BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


def test_traversal_color_appears_when_local_leg_extends_past_cloud():
    """Cloud has a short mowing segment; local leg continues past it (dock return).
    The post-cloud points must render in traversal_color, not mow_trail_color."""
    cloud = [[(2000.0, 5000.0), (4000.0, 5000.0)]]
    local = [[(2000.0, 5000.0), (4000.0, 5000.0), (8000.0, 8000.0)]]

    png = render_with_trail(
        _tiny_map(), local_legs=local, cloud_segments=cloud,
    )
    px = _collect_pixels(png)

    grey = _DEFAULT_PALETTE["traversal_color"]
    light = _DEFAULT_PALETTE["mow_trail_color"]
    assert grey in px, f"expected traversal_color {grey} pixels"
    assert light in px, f"expected mow_trail_color {light} pixels"


def test_no_traversal_when_local_matches_cloud_exactly():
    cloud = [[(2000.0, 5000.0), (4000.0, 5000.0)]]
    local = [[(2000.0, 5000.0), (4000.0, 5000.0)]]
    png = render_with_trail(
        _tiny_map(), local_legs=local, cloud_segments=cloud,
    )
    px = _collect_pixels(png)
    grey = _DEFAULT_PALETTE["traversal_color"]
    assert grey not in px, "no traversal points expected when local == cloud"
```

If `MapData`/`MowingZone` signatures in the actual codebase differ, adapt — read `custom_components/dreame_a2_mower/map_decoder.py` for the real fields.

- [ ] **Step 3: Run failing**

```bash
python3 -m pytest tests/protocol/test_render_traversal_visible.py -v
```
Expected: FAIL — `render_with_trail` doesn't accept `local_legs` separately yet, or paints both in `_TRAIL_COLOR`.

- [ ] **Step 4: Update `render_with_trail`**

Edit `map_render.py`. The new signature accepts `local_legs` and `cloud_segments` explicitly (deprecating any single `legs` kwarg). Inside:

```python
from ._render_trail_split import split_trail

def render_with_trail(
    map_data,
    local_legs=None,
    cloud_segments=None,
    palette=None,
    obstacles=None,
    **legacy_kwargs,  # back-compat for older callers
):
    """Render map + trail. Splits local_legs / cloud_segments into mowing
    (light-green) and traversal (grey, drawn last on top)."""
    base = render_base_map(map_data, palette=palette)
    p = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)

    # Back-compat: if a caller passes the old `legs` kwarg, treat as cloud.
    if cloud_segments is None and "legs" in legacy_kwargs:
        cloud_segments = legacy_kwargs["legs"]
    cloud_segments = cloud_segments or []
    local_legs = local_legs or []

    mowing, traversal = split_trail(
        local_legs=local_legs, cloud_segments=cloud_segments,
    )

    img = Image.open(io.BytesIO(base)).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    # Mowing strokes first.
    mow_color = p.get("mow_trail_color", (178, 223, 138, 255))
    for seg in mowing:
        if len(seg) < 2:
            continue
        pts_px = [_cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm) for x, y in seg]
        draw.line(pts_px, fill=mow_color, width=_TRAIL_LINE_WIDTH)

    # Traversal LAST so it stays on top.
    trav_color = p.get("traversal_color", (130, 130, 130, 220))
    for seg in traversal:
        if len(seg) < 2:
            continue
        pts_px = [_cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm) for x, y in seg]
        draw.line(pts_px, fill=trav_color, width=_TRAIL_LINE_WIDTH)

    # Obstacles overlay (unchanged from prior implementation).
    if obstacles:
        for ob in obstacles:
            poly_px = [_cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm) for x, y in ob]
            draw.polygon(poly_px, fill=_OBSTACLE_FILL, outline=_OBSTACLE_OUTLINE)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

Adapt: keep any existing return-shape behaviour (e.g., if there's a `_PRECOMPUTED_PNG_CACHE` step the function does, preserve it). The intent is: replace the single trail loop with split + two loops + reordering.

Drop the `_TRAIL_COLOR` constant since nothing reads it anymore:

```python
# Delete:
# _TRAIL_COLOR: tuple[int, int, int, int] = (70, 70, 70, 220)
```

Leave `_TRAIL_LINE_WIDTH = 3` — used by both passes.

- [ ] **Step 5: Run new + existing tests**

```bash
python3 -m pytest tests/protocol -q --tb=line 2>&1 | tail -10
```
Expected: all pass. If a pre-existing test asserted `_TRAIL_COLOR` (e.g., color of trail pixels in a fixture), update it to assert `mow_trail_color` or `traversal_color` per the new contract.

- [ ] **Step 6: Update any callers passing the old single-list `legs` arg**

```bash
grep -rn "render_with_trail" custom_components/ tests/ 2>/dev/null | grep -v ":.*#" | head -10
```

For each call site:
- If the caller knows about both lists (e.g. coordinator session-end render), pass `local_legs=...` and `cloud_segments=...` explicitly.
- If the caller only has one list, pass it as `cloud_segments=...` (matches the old behavior of single-color-trail).
- The legacy_kwargs back-compat handles the old `legs=...` style for any third-party code.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py tests/protocol/test_render_traversal_visible.py
git commit -m "render_with_trail: split mowing vs traversal trails; traversal drawn last in grey"
```

---

## Task 5: Dark-green lawn background for completed/active mow sessions

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` (`render_base_map`)
- Test: `tests/protocol/test_render_dark_green_base.py` (NEW)

The doc says: during/after a mow, the lawn shows dark-green wherever the mower didn't reach. `render_base_map` currently always paints lawn in light-green (zone_fills[0]). Add a `lawn_mode` kwarg: `"light"` (default, idle baseline) or `"dark"` (post-mow / active-mow visual).

- [ ] **Step 1: Write the failing test**

Create `tests/protocol/test_render_dark_green_base.py`:

```python
"""render_base_map honors lawn_mode=dark for active/finished mow render."""
import io
from PIL import Image
from custom_components.dreame_a2_mower.map_render import (
    render_base_map, _DEFAULT_PALETTE,
)
from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone


def _tiny_map():
    return MapData(
        bx1=0, by1=0, bx2=10000, by2=10000, pixel_size_mm=50,
        boundary_path=((0, 0), (10000, 0), (10000, 10000), (0, 10000)),
        mowing_zones=(
            MowingZone(zone_id=0, name="lawn", path=((0, 0), (10000, 0), (10000, 10000), (0, 10000)), area_m2=100.0),
        ),
    )


def _has_color(png_bytes, rgba):
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return rgba in set(img.getdata())


def test_default_lawn_mode_light_green():
    png = render_base_map(_tiny_map())
    assert _has_color(png, _DEFAULT_PALETTE["zone_fills"][0])  # light green


def test_lawn_mode_dark_uses_dark_green():
    png = render_base_map(_tiny_map(), lawn_mode="dark")
    assert _has_color(png, _DEFAULT_PALETTE["dark_green"])


def test_lawn_mode_light_explicit_same_as_default():
    a = render_base_map(_tiny_map())
    b = render_base_map(_tiny_map(), lawn_mode="light")
    assert a == b
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/protocol/test_render_dark_green_base.py -v
```
Expected: 2 FAIL (default+light pass; dark fails — kwarg not accepted).

- [ ] **Step 3: Wire `lawn_mode` through `render_base_map`**

In `render_base_map`, after the `p = dict(_DEFAULT_PALETTE); ...` lines, replace `zone_fills[0]` based on `lawn_mode`:

```python
def render_base_map(
    map_data,
    palette=None,
    lawn_mode: str = "light",  # "light" (idle) or "dark" (active/post-mow)
):
    p: dict = dict(_DEFAULT_PALETTE)
    if palette:
        p.update(palette)
    if lawn_mode == "dark":
        # Override the primary zone fill so the lawn polygon paints dark green.
        # Trail strokes in mow_trail_color (light green) will overlay where mowed.
        p["zone_fills"] = [p["dark_green"]] + list(p["zone_fills"][1:])
    # ... rest of render_base_map unchanged
```

Also wire the kwarg through `render_with_trail` and `render_main_view` and `render_work_log`:

```python
def render_with_trail(map_data, *, local_legs=None, cloud_segments=None,
                     palette=None, obstacles=None, lawn_mode="dark", **legacy_kwargs):
    # ... lawn_mode default is "dark" because if you're rendering a trail
    # you're showing a mow session, completed or in-progress.
    base = render_base_map(map_data, palette=palette, lawn_mode=lawn_mode)
    # ... rest
```

`render_main_view` (live camera) and `render_work_log` (static archive) similarly default `lawn_mode="dark"` since both are mow-context renders.

- [ ] **Step 4: Run all render tests**

```bash
python3 -m pytest tests/protocol -q --tb=line 2>&1 | tail -5
```
Expected: all pass. If a pre-existing test pinned the lawn color in a work_log scenario, it now sees dark-green instead — update it to expect `_DEFAULT_PALETTE["dark_green"]`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py tests/protocol/test_render_dark_green_base.py
git commit -m "render_base_map: lawn_mode kwarg; dark-green base for active/completed mow renders"
```

---

## Task 6 — Cut P1 release

**Files:** none (release.sh handles bump + tag + push + GitHub release + HACS refresh)

- [ ] **Step 1: Confirm tests pass**

```bash
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5
```
Expected: all pass; suite under ~60s.

- [ ] **Step 2: Run release.sh**

```bash
bash tools/release.sh --notes "$(cat <<'EOF'
v1.0.15aN: P1 of render-styling refresh

- Palette: light-green lawn opaque + new dark_green/mow_trail/traversal keys
- Ignore-obstacle zones now blueish-green semi-transparent (matches app)
- Trail rendering splits cloud mowing strokes (light green) from local-only
  traversal points (grey, drawn LAST so dock-return arcs stay visible)
- render_base_map lawn_mode='dark' for mow-context renders so the visual is
  dark-green background + light-green where mowed (post-Phase 1 of design)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Verify HACS refresh ping**

Look for `✅ release vX.Y.ZaN published cleanly.` + `HACS refresh: {...success:true...}` in release.sh output. If absent, investigate before declaring done.

---

# Phase 2 — Animation engine + fat/thin toggle

JS work on `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`. Manual visual validation; no Python tests cover animation engine.

## Task 7: Fat/thin toggle button + localStorage

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

- [ ] **Step 1: Read existing card setup**

```bash
grep -n "play\|pause\|button\|querySelector\|getElementById\|_pathLengths\|_paths" custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js | head -30
```

Identify where the play/pause buttons live in the rendered DOM (probably inside the SVG header or a control row above/below). Note the current stroke-width value (likely hardcoded `3` in the template literal).

- [ ] **Step 2: Add the toggle button + state**

In the constructor or `setConfig`:

```javascript
this._renderStyle = localStorage.getItem(
  `dreame_replay_render_style:${this._cameraEntityId}`
) || 'fat';
```

In the rendered HTML (find the play/pause row, add adjacent button):

```html
<button id="style-toggle" class="ctrl-btn" title="Toggle render style">
  <svg width="24" height="24"><!-- two-circle icon or "F/T" text --></svg>
</button>
```

In the wiring section (where play/pause click handlers are bound):

```javascript
const styleBtn = this.shadowRoot.getElementById('style-toggle');
styleBtn.addEventListener('click', () => {
  this._renderStyle = this._renderStyle === 'fat' ? 'thin' : 'fat';
  localStorage.setItem(
    `dreame_replay_render_style:${this._cameraEntityId}`,
    this._renderStyle
  );
  this._applyRenderStyle();
});
```

- [ ] **Step 3: Apply the style to the SVG paths**

```javascript
_applyRenderStyle() {
  const fatWidthPx = Math.max(8, Math.round(this._pixelsPerMm * 220));  // 22cm blade ≈
  const thinWidthPx = 3;
  const fatColor = 'rgb(178, 223, 138)';           // mow_trail_color
  const thinColor = 'rgba(50, 100, 30, 0.86)';     // mow_trail_thin_color
  for (const p of this._paths) {
    if (this._renderStyle === 'fat') {
      p.style.stroke = fatColor;
      p.style.strokeWidth = fatWidthPx;
    } else {
      p.style.stroke = thinColor;
      p.style.strokeWidth = thinWidthPx;
    }
  }
  // Apply on initial render too — call from _renderAt's setup.
}
```

Call `_applyRenderStyle()` at the end of the SVG-path-build block (the one near line 331 that sets `strokeDasharray` and `strokeDashoffset`).

- [ ] **Step 4: Manual validation**

```bash
HOST=$(awk 'NR==1' /data/claude/homeassistant/ha-credentials.txt)
USER=$(awk 'NR==2' /data/claude/homeassistant/ha-credentials.txt)
PASS=$(awk 'NR==3' /data/claude/homeassistant/ha-credentials.txt)
sshpass -p "$PASS" scp -o StrictHostKeyChecking=no \
  custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js \
  "$USER@$HOST:/config/www/dreame-mower-replay-card.js"
```

Hard-reload the dashboard (`Ctrl+Shift+R`); confirm:
- Style button visible next to play/pause
- Default render = fat (wide light-green strokes)
- Click → flips to thin (narrow dark-green strokes)
- Page reload retains the last-chosen mode (localStorage)

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "replay-card: add fat/thin render-style toggle (localStorage-persisted, default fat)"
```

---

## Task 8: Icon-traverses-path animation (progressive reveal)

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js` (`_tick` + `_renderAt`)

The current engine teleports the icon between segment endpoints. Rewrite so the icon walks along each segment (using SVG `getPointAtLength`) and the stroke reveals progressively.

- [ ] **Step 1: Find the current animation loop**

```bash
grep -nA10 "_tick\|_renderAt" custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js | head -40
```

Note the structure:
- `_tick(now)`: requestAnimationFrame-driven; updates `_playheadMs`, calls `_renderAt`.
- `_renderAt(ms)`: iterates `_paths` array, sets `strokeDashoffset` per segment based on whether the playhead is before/after that segment's window. Sets the icon position to the segment's end (causing teleports).

- [ ] **Step 2: Rewrite `_renderAt` for progressive reveal**

Replace the per-segment loop body inside `_renderAt(ms)`:

```javascript
_renderAt(ms) {
  this._playheadMs = ms;
  const paths = this._paths;
  const starts = this._pathStartsMs;
  const ends = this._pathEndsMs;
  const lengths = this._pathLengths;
  const head = this.shadowRoot.getElementById('head');
  let iconX = null, iconY = null;

  for (let i = 0; i < paths.length; i++) {
    const p = paths[i];
    const sMs = starts[i];
    const eMs = ends[i];
    const len = lengths[i];
    if (ms <= sMs) {
      // Not yet started — full dash offset, hidden.
      p.style.strokeDashoffset = len;
      continue;
    }
    if (ms >= eMs) {
      // Fully drawn.
      p.style.strokeDashoffset = 0;
      continue;
    }
    // In-progress — progressive reveal.
    const t = (ms - sMs) / (eMs - sMs);  // 0..1
    p.style.strokeDashoffset = len * (1 - t);
    // Icon position = point at length t * len.
    const pt = p.getPointAtLength(t * len);
    iconX = pt.x;
    iconY = pt.y;
  }

  // If no segment is active, place icon at the end of the most-recent
  // completed segment (or the start of the next).
  if (iconX === null) {
    for (let i = paths.length - 1; i >= 0; i--) {
      if (ms >= ends[i]) {
        const pt = paths[i].getPointAtLength(lengths[i]);
        iconX = pt.x; iconY = pt.y; break;
      }
    }
  }
  if (iconX === null && paths.length > 0) {
    const pt = paths[0].getPointAtLength(0);
    iconX = pt.x; iconY = pt.y;
  }
  if (iconX !== null) {
    head.setAttribute('cx', iconX);
    head.setAttribute('cy', iconY);
  }
}
```

Note: this assumes `_pathStartsMs` / `_pathEndsMs` are already populated per-segment (they are — that's how the old teleport version knew when each segment "fires"). The change is replacing the binary on/off offset with a smooth `len * (1 - t)`, and using `getPointAtLength(t * len)` for the icon position.

- [ ] **Step 3: Manual validation**

SCP-deploy as in Task 7 Step 4. Replay a session; confirm:
- Icon moves smoothly along each segment, not teleporting
- Stroke fills in behind the icon as it moves
- Animation tempo matches before (no slowdown/speedup vs old engine)

- [ ] **Step 4: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "replay-card: icon-traverses-path + progressive stroke reveal (no more teleports)"
```

---

## Task 9: Charging-window dock snap

**Files:**
- Modify: `custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js`

When the playhead is inside a charging window (per session attributes), the icon should snap to the dock and freeze. Today the icon stays wherever the last segment ended (often mid-yard).

- [ ] **Step 1: Find the session-attribute access point**

```bash
grep -n "charging\|time_charging\|charge\|dock\|_dockX\|_dockY" custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js | head -10
```

The card reads session attributes (probably in `setConfig` or `hass` setter). Identify whether `charging_windows` or similar is already a parsed attribute; if not, this task also surfaces them.

- [ ] **Step 2: Parse charging windows on session-load**

In the session-load block:

```javascript
// Expect session attribute `state_samples` = [[ts_ms, code], ...] where
// code from sensor.charging_status_code_raw — 1 = CHARGING. Build [start, end]
// pairs for contiguous charging runs.
this._chargingWindowsMs = [];
const samples = this._sessionAttrs?.charging_status_samples || [];
const sessionStartUnix = this._sessionAttrs?.session_start_unix || 0;
let runStart = null;
for (const [tsUnix, code] of samples) {
  const ms = (tsUnix - sessionStartUnix) * 1000;
  if (code === 1 && runStart === null) runStart = ms;
  if (code !== 1 && runStart !== null) {
    this._chargingWindowsMs.push([runStart, ms]);
    runStart = null;
  }
}
if (runStart !== null) {
  this._chargingWindowsMs.push([runStart, this._totalAnimationMs]);
}
```

- [ ] **Step 3: Apply in `_renderAt`**

At the end of `_renderAt`, before the final icon-position write:

```javascript
const inCharging = this._chargingWindowsMs.some(
  ([s, e]) => ms >= s && ms <= e,
);
if (inCharging) {
  // Snap to dock; freeze icon.
  iconX = this._dockPxX;
  iconY = this._dockPxY;
}
```

`_dockPxX` / `_dockPxY` come from the existing dock-position calculation (likely already used to draw the dock icon — verify by grepping).

- [ ] **Step 4: Manual validation**

Replay a session that included charging. Confirm icon visibly sits at the dock during charge windows instead of staying wherever the last mowing stroke ended.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/www/dreame-mower-replay-card.js
git commit -m "replay-card: snap icon to dock during charging windows (no more mid-lawn freeze)"
```

---

## Task 10 — Cut P2 release

- [ ] **Step 1: Confirm full suite**

```bash
python3 -m pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 2: Cut release**

```bash
bash tools/release.sh --notes "$(cat <<'EOF'
v1.0.15aN: P2 of render-styling refresh

- Replay-card fat/thin toggle (localStorage-persisted, default fat = app-style coverage)
- Icon traverses each segment smoothly with progressive stroke reveal (no more teleports)
- Charging windows snap the icon to the dock (no more mid-lawn freeze)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

# Phase 3 — Pre-start dynamic viz + direction tracking

Largest phase. Adds per-map state, finalize-time inference, and renderer dispatch for the idle preview.

## Task 11: Add `last_all_area_mow_direction_deg` to MowerState

**Files:**
- Modify: `custom_components/dreame_a2_mower/mower/state.py`
- Test: `tests/unit/test_mower_state_last_direction.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_mower_state_last_direction.py`:

```python
"""Per-map last mow direction tracking — new MowerState field for Phase 3."""
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_default_is_empty_dict():
    s = MowerState()
    assert s.last_all_area_mow_direction_deg == {}


def test_can_record_per_map():
    s = MowerState()
    s.last_all_area_mow_direction_deg[0] = 45
    s.last_all_area_mow_direction_deg[1] = 90
    assert s.last_all_area_mow_direction_deg == {0: 45, 1: 90}
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/unit/test_mower_state_last_direction.py -v
```
Expected: AttributeError on the new field.

- [ ] **Step 3: Add the field**

In `mower/state.py`, find a suitable section (probably near `action_mode` ~line 285):

```python
    # P3 of render-styling refresh: tracks the dominant mow direction
    # (degrees, 0..179) of the most recent ALL_AREAS or ZONE session per
    # map. Used by render_main_view to draw the pre-start stripe overlay
    # at the angle the next mow will use (per mowing_direction_mode).
    # None / missing-key = no prior mow recorded yet; renderer falls back
    # to 0° baseline.
    last_all_area_mow_direction_deg: dict[int, int] = field(default_factory=dict)
```

Make sure `field` is imported from `dataclasses` (it should be).

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/unit/test_mower_state_last_direction.py tests/ -q --tb=line 2>&1 | tail -5
```
Expected: 2 new tests pass; no regressions.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/mower/state.py tests/unit/test_mower_state_last_direction.py
git commit -m "MowerState: add per-map last_all_area_mow_direction_deg for stripe-overlay tracking"
```

---

## Task 12: Pure `infer_mow_direction` helper

**Files:**
- Create: `custom_components/dreame_a2_mower/_render_direction.py`
- Test: `tests/unit/test_render_direction.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
"""Infer dominant mow direction from cloud track_segments."""
from custom_components.dreame_a2_mower._render_direction import infer_mow_direction


def test_horizontal_passes_return_zero():
    """Straight east-west mowing (along the X axis) → 0 degrees."""
    segs = [
        [(0.0, 0.0), (10000.0, 0.0)],
        [(0.0, 200.0), (10000.0, 200.0)],
        [(0.0, 400.0), (10000.0, 400.0)],
    ]
    assert infer_mow_direction(segs) == 0


def test_vertical_passes_return_ninety():
    segs = [
        [(0.0, 0.0), (0.0, 10000.0)],
        [(200.0, 0.0), (200.0, 10000.0)],
    ]
    assert infer_mow_direction(segs) == 90


def test_diagonal_45_returns_forty_five():
    segs = [
        [(0.0, 0.0), (10000.0, 10000.0)],
        [(200.0, 0.0), (10200.0, 10000.0)],
    ]
    assert infer_mow_direction(segs) == 45


def test_returns_none_for_no_qualifying_segments():
    """Empty or all-too-short segments → None (renderer falls back to 0°)."""
    assert infer_mow_direction([]) is None
    assert infer_mow_direction([[(0.0, 0.0), (10.0, 10.0)]]) is None  # below MIN_SEGMENT_M


def test_result_in_0_to_179_inclusive():
    """135° vs 315° are the SAME stripe direction — reduce mod 180."""
    segs = [
        [(10000.0, 0.0), (0.0, 10000.0)],  # heading northwest = 135°
    ]
    assert infer_mow_direction(segs) == 135


def test_circular_mean_weighted_by_segment_length():
    """A long horizontal and a short diagonal: result should lean horizontal."""
    segs = [
        [(0.0, 0.0), (20000.0, 0.0)],     # length 20m, direction 0°
        [(0.0, 0.0), (1000.0, 1000.0)],   # length ≈1.4m, direction 45°
    ]
    d = infer_mow_direction(segs)
    assert 0 <= d <= 15, f"long horizontal should dominate; got {d}"
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/unit/test_render_direction.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `custom_components/dreame_a2_mower/_render_direction.py`:

```python
"""Infer dominant mow direction from cloud track_segments.

The direction is used to render the pre-start stripe overlay (P3 of
render-styling design). Pure function: takes mm-coord segments, returns
degrees in [0, 180) or None.
"""
from __future__ import annotations

import math

MIN_SEGMENT_M: float = 0.5  # 50cm — below this, segment is too short to be a "pass"


def infer_mow_direction(
    track_segments: list[list[tuple[float, float]]],
) -> int | None:
    """Length-weighted circular mean of segment directions (mod 180).

    Segments below MIN_SEGMENT_M are ignored.
    """
    sin_sum = 0.0
    cos_sum = 0.0
    weight_sum = 0.0
    for seg in track_segments:
        if len(seg) < 2:
            continue
        # Net displacement from first to last point of the segment.
        x0, y0 = seg[0]
        x1, y1 = seg[-1]
        dx = x1 - x0
        dy = y1 - y0
        length_m = math.hypot(dx, dy) / 1000.0
        if length_m < MIN_SEGMENT_M:
            continue
        # Direction mod 180 — multiply angle by 2 so 0° and 180° collapse,
        # take the circular mean, then halve at the end.
        angle = math.atan2(dy, dx)  # -pi..pi
        if angle < 0:
            angle += math.pi  # collapse to [0, pi)
        doubled = 2 * angle
        sin_sum += math.sin(doubled) * length_m
        cos_sum += math.cos(doubled) * length_m
        weight_sum += length_m
    if weight_sum == 0:
        return None
    mean_doubled = math.atan2(sin_sum, cos_sum)
    if mean_doubled < 0:
        mean_doubled += 2 * math.pi
    mean = mean_doubled / 2  # back to [0, pi)
    return int(round(math.degrees(mean))) % 180
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/unit/test_render_direction.py -v
```
Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_render_direction.py tests/unit/test_render_direction.py
git commit -m "_render_direction: infer dominant mow direction from cloud segments (length-weighted mod-180)"
```

---

## Task 13: Pure `next_direction` helper for mode transitions

**Files:**
- Modify: `custom_components/dreame_a2_mower/_render_direction.py` (add helper)
- Test: `tests/unit/test_render_direction.py` (extend)

- [ ] **Step 1: Append failing tests**

```python
import pytest
from custom_components.dreame_a2_mower._render_direction import next_direction


@pytest.mark.parametrize("mode,last,expected", [
    # Striped (0) — same as last
    (0, 0, 0), (0, 45, 45), (0, 90, 90), (0, 135, 135),
    # Crisscross (1) — last + 45 mod 180
    (1, 0, 45), (1, 45, 90), (1, 90, 135), (1, 135, 0),
    # Chequerboard (2) — last + 90 mod 180
    (2, 0, 90), (2, 45, 135), (2, 90, 0), (2, 135, 45),
])
def test_next_direction_table(mode, last, expected):
    assert next_direction(last_direction_deg=last, mode=mode) == expected


def test_next_direction_none_last_returns_zero():
    """First mow ever → no prior direction → default 0°."""
    assert next_direction(last_direction_deg=None, mode=0) == 0
    assert next_direction(last_direction_deg=None, mode=1) == 0
    assert next_direction(last_direction_deg=None, mode=2) == 0


def test_next_direction_unknown_mode_treated_as_same():
    assert next_direction(last_direction_deg=45, mode=99) == 45
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/unit/test_render_direction.py -v
```
Expected: ImportError on `next_direction`.

- [ ] **Step 3: Implement**

Append to `_render_direction.py`:

```python
# Mowing pattern mode values (per select.py:1624 DreameA2PerMapMowingDirectionModeSelect._OPTIONS):
#   0 = "Striped"     → same direction as last
#   1 = "Crisscross"  → last + 45° (mod 180)
#   2 = "Chequerboard"→ last + 90° (mod 180)
MOWING_PATTERN_STRIPED = 0
MOWING_PATTERN_CRISSCROSS = 1
MOWING_PATTERN_CHEQUER = 2


def next_direction(
    *,
    last_direction_deg: int | None,
    mode: int | None,
) -> int:
    """Compute the next mow stripe direction in degrees [0, 180)."""
    if last_direction_deg is None:
        return 0
    if mode == MOWING_PATTERN_CRISSCROSS:
        return (last_direction_deg + 45) % 180
    if mode == MOWING_PATTERN_CHEQUER:
        return (last_direction_deg + 90) % 180
    # Striped (or unknown) — same as last.
    return last_direction_deg
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/unit/test_render_direction.py -v
```
Expected: 13/13 PASS (6 prior + 7 new param + 1 unknown).

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_render_direction.py tests/unit/test_render_direction.py
git commit -m "_render_direction: next_direction helper for mowing-pattern mode transitions"
```

---

## Task 14: Wire `infer_mow_direction` into session-finalize

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` (`_do_oss_fetch`)
- Test: `tests/integration/test_finalize_records_last_direction.py` (NEW)

After a cloud OSS fetch lands and the session is archived, run `infer_mow_direction` on the parsed track_segments and write to `MowerState.last_all_area_mow_direction_deg[map_id]` — but ONLY if the session was ALL_AREAS or ZONE (not edge, not spot).

- [ ] **Step 1: Locate the post-fetch state update**

```bash
grep -n "track_segments\|_do_oss_fetch\|session_archive.archive\|async_set_updated_data" custom_components/dreame_a2_mower/coordinator/_session.py | head -10
```

Note the spot where the parsed cloud summary's track_segments are available alongside the action_mode in scope.

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration/test_finalize_records_last_direction.py`:

```python
"""After a successful ALL_AREAS or ZONE finalize, last_all_area_mow_direction_deg
is updated for that map. Edge/spot finalizes do NOT touch it."""
import asyncio
import json
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.mower.state import MowerState, ActionMode


# Reuse the same _make_coordinator_for_finalize_tests helper from test_coordinator.py
import sys
sys.path.insert(0, "tests/integration")
from test_coordinator import _make_coordinator_for_finalize_tests  # noqa: E402


def _make_summary_with_track(angle_deg: int) -> dict:
    """Build a minimal cloud-summary dict with one track_segment at angle_deg."""
    import math
    a = math.radians(angle_deg)
    dx = 10000 * math.cos(a)
    dy = 10000 * math.sin(a)
    return {
        "version": 1,
        "map_id": 0,
        "md5": "abc",
        "track_segments": [[[0.0, 0.0], [dx, dy]]],
        "obstacles": [],
        # Other fields the archive expects — fill minimally.
    }


def test_finalize_all_areas_writes_last_direction():
    raw = json.dumps(_make_summary_with_track(90)).encode()
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/s.json",
        pending_first_attempt_unix=1_700_000_000,
        cloud_get_file_return=raw,
    )
    coord.data.action_mode = ActionMode.ALL_AREAS
    coord._active_map_id = 0
    coord.session_archive.count = 1

    asyncio.run(coord._do_oss_fetch(1_700_000_900))

    assert coord.data.last_all_area_mow_direction_deg.get(0) == 90


def test_finalize_edge_does_not_touch_last_direction():
    raw = json.dumps(_make_summary_with_track(45)).encode()
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/s.json",
        pending_first_attempt_unix=1_700_000_000,
        cloud_get_file_return=raw,
    )
    coord.data.action_mode = ActionMode.EDGE
    coord._active_map_id = 0
    coord.session_archive.count = 1

    asyncio.run(coord._do_oss_fetch(1_700_000_900))

    assert 0 not in coord.data.last_all_area_mow_direction_deg
```

Adapt if the cloud-summary parsing path uses different field names than `track_segments`.

- [ ] **Step 3: Run failing**

```bash
python3 -m pytest tests/integration/test_finalize_records_last_direction.py -v
```
Expected: both tests FAIL (field not updated yet).

- [ ] **Step 4: Wire the inference**

In `coordinator/_session.py`, inside `_do_oss_fetch` after the cloud summary has been parsed and successfully archived (look for `session_archive.archive(...)` or the success-path state update right after it):

```python
from .._render_direction import infer_mow_direction

if self.data.action_mode in (ActionMode.ALL_AREAS, ActionMode.ZONE):
    # Update per-map last-direction so the pre-start stripe overlay knows
    # what angle to draw for this map's next mow.
    segs = parsed_summary.get("track_segments") or []
    angle = infer_mow_direction(segs)
    if angle is not None and self._active_map_id is not None:
        new_map = dict(self.data.last_all_area_mow_direction_deg)
        new_map[int(self._active_map_id)] = angle
        new_state = dataclasses.replace(
            self.data, last_all_area_mow_direction_deg=new_map,
        )
        self.async_set_updated_data(new_state)
```

If `parsed_summary` is named differently, adapt. The intent: read whatever variable holds the cloud-decoded track_segments at this point.

`ActionMode` needs an import — `from ..mower.state import ActionMode` (or whatever the current import line is for that file).

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/integration/test_finalize_records_last_direction.py tests/ -q --tb=line 2>&1 | tail -5
```
Expected: 2 new tests pass; no regressions.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py tests/integration/test_finalize_records_last_direction.py
git commit -m "_do_oss_fetch: record per-map mow direction at finalize (only ALL_AREAS/ZONE)"
```

---

## Task 15: Persist `last_all_area_mow_direction_deg` across restarts

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator/_session.py` (`_persist_in_progress` + `_restore_in_progress` — actually the latter goes through `_restore_merge.merge_in_progress_payloads`)
- Modify: `custom_components/dreame_a2_mower/coordinator/_restore_merge.py` (extend merge to carry the new field)
- Test: `tests/state_machine/test_restore_merge.py` (extend)

- [ ] **Step 1: Confirm where in_progress.json is serialized**

```bash
grep -n "_persist_in_progress\|payload.*=\|write_in_progress" custom_components/dreame_a2_mower/coordinator/_session.py | head -10
```

Find the dict the persist code writes — it probably has `live_map.dump_to_payload()` plus a few coordinator-level fields. We need to add `last_all_area_mow_direction_deg` alongside.

- [ ] **Step 2: Extend the persist payload**

In `_persist_in_progress`, when building the dict, include:

```python
"last_all_area_mow_direction_deg": dict(self.data.last_all_area_mow_direction_deg),
```

In `_restore_in_progress` (after the merge), restore it:

```python
new_map = merged.get("last_all_area_mow_direction_deg") or {}
new_state = dataclasses.replace(
    self.data,
    last_all_area_mow_direction_deg={int(k): int(v) for k, v in new_map.items()},
)
self.async_set_updated_data(new_state)
```

- [ ] **Step 3: Extend the merge helper**

In `coordinator/_restore_merge.py`, the existing `merge_in_progress_payloads` returns a dict. Add handling for the new key (similar to `charge_at_start` / `settings_snapshot` — memory wins if set, fall back to disk):

```python
if "last_all_area_mow_direction_deg" in disk or "last_all_area_mow_direction_deg" in memory:
    mem_dict = memory.get("last_all_area_mow_direction_deg") or {}
    disk_dict = disk.get("last_all_area_mow_direction_deg") or {}
    # Merge per-map: disk has older entries, memory wins for overlapping keys.
    merged_map = {**disk_dict, **mem_dict}
    out["last_all_area_mow_direction_deg"] = merged_map
```

- [ ] **Step 4: Add merge test**

Append to `tests/state_machine/test_restore_merge.py`:

```python
def test_last_direction_merged_per_map_memory_wins_on_overlap():
    disk = {
        "session_start_ts": 100,
        "last_all_area_mow_direction_deg": {0: 45, 1: 90},
    }
    mem = {
        "session_start_ts": 100,
        "last_all_area_mow_direction_deg": {0: 135},  # overlap on map 0
    }
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["last_all_area_mow_direction_deg"] == {0: 135, 1: 90}


def test_last_direction_restored_from_disk_when_memory_empty():
    disk = {"session_start_ts": 100, "last_all_area_mow_direction_deg": {0: 45}}
    mem = {"session_start_ts": 100, "last_all_area_mow_direction_deg": {}}
    out = merge_in_progress_payloads(disk=disk, memory=mem)
    assert out["last_all_area_mow_direction_deg"] == {0: 45}
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/state_machine/test_restore_merge.py tests/ -q 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/dreame_a2_mower/coordinator/_session.py \
        custom_components/dreame_a2_mower/coordinator/_restore_merge.py \
        tests/state_machine/test_restore_merge.py
git commit -m "_persist/_restore_in_progress + _restore_merge: carry last_all_area_mow_direction_deg"
```

---

## Task 16: Pure `_compute_stripe_overlay` helper

**Files:**
- Create: `custom_components/dreame_a2_mower/_render_stripes.py`
- Test: `tests/protocol/test_render_stripes.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
"""Stripe overlay: alternating dark/light bands rotated to mow direction, clipped to lawn."""
import io
from PIL import Image
from custom_components.dreame_a2_mower._render_stripes import compute_stripe_overlay
from custom_components.dreame_a2_mower.map_render import _DEFAULT_PALETTE


def test_overlay_size_matches_canvas():
    """Returned overlay must be the same size as the canvas it'll composite onto."""
    overlay = compute_stripe_overlay(
        width=200, height=150, lawn_polygon_px=[(0, 0), (200, 0), (200, 150), (0, 150)],
        angle_deg=0, stripe_width_px=40,
        dark_color=_DEFAULT_PALETTE["dark_green"],
        light_color=_DEFAULT_PALETTE["zone_fills"][0],
    )
    assert overlay.size == (200, 150)


def test_overlay_horizontal_stripes_when_angle_zero():
    """angle=0 → horizontal stripes. Sample column at x=100: alternates dark/light."""
    overlay = compute_stripe_overlay(
        width=200, height=200,
        lawn_polygon_px=[(0, 0), (200, 0), (200, 200), (0, 200)],
        angle_deg=0, stripe_width_px=20,
        dark_color=(100, 160, 70, 255), light_color=(178, 223, 138, 255),
    )
    col = [overlay.getpixel((100, y)) for y in (0, 20, 40, 60)]
    # Three colors over four samples: first dark, then light, then dark...
    assert col[0] != col[1]  # different bands
    assert col[0] == col[2]  # same band 2 rows away


def test_overlay_clipped_to_polygon():
    """Outside the lawn polygon → transparent."""
    overlay = compute_stripe_overlay(
        width=200, height=200,
        lawn_polygon_px=[(50, 50), (150, 50), (150, 150), (50, 150)],
        angle_deg=0, stripe_width_px=20,
        dark_color=(100, 160, 70, 255), light_color=(178, 223, 138, 255),
    )
    assert overlay.getpixel((10, 10))[3] == 0  # transparent outside polygon
    assert overlay.getpixel((100, 100))[3] != 0  # opaque inside


def test_overlay_angle_45_diagonal_stripes():
    """angle=45 → stripes at 45° (top-left to bottom-right or vice versa)."""
    overlay = compute_stripe_overlay(
        width=200, height=200,
        lawn_polygon_px=[(0, 0), (200, 0), (200, 200), (0, 200)],
        angle_deg=45, stripe_width_px=20,
        dark_color=(100, 160, 70, 255), light_color=(178, 223, 138, 255),
    )
    # Along the diagonal (where stripes are PARALLEL to the sample direction),
    # the pixel stays the same band over a long stretch.
    a = overlay.getpixel((50, 50))
    b = overlay.getpixel((60, 60))
    assert a == b, "moving along the stripe direction should stay in the same band"
```

- [ ] **Step 2: Run failing**

```bash
python3 -m pytest tests/protocol/test_render_stripes.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `custom_components/dreame_a2_mower/_render_stripes.py`:

```python
"""Stripe overlay for pre-start mow visualization (P3 of render-styling design).

Renders alternating dark-green / light-green bands of `stripe_width_px`
oriented at `angle_deg` (from horizontal), clipped to the lawn polygon
on a transparent RGBA canvas of `width x height`. The caller composites
this overlay onto the base map.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw


def compute_stripe_overlay(
    *,
    width: int,
    height: int,
    lawn_polygon_px: list[tuple[float, float]],
    angle_deg: int,
    stripe_width_px: float,
    dark_color: tuple[int, int, int, int],
    light_color: tuple[int, int, int, int],
) -> Image.Image:
    """Return a transparent RGBA overlay with stripes clipped to the polygon."""
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    # Compute stripe bands in rotated coords:
    # 1. Project all polygon corners onto the unit vector PERPENDICULAR to
    #    the stripe direction → gives the projected-coordinate range.
    # 2. Walk the range in stripe_width_px increments, alternating colors,
    #    drawing a wide rectangle that we then mask with the polygon.
    angle_rad = math.radians(angle_deg)
    # Perpendicular direction: rotate stripe direction by 90°.
    perp_x = -math.sin(angle_rad)
    perp_y = math.cos(angle_rad)
    # Project polygon corners onto perp axis.
    perp_vals = [px * perp_x + py * perp_y for px, py in lawn_polygon_px]
    perp_min = min(perp_vals)
    perp_max = max(perp_vals)
    # Extend a bit beyond to fully cover boundary cells.
    perp_min -= stripe_width_px
    perp_max += stripe_width_px

    # Build a polygon mask (alpha 255 inside, 0 outside).
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.polygon(lawn_polygon_px, fill=255)

    # Diagonal long enough to cross the canvas no matter the angle.
    diag = int(math.hypot(width, height)) + 10

    # Stripe direction vector.
    stripe_dx = math.cos(angle_rad)
    stripe_dy = math.sin(angle_rad)

    n_bands = 0
    perp_pos = perp_min
    while perp_pos < perp_max:
        # Band center in canvas coords.
        cx = perp_pos * perp_x
        cy = perp_pos * perp_y
        # Four corners of a band: thick rectangle along stripe direction.
        cor1 = (cx - stripe_dx * diag, cy - stripe_dy * diag)
        cor2 = (cx + stripe_dx * diag, cy + stripe_dy * diag)
        cor3 = (cor2[0] + perp_x * stripe_width_px,
                cor2[1] + perp_y * stripe_width_px)
        cor4 = (cor1[0] + perp_x * stripe_width_px,
                cor1[1] + perp_y * stripe_width_px)
        color = dark_color if n_bands % 2 == 0 else light_color
        draw.polygon([cor1, cor2, cor3, cor4], fill=color)
        perp_pos += stripe_width_px
        n_bands += 1

    # Apply polygon mask: zero out alpha outside the lawn.
    r, g, b, a = overlay.split()
    a = Image.eval(a, lambda v: v)  # noop for type
    # Combine overlay alpha with polygon mask.
    a = Image.eval(a, lambda v: v)
    combined_alpha = Image.eval(mask, lambda v: v)
    overlay.putalpha(combined_alpha)
    return overlay
```

Note: stripe-mask math is fiddly; if the third test (clipped to polygon) fails, the issue is the final mask-application step. Verify the `putalpha(mask)` overrides per-pixel alpha correctly — alternatively use `Image.composite(stripe_layer, transparent, mask)` to apply the mask.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/protocol/test_render_stripes.py -v
```
Expected: 4/4 PASS. If stripe alignment math is off, iterate on the corner computation until tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/dreame_a2_mower/_render_stripes.py tests/protocol/test_render_stripes.py
git commit -m "_render_stripes: compute alternating dark/light stripe overlay clipped to lawn polygon"
```

---

## Task 17: Renderer dispatch for idle pre-start preview

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` (`render_main_view`)
- Test: `tests/protocol/test_render_main_view_idle.py` (NEW)

- [ ] **Step 1: Read current `render_main_view`**

```bash
grep -nA20 "def render_main_view" custom_components/dreame_a2_mower/map_render.py | head -30
```

It probably just delegates to `render_with_trail`. We're adding idle-state branching.

- [ ] **Step 2: Write the failing tests**

Create `tests/protocol/test_render_main_view_idle.py`:

```python
"""render_main_view: idle pre-start preview branches by action_mode."""
import io
from PIL import Image
from custom_components.dreame_a2_mower.map_render import (
    render_main_view, _DEFAULT_PALETTE,
)
from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.mower.state import MowerState, ActionMode
from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession


def _tiny_map():
    return MapData(
        bx1=0, by1=0, bx2=10000, by2=10000, pixel_size_mm=50,
        boundary_path=((0, 0), (10000, 0), (10000, 10000), (0, 10000)),
        mowing_zones=(
            MowingZone(zone_id=0, name="lawn",
                       path=((0, 0), (10000, 0), (10000, 10000), (0, 10000)),
                       area_m2=100.0),
        ),
    )


def _has_color(png_bytes, rgba):
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return rgba in set(img.getdata())


def test_idle_all_areas_shows_stripes():
    """Idle + ALL_AREAS → stripe overlay with both dark+light bands present."""
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(_tiny_map(), state=state, map_id=0,
                           mow_session=MowSession.IDLE)
    assert _has_color(png, _DEFAULT_PALETTE["dark_green"])
    assert _has_color(png, _DEFAULT_PALETTE["zone_fills"][0])  # light green


def test_idle_edge_all_light_green_no_dark():
    state = MowerState(action_mode=ActionMode.EDGE)
    png = render_main_view(_tiny_map(), state=state, map_id=0,
                           mow_session=MowSession.IDLE)
    assert _has_color(png, _DEFAULT_PALETTE["zone_fills"][0])  # light green
    # dark_green should not appear (other than maybe single-pixel boundary
    # outlines; we accept that). Use a count threshold instead:
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    dark_count = sum(1 for px in img.getdata() if px == _DEFAULT_PALETTE["dark_green"])
    assert dark_count < 100, "edge-mode preview should have very little dark-green"


def test_in_session_uses_trail_path():
    """Active mow uses the standard trail render, not the stripe overlay."""
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(_tiny_map(), state=state, map_id=0,
                           mow_session=MowSession.IN_SESSION)
    # Active path returns a dark-green base (per Task 5), no stripes.
    assert _has_color(png, _DEFAULT_PALETTE["dark_green"])
```

If `MowSession` doesn't have an `IDLE` member, substitute the actual idle-state member name from `mower/state_snapshot.py`.

- [ ] **Step 3: Run failing**

```bash
python3 -m pytest tests/protocol/test_render_main_view_idle.py -v
```
Expected: FAIL — `render_main_view` doesn't accept `state` / `mow_session` kwargs yet.

- [ ] **Step 4: Update `render_main_view`**

```python
from ._render_direction import next_direction
from ._render_stripes import compute_stripe_overlay

STRIPE_WIDTH_MM: int = 400  # tunable cosmetic; not literal blade width


def render_main_view(
    map_data,
    *,
    state=None,           # MowerState (optional — legacy callers pass None)
    map_id=0,
    mow_session=None,     # MowSession enum (optional)
    local_legs=None,
    cloud_segments=None,
    palette=None,
    obstacles=None,
):
    """Live-camera view. Idle: pre-start preview; In-session: trail render."""
    from .mower.state_snapshot import MowSession  # avoid circular import at module top

    if mow_session != MowSession.IN_SESSION and state is not None:
        from .mower.state import ActionMode
        mode = getattr(state, "action_mode", ActionMode.ALL_AREAS)
        if mode in (ActionMode.ALL_AREAS, ActionMode.ZONE):
            # Pre-start with stripes.
            last = state.last_all_area_mow_direction_deg.get(int(map_id))
            angle = next_direction(
                last_direction_deg=last,
                mode=state.settings_mowing_direction_mode,
            )
            base = render_base_map(map_data, palette=palette, lawn_mode="dark")
            # Compose stripe overlay onto base.
            from PIL import Image
            import io
            base_img = Image.open(io.BytesIO(base)).convert("RGBA")
            # Lawn polygon in pixel coords from the first mowing zone.
            mowing = map_data.mowing_zones[0] if map_data.mowing_zones else None
            if mowing is None:
                return base  # no zone → nothing to stripe
            poly_px = [
                _cloud_to_px(x, y, map_data.bx2, map_data.by2, map_data.pixel_size_mm)
                for x, y in mowing.path
            ]
            stripe_width_px = STRIPE_WIDTH_MM / map_data.pixel_size_mm
            overlay = compute_stripe_overlay(
                width=base_img.width, height=base_img.height,
                lawn_polygon_px=poly_px,
                angle_deg=angle, stripe_width_px=stripe_width_px,
                dark_color=_DEFAULT_PALETTE["dark_green"],
                light_color=_DEFAULT_PALETTE["zone_fills"][0],
            )
            composed = Image.alpha_composite(base_img, overlay)
            buf = io.BytesIO()
            composed.save(buf, format="PNG")
            return buf.getvalue()
        if mode in (ActionMode.EDGE, ActionMode.SPOT):
            # All-light-green base, no stripes.
            return render_base_map(map_data, palette=palette, lawn_mode="light")

    # In session, or legacy (no state passed) — use the trail renderer.
    return render_with_trail(
        map_data,
        local_legs=local_legs, cloud_segments=cloud_segments,
        palette=palette, obstacles=obstacles, lawn_mode="dark",
    )
```

- [ ] **Step 5: Run tests + suite**

```bash
python3 -m pytest tests/protocol/test_render_main_view_idle.py tests/ -q --tb=line 2>&1 | tail -5
```
Expected: 3 new tests pass; no regressions. If a pre-existing `render_main_view` test passed `state=None` (legacy callers), the new code's fallback to the trail-render path handles that.

- [ ] **Step 6: Update the live-camera entity caller**

```bash
grep -n "render_main_view\(" custom_components/dreame_a2_mower/ -rn 2>/dev/null | head -5
```

For the live camera's `_compute_native_value` (or wherever it calls render_main_view), pass `state=self.coordinator.data`, `map_id=...`, `mow_session=self.coordinator.state_machine.snapshot().mow_session`.

- [ ] **Step 7: Commit**

```bash
git add custom_components/dreame_a2_mower/map_render.py \
        tests/protocol/test_render_main_view_idle.py \
        custom_components/dreame_a2_mower/camera.py  # if the caller signature changed
git commit -m "render_main_view: idle pre-start preview (stripes for all_areas/zone, light-green for edge/spot)"
```

---

## Task 18: Cut P3 release

- [ ] **Step 1: Confirm full suite**

```bash
python3 -m pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 2: Cut release**

```bash
bash tools/release.sh --notes "$(cat <<'EOF'
v1.0.15aN: P3 of render-styling refresh — pre-start dynamic visualization

- New per-map MowerState field last_all_area_mow_direction_deg, inferred
  at session-finalize for ALL_AREAS/ZONE mows (length-weighted circular
  mean of cloud track segments).
- Persisted via in_progress.json + restore-merge across HA restarts.
- render_main_view dispatches on idle action_mode:
  * ALL_AREAS / ZONE → dark-green lawn + light-green stripes at the
    next mow direction (computed from last + mowing_pattern setting)
  * EDGE / SPOT → all-light-green lawn, no stripes
  * Active mow → existing trail render
- STRIPE_WIDTH_MM = 400 cosmetic tunable; revisit after seeing live.

Closes project_render_styling_todo.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage**: every section in the spec maps to at least one task:
  - Palette refresh → T1, T2
  - Traversal split → T3, T4
  - Dark-green active/post-mow base → T5
  - Fat/thin toggle → T7
  - Icon-traverse animation → T8
  - Charging-window snap → T9
  - Direction state + tracking → T11, T12, T13, T14, T15
  - Stripe overlay → T16
  - Render dispatch → T17
  - Maintenance points → already rendered in the codebase (verified during brainstorm); no task needed.
- **Placeholder scan**: no TBD / TODO / "similar to" placeholders. Every code step has the actual code.
- **Type consistency**:
  - `next_direction(last_direction_deg=..., mode=...)` keyword args used in T13 and called the same way in T17.
  - `infer_mow_direction(track_segments)` signature consistent in T12 and T14.
  - `compute_stripe_overlay(...)` keyword args identical in T16 and T17.
  - `MowerState.last_all_area_mow_direction_deg` field name identical in T11, T14, T15, T17.
  - `_DEFAULT_PALETTE` key names: `dark_green`, `mow_trail_color`, `traversal_color`, `mow_trail_thin_color` consistent across all tasks.
- **Risk hotspots**:
  - T8 (JS animation rewrite) is the most subtle change in the plan — manual visual validation is the only check. Keep the old engine reachable via a `?engine=legacy` URL flag if needed for one release cycle.
  - T16 (stripe-overlay polygon clipping) has fiddly math; if the third test fails iterate on `putalpha` vs `Image.composite` until correct.
  - T17 wires multiple pieces; if `_active_map_id` is None on first call after restart, the renderer falls back to `render_with_trail` cleanly (verified via the early-return paths).
