# Work Logs Cleanup + Map-Render Z-Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single shared `cached_map_png` + `_render_map_id` router with three independent render pipelines (Main view / Per-map static / Work Log), fix M_PATH color + z-order, drop the in-progress entry from the Work Log picker, and align entity names with the Dreame app's "Work Logs" terminology.

**Architecture:** Three PNG cache slots (`_main_view_png`, `_static_map_pngs_by_id`, `_work_log_png`) — each owned by a single render path with no shared mutability. Main view shows live state on the active map (no historical M_PATH). Per-map static cameras show base + black M_PATH overlay (drawn above the mowing zones for visibility). Work Log camera is independent of refresh ticks; only the picker writes it. In-progress sessions only appear on the Main view, never in the picker.

**Tech Stack:** Python 3.13+, Home Assistant Core, Pillow (PIL) for image rendering, pytest, frozen dataclasses, async_track_time_interval scheduling.

**Spec:** `docs/superpowers/specs/2026-05-08-replay-session-cleanup-design.md`

---

## File Structure

| Path | Responsibility | Touched in |
|---|---|---|
| `custom_components/dreame_a2_mower/map_render.py` | PIL render pipelines: `render_base_map` (palette + z-order), `render_main_view`, `render_work_log` | Tasks 1, 2, 3, 4 |
| `custom_components/dreame_a2_mower/coordinator.py` | State slots `_main_view_png` / `_work_log_png` / `_static_map_pngs_by_id`; render orchestration; legacy router removal | Tasks 5, 6, 10, 11 |
| `custom_components/dreame_a2_mower/camera.py` | `DreameA2MapCamera` (reads `_main_view_png`), new `DreameA2WorkLogCamera`, `MapImageView` updated paths | Tasks 7, 8, 11 |
| `custom_components/dreame_a2_mower/select.py` | `DreameA2WorkLogSelect` (renamed; filters `still_running`; `[Mowing]` prefix) | Task 9 |
| `dashboards/mower/dashboard.yaml` | "Sessions" view → "Work Logs"; references to renamed entities | Task 12 |
| `tests/protocol/test_m_path_render.py` | M_PATH black-by-default + above-zones z-order tests | Tasks 1, 2 |
| `tests/integration/test_main_view_render.py` | Main view contains zero M_PATH pixels | Task 3 |
| `tests/integration/test_work_log_render.py` | Work Log render has no mower icon | Task 4 |
| `tests/integration/test_work_log_isolation.py` | Cross-cache isolation: refresh tick doesn't touch `_work_log_png` | Task 11 |
| `tests/integration/test_work_log_picker.py` | Label format + `still_running` filter | Task 9 |
| `manifest.json` | Version bump | Task 12 |

---

## Task 1: M_PATH default color → black

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py:91`
- Modify: `tests/protocol/test_m_path_render.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/protocol/test_m_path_render.py`:

```python
def test_default_m_path_palette_is_black():
    """The default _DEFAULT_PALETTE['m_path'] is opaque black."""
    from custom_components.dreame_a2_mower.map_render import _DEFAULT_PALETTE

    assert _DEFAULT_PALETTE["m_path"] == (0, 0, 0, 255)
    # Width unchanged from Task 14 of cloud-discovery integration.
    assert _DEFAULT_PALETTE["m_path_width_px"] == 4
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/protocol/test_m_path_render.py::test_default_m_path_palette_is_black -v
```

Expected: FAIL with `AssertionError` — current default is `(160, 160, 160, 255)`.

- [ ] **Step 3: Update the palette default**

Edit `custom_components/dreame_a2_mower/map_render.py` around line 88-92. Replace:

```python
    # M_PATH overlay — cloud-persisted mow trajectories from prior sessions.
    # Drawn above the lawn but below mowing zones, so live work is visible.
    "m_path": (160, 160, 160, 255),
    "m_path_width_px": 4,
```

with:

```python
    # M_PATH overlay — cloud-persisted mow trajectories from prior sessions.
    # Black so it visually distinguishes from the live trail's dark grey
    # _TRAIL_COLOR (70,70,70,220). Drawn above the mowing zones (Section 2.5
    # in render_base_map) so it's visible over the alpha-200 zone fills.
    "m_path": (0, 0, 0, 255),
    "m_path_width_px": 4,
```

- [ ] **Step 4: Run all M_PATH render tests**

```
python -m pytest tests/protocol/test_m_path_render.py -v
```

Expected: PASS (all existing tests + new `test_default_m_path_palette_is_black`).

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/map_render.py tests/protocol/test_m_path_render.py
git commit -m "feat(map-render): M_PATH default color → black"
```

---

## Task 2: Move M_PATH render block above mowing zones

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` (cut ~263-281, re-insert after the mowing-zones block ending around line 312-314)
- Modify: `tests/protocol/test_m_path_render.py` (new test asserting M_PATH visible over zones)

- [ ] **Step 1: Write the failing test**

Append to `tests/protocol/test_m_path_render.py`:

```python
def test_m_path_drawn_above_mowing_zones():
    """An M_PATH segment crossing a mowing-zone polygon should be the
    M_PATH color, not zone-tinted (would mean it's drawn under the zone)."""
    import io
    from PIL import Image
    from custom_components.dreame_a2_mower.cloud_state import MowPathData
    from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
    from custom_components.dreame_a2_mower.map_render import render_base_map

    # Map with one mowing zone covering most of the canvas.
    map_data = MapData(
        md5="test",
        width_px=100, height_px=100, pixel_size_mm=50.0,
        bx1=0.0, by1=0.0, bx2=5000.0, by2=5000.0,
        cloud_x_reflect=5000.0, cloud_y_reflect=5000.0,
        rotation_deg=0.0,
        boundary_polygon=((0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0), (0.0, 5000.0)),
        mowing_zones=(MowingZone(zone_id=1, path=(
            (500.0, 500.0), (4500.0, 500.0), (4500.0, 4500.0), (500.0, 4500.0),
        )),),
        exclusion_zones=(), spot_zones=(),
        contour_paths=(), available_contour_ids=(),
        maintenance_points=(), dock_xy=None,
        total_area_m2=10.0, nav_paths=(),
    )

    # M_PATH segment running through the middle of the zone.
    mp = MowPathData(
        map_id=0,
        segments=(((1000, 2500), (4000, 2500)),),
    )
    distinct_color = (255, 0, 255, 255)  # magenta — won't appear in any other layer
    png_bytes = render_base_map(
        map_data,
        palette={"m_path": distinct_color, "m_path_width_px": 4},
        m_path=mp,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    pixels = list(img.getdata())
    # M_PATH pixels should be the exact override color — NOT alpha-blended
    # with green zone fill underneath. If the zone were drawn ON TOP, the
    # blended pixel would have green-shifted RGB instead of pure magenta.
    matching = [px for px in pixels if px == distinct_color]
    assert len(matching) > 0, (
        f"Expected pure {distinct_color!r} pixels (M_PATH above zones), "
        f"got 0. Top colors: {sorted(set(pixels), key=lambda c: -pixels.count(c))[:5]}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/protocol/test_m_path_render.py::test_m_path_drawn_above_mowing_zones -v
```

Expected: FAIL — current code draws M_PATH at Section 1.5 (BEFORE zones), so the magenta gets dimmed to a green-shifted color by the zone's alpha-200 fill on top.

- [ ] **Step 3: Move the M_PATH render block**

In `custom_components/dreame_a2_mower/map_render.py`, find the existing M_PATH section (currently labelled "1.5", added in Task 14 of v1.0.0a100). It's at approximately lines 263-281, immediately AFTER the lawn-boundary block (Section 1) and BEFORE the mowing-zones block (Section 2).

CUT this entire block:

```python
    # -----------------------------------------------------------------------
    # 1.5. M_PATH overlay — cloud-persisted prior-session mow tracks.
    #      Drawn above lawn fill, below mowing zones so live state stays
    #      visible. Each segment is an independent polyline (firmware's
    #      pen-up sentinel split, see protocol/m_path.py).
    # -----------------------------------------------------------------------
    if m_path is not None and m_path.segments:
        m_path_color: tuple[int, int, int, int] = p.get(
            "m_path", (0, 0, 0, 255)
        )  # type: ignore[assignment]
        m_path_width: int = p.get("m_path_width_px", 4)  # type: ignore[assignment]
        drawn_segments = 0
        for seg in m_path.segments:
            if len(seg) < 2:
                continue
            seg_px = [
                _cloud_to_px(x_mm, y_mm, bx2, by2, grid)
                for (x_mm, y_mm) in seg
            ]
            draw.line(seg_px, fill=m_path_color, width=m_path_width, joint="curve")
            drawn_segments += 1
        _LOGGER.debug(
            "render_base_map: drew %d M_PATH segment(s)", drawn_segments
        )
```

(Note the `(0, 0, 0, 255)` literal is the new default from Task 1.)

RE-INSERT it as Section 2.5 — immediately AFTER the mowing-zones loop ends and BEFORE the exclusion-zones / spot-zones / contour blocks. Update the section header to:

```python
    # -----------------------------------------------------------------------
    # 2.5. M_PATH overlay — cloud-persisted prior-session mow tracks.
    #      Drawn ABOVE mowing zones (so the cumulative track is visible
    #      over the alpha-200 zone fills) but BELOW exclusion / spot /
    #      nav / dock layers (those are interactive overlays the user
    #      cares about more than historical coverage).
    # -----------------------------------------------------------------------
    if m_path is not None and m_path.segments:
        m_path_color: tuple[int, int, int, int] = p.get(
            "m_path", (0, 0, 0, 255)
        )  # type: ignore[assignment]
        m_path_width: int = p.get("m_path_width_px", 4)  # type: ignore[assignment]
        drawn_segments = 0
        for seg in m_path.segments:
            if len(seg) < 2:
                continue
            seg_px = [
                _cloud_to_px(x_mm, y_mm, bx2, by2, grid)
                for (x_mm, y_mm) in seg
            ]
            draw.line(seg_px, fill=m_path_color, width=m_path_width, joint="curve")
            drawn_segments += 1
        _LOGGER.debug(
            "render_base_map: drew %d M_PATH segment(s)", drawn_segments
        )
```

To find the correct insertion point: the mowing-zones block ends with `_composite_polygon(...)` calls inside a `for zone in map_data.mowing_zones:` loop. The next section after it is exclusion zones (`for zone in map_data.exclusion_zones:`). Insert M_PATH between those two.

- [ ] **Step 4: Run M_PATH render tests**

```
python -m pytest tests/protocol/test_m_path_render.py -v
```

Expected: PASS (all 5 tests, including the new `test_m_path_drawn_above_mowing_zones`).

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/map_render.py tests/protocol/test_m_path_render.py
git commit -m "fix(map-render): draw M_PATH above mowing zones (z-order fix)"
```

---

## Task 3: Add `render_main_view()` function

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py` (add new function near `render_with_trail`)
- Create: `tests/integration/test_main_view_render.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_main_view_render.py`:

```python
"""Tests for render_main_view — live trail + mower icon, NO M_PATH."""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.cloud_state import MowPathData
from custom_components.dreame_a2_mower.map_decoder import MapData
from custom_components.dreame_a2_mower.map_render import render_main_view


def _make_min_map():
    return MapData(
        md5="test",
        width_px=100, height_px=100, pixel_size_mm=50.0,
        bx1=0.0, by1=0.0, bx2=5000.0, by2=5000.0,
        cloud_x_reflect=5000.0, cloud_y_reflect=5000.0,
        rotation_deg=0.0,
        boundary_polygon=((0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0), (0.0, 5000.0)),
        mowing_zones=(), exclusion_zones=(), spot_zones=(),
        contour_paths=(), available_contour_ids=(),
        maintenance_points=(), dock_xy=None,
        total_area_m2=10.0, nav_paths=(),
    )


def test_render_main_view_returns_png_bytes():
    """Smoke test: render_main_view produces valid PNG output."""
    map_data = _make_min_map()
    png_bytes = render_main_view(
        map_data,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    assert img.size == (100, 100)


def test_render_main_view_does_not_render_m_path():
    """render_main_view must NEVER include M_PATH overlay pixels, even if
    the caller had cloud history available — Main view shows live only."""
    map_data = _make_min_map()
    # Even though we don't pass an m_path kwarg, verify the signature
    # doesn't accept one — main view simply has no concept of historical paths.
    import inspect
    sig = inspect.signature(render_main_view)
    assert "m_path" not in sig.parameters
    # And the output should not contain the M_PATH default color.
    png_bytes = render_main_view(
        map_data, legs=None, mower_position_m=None, mower_heading_deg=None,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    pixels = list(img.getdata())
    matching = [px for px in pixels if px == (0, 0, 0, 255)]  # M_PATH default
    assert len(matching) == 0, (
        f"Main view contains {len(matching)} pure-black pixels — should be zero "
        f"(no M_PATH overlay). Top colors: "
        f"{sorted(set(pixels), key=lambda c: -pixels.count(c))[:5]}"
    )


def test_render_main_view_with_live_trail():
    """Pass legs and assert the trail is rendered on top of the base."""
    map_data = _make_min_map()
    legs = [[(10.0, 25.0), (40.0, 25.0)]]  # cloud-frame metres
    png_bytes = render_main_view(
        map_data,
        legs=legs,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    # Trail color is _TRAIL_COLOR = (70, 70, 70, 220) — blended over the
    # opaque grey lawn (221,221,221,255). The composite is approximately
    # (152, 152, 152, 255) — visible as a darker line.
    pixels = list(img.getdata())
    # Look for any pixel where R == G == B and 100 <= R <= 180 (trail-blended).
    blended = [
        px for px in pixels
        if px[0] == px[1] == px[2] and 100 <= px[0] <= 180 and px[3] == 255
    ]
    assert len(blended) > 0, "No trail-blended pixels found"
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/integration/test_main_view_render.py -v
```

Expected: FAIL with `ImportError: cannot import name 'render_main_view'`.

- [ ] **Step 3: Add `render_main_view` to `map_render.py`**

In `custom_components/dreame_a2_mower/map_render.py`, add this function near the existing `render_with_trail` (around line 469). Place it BEFORE `render_with_trail` so the new public API surface comes first:

```python
def render_main_view(
    map_data: "MapData",
    *,
    legs: "list[Leg] | None",
    mower_position_m: "tuple[float, float] | None",
    mower_heading_deg: "float | None",
    obstacle_polygons_m: "list[list[tuple[float, float]]] | None" = None,
    palette: dict | None = None,
) -> bytes:
    """Render the active map's Main view: base + live trail + mower icon + obstacles.

    Main view never shows historical M_PATH (that's the per-map static
    cameras' job). Always renders against the active map's MapData.

    Args:
        map_data: Decoded active map.
        legs: Live trail legs from LiveMapState.legs (None or empty → no trail).
        mower_position_m: Live mower position in cloud-frame metres.
        mower_heading_deg: Live mower heading in degrees (0-360).
        obstacle_polygons_m: Optional run-time obstacles (currently always
            empty until a live data source is identified — see spec
            "Non-goals" for context).
        palette: Optional palette override (forwarded to render_base_map).

    Returns:
        Raw PNG bytes.
    """
    return render_with_trail(
        map_data,
        legs,
        palette=palette,
        mower_position_m=mower_position_m,
        mower_heading_deg=mower_heading_deg,
        obstacle_polygons_m=obstacle_polygons_m,
    )
```

(This is a thin wrapper for now — Task 11 removes `render_with_trail` and inlines the logic. Keeping the wrapper here lets us migrate callers incrementally.)

- [ ] **Step 4: Run the new tests + full suite**

```
python -m pytest tests/integration/test_main_view_render.py -v
python -m pytest -q
```

Expected: 3 new tests pass, no regressions.

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/map_render.py tests/integration/test_main_view_render.py
git commit -m "feat(map-render): add render_main_view (live + no historical)"
```

---

## Task 4: Add `render_work_log()` function

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py`
- Create: `tests/integration/test_work_log_render.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_work_log_render.py`:

```python
"""Tests for render_work_log — archived trail, NO mower icon, NO M_PATH."""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData
from custom_components.dreame_a2_mower.map_render import render_work_log


def _make_min_map():
    return MapData(
        md5="test",
        width_px=100, height_px=100, pixel_size_mm=50.0,
        bx1=0.0, by1=0.0, bx2=5000.0, by2=5000.0,
        cloud_x_reflect=5000.0, cloud_y_reflect=5000.0,
        rotation_deg=0.0,
        boundary_polygon=((0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0), (0.0, 5000.0)),
        mowing_zones=(), exclusion_zones=(), spot_zones=(),
        contour_paths=(), available_contour_ids=(),
        maintenance_points=(), dock_xy=None,
        total_area_m2=10.0, nav_paths=(),
    )


def test_render_work_log_signature_has_no_mower_position():
    """The session is over — no live mower icon. Verify signature
    doesn't accept mower_position_m."""
    import inspect
    sig = inspect.signature(render_work_log)
    assert "mower_position_m" not in sig.parameters
    assert "mower_heading_deg" not in sig.parameters
    # M_PATH is also out — work logs are about ONE session, not history.
    assert "m_path" not in sig.parameters


def test_render_work_log_with_archived_trail():
    """Pass legs as if from an archived session; assert PNG renders."""
    map_data = _make_min_map()
    legs = [[(10.0, 25.0), (40.0, 25.0)]]
    png_bytes = render_work_log(map_data, legs=legs)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    assert img.size == (100, 100)


def test_render_work_log_no_m_path_pixels():
    """Output never contains M_PATH default color."""
    map_data = _make_min_map()
    png_bytes = render_work_log(map_data, legs=[])
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    matching = [px for px in img.getdata() if px == (0, 0, 0, 255)]
    assert len(matching) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/integration/test_work_log_render.py -v
```

Expected: FAIL with `ImportError: cannot import name 'render_work_log'`.

- [ ] **Step 3: Add `render_work_log` to `map_render.py`**

Place it immediately after `render_main_view` (defined in Task 3):

```python
def render_work_log(
    map_data: "MapData",
    *,
    legs: "list[Leg]",
    obstacle_polygons_m: "list[list[tuple[float, float]]] | None" = None,
    palette: dict | None = None,
) -> bytes:
    """Render an archived session: base + archived trail + archived obstacles.

    Differs from render_main_view: NO mower icon (the session is over,
    no live position), NO M_PATH (work logs are about ONE specific session,
    not cumulative history).

    Args:
        map_data: Decoded MapData for the map the session ran against.
        legs: Archived trail legs from session_summary.track_segments
            (or _local_legs fallback).
        obstacle_polygons_m: Archived obstacles in cloud-frame metres.
        palette: Optional palette override.

    Returns:
        Raw PNG bytes.
    """
    return render_with_trail(
        map_data,
        legs,
        palette=palette,
        mower_position_m=None,
        mower_heading_deg=None,
        obstacle_polygons_m=obstacle_polygons_m,
    )
```

- [ ] **Step 4: Run the new tests + full suite**

```
python -m pytest tests/integration/test_work_log_render.py -v
python -m pytest -q
```

Expected: 3 new tests pass, no regressions.

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/map_render.py tests/integration/test_work_log_render.py
git commit -m "feat(map-render): add render_work_log (archived trail, no live mower icon)"
```

---

## Task 5: Add coordinator state slots `_main_view_png`, `_work_log_png`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py:569` (in `__init__`)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_main_view_render.py`:

```python
def test_coordinator_has_main_view_and_work_log_png_slots():
    """Coordinator exposes the new explicit cache slots."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    coord = object.__new__(DreameA2MowerCoordinator)
    # __init__ not called here, so the slots only show up if the dataclass
    # defines them or if they're set via type annotation default.
    # For unittest purposes, instantiate the relevant attributes manually:
    coord._main_view_png = None
    coord._work_log_png = None
    # Verify they're settable to bytes.
    coord._main_view_png = b"\x89PNG"
    coord._work_log_png = b"\x89PNG"
    assert coord._main_view_png == b"\x89PNG"
    assert coord._work_log_png == b"\x89PNG"
```

(This test is mostly a documentation harness — the real check is that the coordinator's `__init__` initialises the slots so other code can read them safely.)

Also add to that file (or to the bottom of `tests/integration/test_main_view_render.py`):

```python
def test_coordinator_init_sets_png_slots_to_none(hass=None):
    """A freshly-constructed coordinator has both png slots = None."""
    # Standalone-import the __init__ logic without HA. This test parses the
    # coordinator __init__ source for the new slot lines as a syntactic check,
    # since constructing DreameA2MowerCoordinator requires an HA instance.
    import re
    from pathlib import Path
    src = Path("custom_components/dreame_a2_mower/coordinator.py").read_text()
    assert re.search(r"self\._main_view_png\s*:\s*bytes\s*\|\s*None\s*=\s*None", src), (
        "coordinator.__init__ should declare self._main_view_png: bytes | None = None"
    )
    assert re.search(r"self\._work_log_png\s*:\s*bytes\s*\|\s*None\s*=\s*None", src), (
        "coordinator.__init__ should declare self._work_log_png: bytes | None = None"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/integration/test_main_view_render.py::test_coordinator_init_sets_png_slots_to_none -v
```

Expected: FAIL — neither slot is defined yet.

- [ ] **Step 3: Add the slots to coordinator `__init__`**

In `custom_components/dreame_a2_mower/coordinator.py`, find the existing block at line 569:

```python
        self._cached_pngs_by_id: dict[int, bytes] = {}
        self._last_map_md5_by_id: dict[int, str] = {}
```

INSERT these two lines IMMEDIATELY BEFORE that block (so the new slots are documented next to the related state):

```python
        # Three independent PNG cache slots, one per render pipeline:
        #   _main_view_png         — active map + live trail (Main view)
        #   _cached_pngs_by_id     — per-map static base + M_PATH (renamed
        #                            to _static_map_pngs_by_id in Task 11)
        #   _work_log_png          — picker-selected archived session
        # Each slot is owned by one render path; no shared mutability.
        self._main_view_png: bytes | None = None
        self._work_log_png: bytes | None = None
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_main_view_render.py -v
python -m pytest -q
```

Expected: New slot tests pass, no regressions.

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_main_view_render.py
git commit -m "feat(coordinator): add _main_view_png + _work_log_png cache slots"
```

---

## Task 6: Add `_render_main_view()` coordinator method + wire into existing triggers

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (add new method; change existing 3 call sites at lines 1832, 1989, 2071)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_main_view_render.py`:

```python
def test_coordinator_render_main_view_method_exists():
    """Coordinator exposes _render_main_view as an awaitable that writes
    self._main_view_png."""
    import inspect
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    method = getattr(DreameA2MowerCoordinator, "_render_main_view", None)
    assert method is not None, "_render_main_view should be defined"
    assert inspect.iscoroutinefunction(method), "_render_main_view should be async"
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/integration/test_main_view_render.py::test_coordinator_render_main_view_method_exists -v
```

Expected: FAIL — method doesn't exist.

- [ ] **Step 3: Add `_render_main_view` method**

In `custom_components/dreame_a2_mower/coordinator.py`, add a new method near `_rerender_live_trail` (around line 2047). Place AFTER it:

```python
    async def _render_main_view(self) -> None:
        """Render the active map's Main view (base + live trail + mower icon).

        Writes the result to self._main_view_png. No-ops gracefully when:
        - _active_map_id is None (active map not yet known)
        - _cached_maps_by_id has no entry for the active map
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self._cached_maps_by_id.get(active_id)
        if map_data is None:
            return
        from .map_render import render_main_view
        from functools import partial

        legs = list(self.live_map.legs) if self.live_map.is_active() else None
        if (
            self.data.position_x_m is not None
            and self.data.position_y_m is not None
        ):
            mower_pos: tuple[float, float] | None = (
                float(self.data.position_x_m),
                float(self.data.position_y_m),
            )
        else:
            mower_pos = None
        heading = self._current_mower_heading()
        png = await self.hass.async_add_executor_job(
            partial(
                render_main_view,
                map_data,
                legs=legs,
                mower_position_m=mower_pos,
                mower_heading_deg=heading,
            )
        )
        if png:
            self._main_view_png = png
```

- [ ] **Step 4: Wire the new method into existing trigger points**

For now, leave the existing `render_with_trail` calls in place (they still write to `_cached_pngs_by_id[active_id]` for backward compat). Tasks 7 + 11 finish the migration.

But ALSO call `_render_main_view()` from the same trigger points so `_main_view_png` populates. Find these call sites and add a follow-up call:

**Site 1: `_render_maps_from_cloud_state` (line ~1817–1850)**

After the loop's `if png: self._cached_pngs_by_id[map_id] = png` line, OUTSIDE the loop, add:

```python
        # Also populate _main_view_png so DreameA2MapCamera (post-Task 7)
        # has a fresh active-map render. This is redundant during the
        # migration; Task 11 removes the legacy _cached_pngs_by_id active-map
        # write.
        await self._render_main_view()
```

**Site 2: `_rerender_live_trail` (line ~2047–2010-ish, depending on the exact size)**

At the END of the existing method body (before it returns), add:

```python
        await self._render_main_view()
```

**Site 3: any other place that writes `self._cached_pngs_by_id[active_id]` for the live trail.** Search with `grep -n "_cached_pngs_by_id\[" custom_components/dreame_a2_mower/coordinator.py` and add a `_render_main_view()` call after each, EXCEPT inside `replay_session` (which renders to `_render_map_id`, not the active map — Task 10 handles it).

- [ ] **Step 5: Run tests**

```
python -m pytest tests/integration/test_main_view_render.py -v
python -m pytest -q
```

Expected: New method test passes, no regressions.

- [ ] **Step 6: Commit**

```
git add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_main_view_render.py
git commit -m "feat(coordinator): _render_main_view writes _main_view_png on every live trigger"
```

---

## Task 7: Rewire `DreameA2MapCamera` to read `_main_view_png`

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py` (replace `cached_map_png` references in `DreameA2MapCamera` only — `MapImageView` keeps its existing fallback for now; Task 11 finishes that)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_main_view_render.py`:

```python
def test_main_view_camera_reads_main_view_png():
    """DreameA2MapCamera.async_camera_image returns _main_view_png."""
    import asyncio
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.camera import DreameA2MapCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = None
    coord._cached_pngs_by_id = {}
    coord._cached_maps_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._render_map_id = None  # legacy field, still in __init__ until Task 11
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    cam = DreameA2MapCamera(coord)
    result = asyncio.run(cam.async_camera_image())
    assert result == b"\x89PNGmainview"
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/integration/test_main_view_render.py::test_main_view_camera_reads_main_view_png -v
```

Expected: FAIL — the camera currently reads from `cached_map_png` (which routes via `_render_map_id ?? _active_map_id`), so it returns `None` (the legacy slot is empty in this test).

- [ ] **Step 3: Update `DreameA2MapCamera`**

In `custom_components/dreame_a2_mower/camera.py`, find `DreameA2MapCamera` (line 49). Replace EVERY occurrence of `self.coordinator.cached_map_png` with `self.coordinator._main_view_png` inside this class — there are roughly 4 such call sites at lines 76, 101, 115, 195.

For example, line 76 today:
```python
        rendered = self.coordinator.cached_map_png
```
Becomes:
```python
        rendered = self.coordinator._main_view_png
```

DO NOT touch `DreameA2PerMapCamera` (line 213) or `MapImageView` (line 341) yet — those still use `_cached_pngs_by_id` and `cached_map_png` respectively. Task 11 / 12 handles them.

The `extra_state_attributes` block at line ~109-164 reads `self.coordinator._cached_map_data` (a multi-map-aware getter). LEAVE THAT ALONE for now — that getter still works. Task 11 simplifies it.

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_main_view_render.py -v
python -m pytest -q
```

Expected: New test passes, no regressions. Existing `tests/integration/test_camera.py` tests (if any) may need a `_main_view_png` field added to their stubs — fix those by setting `coord._main_view_png = <bytes>` alongside the existing `coord._cached_pngs_by_id[...] = ...` setup.

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/camera.py tests/integration/test_main_view_render.py tests/integration/test_camera.py
git commit -m "feat(camera): DreameA2MapCamera reads _main_view_png"
```

(Adjust the `git add` for tests if you didn't end up modifying `test_camera.py`.)

---

## Task 8: Add `DreameA2WorkLogCamera` entity + register

**Files:**
- Modify: `custom_components/dreame_a2_mower/camera.py` (new class + add to `async_setup_entry`)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_work_log_camera.py`:

```python
"""Tests for DreameA2WorkLogCamera — reads _work_log_png independently."""
from __future__ import annotations

import asyncio

from unittest.mock import MagicMock


def test_work_log_camera_reads_work_log_png():
    from custom_components.dreame_a2_mower.camera import DreameA2WorkLogCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = b"\x89PNGworklog"
    coord._cached_pngs_by_id = {}
    coord._cached_maps_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._render_map_id = None
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    cam = DreameA2WorkLogCamera(coord)
    result = asyncio.run(cam.async_camera_image())
    assert result == b"\x89PNGworklog"


def test_work_log_camera_returns_none_when_slot_empty():
    from custom_components.dreame_a2_mower.camera import DreameA2WorkLogCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = None
    coord._cached_pngs_by_id = {}
    coord._cached_maps_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._render_map_id = None
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    cam = DreameA2WorkLogCamera(coord)
    result = asyncio.run(cam.async_camera_image())
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/integration/test_work_log_camera.py -v
```

Expected: FAIL with `ImportError: cannot import name 'DreameA2WorkLogCamera'`.

- [ ] **Step 3: Add `DreameA2WorkLogCamera` to `camera.py`**

In `custom_components/dreame_a2_mower/camera.py`, immediately after `DreameA2PerMapCamera` (which ends around line 250), add:

```python
class DreameA2WorkLogCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """The Work Log camera. Independent of live state — its PNG is
    written ONLY by the work-log picker (select.dreame_a2_mower_work_log).
    Periodic refreshes never touch it.

    Returns None when no log has been picked yet (or the picker is on
    the placeholder), surfacing as "Image not available" in the UI.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "work_log"
    _attr_name = "Work Log"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_work_log"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model="dreame.mower.g2408",
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self.coordinator._work_log_png

    @property
    def entity_picture(self) -> str | None:
        png = self.coordinator._work_log_png
        if not png:
            return None
        import hashlib
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/work_log.png?v={v}"
```

Then update `async_setup_entry` (around line 22-44) to register it. The current call adds `DreameA2PerMapCamera` instances; just append `DreameA2WorkLogCamera`:

```python
    entities.append(DreameA2WorkLogCamera(coordinator))
```

(Find the exact location: after the `for map_id in ...: entities.append(DreameA2PerMapCamera(coordinator, map_id))` loop, BEFORE `async_add_entities(entities)`.)

- [ ] **Step 4: Add the `MapImageView` route for `work_log.png`**

In `MapImageView` (around line 341-410), the `get` handler currently splits on `map_id` query param. Add a new view OR add a route param. Cleanest: add a separate view class.

Add IMMEDIATELY AFTER `MapImageView`:

```python
class WorkLogImageView(HomeAssistantView):
    """HTTP endpoint serving the Work Log camera's PNG with no-cache headers."""

    url = "/api/dreame_a2_mower/work_log.png"
    name = "api:dreame_a2_mower:work_log"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        coordinator = None
        for cand in entries.values():
            coordinator = cand
            break
        if coordinator is None:
            return web.Response(status=404, text="No mower coordinator")
        png = coordinator._work_log_png
        if not png:
            return web.Response(status=404, text="No work log rendered yet")
        return web.Response(
            body=png,
            content_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )
```

Register it in `async_setup_entry` next to `MapImageView()`:

```python
        hass.http.register_view(WorkLogImageView())
```

(Find the existing line `hass.http.register_view(MapImageView())` at line 34 and add the new register on the next line.)

- [ ] **Step 5: Run tests + commit**

```
python -m pytest tests/integration/test_work_log_camera.py -v
python -m pytest -q
```

Expected: 2 new tests pass, no regressions.

```
git add custom_components/dreame_a2_mower/camera.py tests/integration/test_work_log_camera.py
git commit -m "feat(camera): add DreameA2WorkLogCamera + WorkLogImageView"
```

---

## Task 9: Rename `DreameA2ReplaySessionSelect` → `DreameA2WorkLogSelect`, filter `still_running`, add `[Mowing]` prefix

**Files:**
- Modify: `custom_components/dreame_a2_mower/select.py:468-631`
- Create: `tests/integration/test_work_log_picker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_work_log_picker.py`:

```python
"""Tests for DreameA2WorkLogSelect — picker filters + label format."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.session import ArchivedSession
from custom_components.dreame_a2_mower.select import DreameA2WorkLogSelect


def _make_archived(**kwargs):
    defaults = dict(
        filename="x.json",
        start_ts=1700000000,
        end_ts=1700001800,
        duration_min=30,
        area_mowed_m2=42.5,
        map_area_m2=100,
        md5="aabbccdd",
        still_running=False,
        local_trail_complete=True,
        map_id=0,
    )
    defaults.update(kwargs)
    return ArchivedSession(**defaults)


def _make_picker():
    coord = MagicMock()
    coord.entry.entry_id = "test"
    coord._cloud = None
    return DreameA2WorkLogSelect(coord)


def test_label_has_mowing_and_map_prefix():
    picker = _make_picker()
    s = _make_archived(map_id=0)
    labels, mapping = picker._build_options_from_sessions([s])
    # First label is the placeholder; second is the session.
    assert labels[1].startswith("[Mowing] [Map 1]")


def test_label_has_map_question_mark_for_legacy():
    picker = _make_picker()
    s = _make_archived(map_id=-1)
    labels, mapping = picker._build_options_from_sessions([s])
    assert labels[1].startswith("[Mowing] [Map ?]")


def test_in_progress_session_is_filtered_out():
    """A session with still_running=True must NOT appear in picker options."""
    picker = _make_picker()
    in_progress = _make_archived(filename="in_progress.json", md5="", still_running=True)
    completed = _make_archived(filename="abc.json", md5="abc")
    labels, mapping = picker._build_options_from_sessions([in_progress, completed])
    # Placeholder + 1 completed = 2 labels.
    assert len(labels) == 2
    assert "in progress" not in " ".join(labels).lower()
    # The completed entry should be present.
    assert any("[Mowing]" in l for l in labels)


def test_partial_trail_marker_preserved():
    """A non-running session with local_trail_complete=False keeps the ⚠ marker."""
    picker = _make_picker()
    s = _make_archived(local_trail_complete=False)
    labels, mapping = picker._build_options_from_sessions([s])
    assert "⚠" in labels[1]
    assert "[Mowing]" in labels[1]


def test_unique_id_uses_work_log_suffix():
    coord = MagicMock()
    coord.entry.entry_id = "abc123"
    coord._cloud = None
    picker = DreameA2WorkLogSelect(coord)
    assert picker._attr_unique_id == "abc123_work_log"
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/integration/test_work_log_picker.py -v
```

Expected: FAIL with `ImportError: cannot import name 'DreameA2WorkLogSelect'`.

- [ ] **Step 3: Rename + update `select.py`**

In `custom_components/dreame_a2_mower/select.py`, find `class DreameA2ReplaySessionSelect` at line 468. Replace it with this entire block (rename, filter, prefix updates, drop ▶ marker):

```python
class DreameA2WorkLogSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """Dropdown of archived sessions; picking one fires `render_work_log_session`.

    Options are human-readable labels:
        ``[Mowing] [Map N] YYYY-MM-DD HH:MM — N.N m² / Mmin``

    The ``[Mowing]`` prefix tags every entry by category — when Patrol Logs
    become available, ``[Patrol]``-prefixed entries can be merged into the
    same picker.

    The label maps back to a session filename via an internal dict.
    Newest session first; capped at the most recent 50.

    In-progress sessions (``still_running == True``) are FILTERED OUT — the
    Main view shows the live mow; Work Logs is for finalised sessions only.
    """

    _attr_has_entity_name = True
    _attr_name = "Work Log"
    _attr_icon = "mdi:history"
    _placeholder: str = "(pick a session)"
    _max_options: int = 50

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_work_log"
        client = getattr(coordinator, "_cloud", None)
        device_id = getattr(client, "device_id", None) if client else None
        model = getattr(client, "model", None) if client else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )
        self._label_to_filename: dict[str, str] = {}
        self._attr_options: list[str] = [self._placeholder]
        self._attr_current_option = self._placeholder

    def _build_options_from_sessions(self, sessions: list) -> tuple[list[str], dict[str, str]]:
        """Pure formatter — no I/O.

        Filters out still_running entries (in-progress lives on Main view).
        """
        from datetime import datetime

        # Filter still_running BEFORE sorting + capping, so the user never
        # sees a synthesized in-progress row.
        eligible = [s for s in sessions if not getattr(s, "still_running", False)]
        eligible = sorted(eligible, key=lambda s: s.end_ts, reverse=True)[: self._max_options]
        labels: list[str] = [self._placeholder]
        mapping: dict[str, str] = {}
        for s in eligible:
            try:
                ts_str = datetime.fromtimestamp(int(s.end_ts)).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except (OverflowError, OSError, ValueError):
                ts_str = "??"
            map_id = getattr(s, "map_id", -1)
            if map_id == -1:
                map_prefix = "[Map ?]"
            else:
                map_prefix = f"[Map {map_id + 1}]"
            base = f"[Mowing] {map_prefix} {ts_str} — {s.area_mowed_m2:.1f} m² / {s.duration_min}min"
            if not getattr(s, "local_trail_complete", True):
                label = f"⚠ {base} (partial trail)"
            else:
                label = base
            if label in mapping:
                label = f"{label} [{(s.md5 or '')[:6]}]"
            labels.append(label)
            mapping[label] = s.filename or s.md5
        return labels, mapping

    async def _async_refresh_options(self) -> None:
        archive = getattr(self.coordinator, "session_archive", None)
        if archive is None:
            return
        try:
            sessions = await self.hass.async_add_executor_job(archive.list_sessions)
        except Exception as ex:
            LOGGER.warning("select.work_log: list_sessions failed: %s", ex)
            return
        labels, mapping = self._build_options_from_sessions(sessions)
        if labels == self._attr_options and mapping == self._label_to_filename:
            return
        self._attr_options = labels
        self._label_to_filename = mapping
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_refresh_options()

    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        super()._handle_coordinator_update()
        self.hass.async_create_task(self._async_refresh_options())

    @property
    def options(self) -> list[str]:
        return self._attr_options

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option or self._placeholder

    async def async_select_option(self, option: str) -> None:
        if option == self._placeholder:
            # Picking the placeholder clears the work-log camera.
            self.coordinator._work_log_png = None
            update_listeners = getattr(self.coordinator, "async_update_listeners", None)
            if callable(update_listeners):
                update_listeners()
            self._attr_current_option = self._placeholder
            self.async_write_ha_state()
            return
        await self._async_refresh_options()
        filename = self._label_to_filename.get(option)
        if not filename:
            LOGGER.warning(
                "select.work_log: unknown option %r — ignoring", option
            )
            return
        LOGGER.info(
            "select.work_log: render session %s (label=%r)", filename, option,
        )
        try:
            await self.coordinator.render_work_log_session(filename)
        except Exception as ex:
            LOGGER.warning("select.work_log: render_work_log_session(%s) raised: %s", filename, ex)
        self._attr_current_option = option
        self.async_write_ha_state()
```

Then update `async_setup_entry` at the top of `select.py` (around line 55-71) to use the new class name. Find:

```python
    entities.append(DreameA2ReplaySessionSelect(coordinator))
```

Replace with:

```python
    entities.append(DreameA2WorkLogSelect(coordinator))
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_work_log_picker.py -v
python -m pytest -q
```

Expected: 5 new tests pass. Existing tests referencing `DreameA2ReplaySessionSelect` will fail — fix them by renaming all references; the public service `dreame_a2_mower.replay_session` (in `services.py`) is independent and stays.

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/select.py tests/integration/test_work_log_picker.py tests/
git commit -m "feat(select): rename ReplaySessionSelect → WorkLogSelect; filter still_running; [Mowing] prefix"
```

---

## Task 10: Add `render_work_log_session()` coordinator method

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py:2080-2300` (rename `replay_session` → `render_work_log_session` and have it write to `_work_log_png` instead of going through `_render_map_id` / `cached_map_png`)
- Modify: `custom_components/dreame_a2_mower/services.py` (the public `dreame_a2_mower.replay_session` service still calls `coordinator.replay_session`; update the call name OR keep `replay_session` as a thin alias)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_work_log_isolation.py`:

```python
"""Cross-cache isolation: picking a Work Log doesn't touch _main_view_png."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from custom_components.dreame_a2_mower.archive.session import ArchivedSession
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator


def _build_coord(active_map_id: int = 0):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = None
    coord._cached_pngs_by_id = {}
    coord._cached_maps_by_id = {}  # Empty — replay must handle gracefully.
    coord._last_map_md5_by_id = {}
    coord._active_map_id = active_map_id
    coord._render_map_id = None
    coord._cloud = MagicMock()
    coord.session_archive = MagicMock()
    coord.session_archive.list_sessions = MagicMock(return_value=[])
    coord.session_archive.load = MagicMock(return_value=None)
    coord.entry = MagicMock()
    coord.entry.entry_id = "test"
    coord.data = MagicMock()
    coord.data.position_x_m = None
    coord.data.position_y_m = None
    coord.live_map = MagicMock()
    coord.live_map.is_active = MagicMock(return_value=False)
    coord.hass = MagicMock()
    return coord


def test_render_work_log_session_method_exists():
    import inspect
    method = getattr(DreameA2MowerCoordinator, "render_work_log_session", None)
    assert method is not None
    assert inspect.iscoroutinefunction(method)


def test_render_work_log_session_does_not_touch_main_view_png():
    """A Work Log render writes _work_log_png and never _main_view_png."""
    coord = _build_coord()
    main_view_before = coord._main_view_png

    # render_work_log_session bails when the session isn't found; we only
    # need to verify it doesn't TOUCH _main_view_png even on failure.
    coord.session_archive.list_sessions = MagicMock(return_value=[])
    asyncio.run(coord.render_work_log_session("does-not-exist"))

    assert coord._main_view_png == main_view_before, (
        "_main_view_png must not change during a Work Log render"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/integration/test_work_log_isolation.py -v
```

Expected: FAIL — `render_work_log_session` not defined.

- [ ] **Step 3: Rename `replay_session` → `render_work_log_session`; rewire output**

In `custom_components/dreame_a2_mower/coordinator.py`, find `async def replay_session(self, session_md5: str)` at line 2080. Apply these changes:

1. **Rename** the method to `render_work_log_session`. Keep the parameter name `session_md5` (the picker may pass either a filename or md5; the lookup logic handles both).

2. **Remove the `self._render_map_id = target_map_id` assignment** at line ~2258. The Work Log no longer steers the active-map PNG cache.

3. **Replace the `self.cached_map_png = png` write** at line ~2273 with:
   ```python
   self._work_log_png = png
   ```

4. **Remove the `self._last_map_md5 = None`** invalidation (it's a remnant of the legacy multi-map-aware `_last_map_md5_by_id`/`_render_map_id` router; Work Log now has its own slot).

5. **Remove the `self._replay_counter = ...` increment.** The new Work Log camera entity has its own cache, and the camera's `entity_picture` already uses a content-hash query param (`?v=...`) so it busts the frontend cache deterministically.

6. **Add a thin compatibility shim** so the public `dreame_a2_mower.replay_session` service keeps working (services.py currently calls `coordinator.replay_session(...)`). Place this directly above `render_work_log_session`:

   ```python
   async def replay_session(self, session_md5: str) -> None:
       """Backwards-compat alias for the Work Log render method.

       Kept so the public dreame_a2_mower.replay_session service (and any
       user automations referencing it) keep working after the rename.
       """
       await self.render_work_log_session(session_md5)
   ```

The end of the (renamed) method should look like:

```python
        png = await self.hass.async_add_executor_job(
            partial(
                render_work_log,
                map_data,
                legs=legs,
                obstacle_polygons_m=obstacle_polygons_m,
            )
        )
        self._work_log_png = png
        elapsed_ms = int((_time.monotonic() - replay_start_unix) * 1000)
        LOGGER.warning(
            "[F5.9.1] render_work_log_session: rendered work-log PNG (%d bytes) "
            "for key=%s, legs=%d, total_points=%d, elapsed=%dms",
            len(png) if png else 0,
            session_md5,
            len(legs),
            sum(len(leg) for leg in legs),
            elapsed_ms,
        )
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()
```

Note the `from .map_render import render_work_log` import (replacing the existing `from .map_render import render_with_trail`).

- [ ] **Step 4: Run tests**

```
python -m pytest tests/integration/test_work_log_isolation.py -v
python -m pytest -q
```

Expected: 2 new tests pass. Some existing replay-session tests will need their assertions updated:
- `coord.cached_map_png` references → `coord._work_log_png`
- `coord._render_map_id` references → drop them (no longer set)
- `coord._replay_counter` references → drop them

Walk those failures and update each test to read `_work_log_png` instead.

- [ ] **Step 5: Commit**

```
git add custom_components/dreame_a2_mower/coordinator.py tests/
git commit -m "feat(coordinator): render_work_log_session writes _work_log_png (cross-cache isolation)"
```

---

## Task 11: Drop legacy plumbing and rename `_cached_pngs_by_id`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py` (delete `_render_map_id`, `cached_map_png` getter/setter, multi-map-aware `_cached_map_data` / `_last_map_md5` getters/setters; rename `_cached_pngs_by_id` → `_static_map_pngs_by_id`)
- Modify: `custom_components/dreame_a2_mower/camera.py` (`MapImageView` and any remaining call sites)
- Modify: tests across the repo (~50 sites)

- [ ] **Step 1: Identify all call sites**

```
grep -rn "_cached_pngs_by_id\|_render_map_id\|cached_map_png\|_replay_counter" \
    custom_components/dreame_a2_mower/ tests/ \
    | grep -v __pycache__
```

Save the output so you can reference each site.

- [ ] **Step 2: Delete legacy state and accessors in `coordinator.py`**

Remove these lines (line numbers approximate as of commit 111b373 — search anchored on the LHS identifier):

- Delete `self._render_map_id: int | None = None` from `__init__` (line 575).
- Delete the entire `cached_map_png` property getter (lines 596-611) and setter (lines 614-626).
- Delete the multi-map-aware `_cached_map_data` getter (lines 631-644) and setter (lines 645-665) — they're routed through `_render_map_id`. Replace any caller with `self._cached_maps_by_id.get(self._active_map_id)` if a single-map read is desired (search for `_cached_map_data` references first; if anything still uses it, leave the getter as a thin wrapper).
- Delete the `_last_map_md5` getter/setter that route through `_render_map_id`.
- Delete every `self._replay_counter = ...` assignment (search for `_replay_counter`).

- [ ] **Step 3: Rename `_cached_pngs_by_id` → `_static_map_pngs_by_id`**

Use a single targeted rename across the integration package:

```
git ls-files custom_components/dreame_a2_mower | xargs sed -i 's/_cached_pngs_by_id/_static_map_pngs_by_id/g'
git ls-files tests | xargs sed -i 's/_cached_pngs_by_id/_static_map_pngs_by_id/g'
```

Verify:
```
grep -rn "_cached_pngs_by_id" custom_components/ tests/ | grep -v __pycache__
```
Expected: 0 hits.

- [ ] **Step 4: Update `MapImageView`**

In `custom_components/dreame_a2_mower/camera.py`, the `MapImageView.get` handler at line ~373-410 currently:

```python
        map_id_raw = request.query.get("map_id")
        if map_id_raw is not None:
            try:
                map_id = int(map_id_raw)
            except (TypeError, ValueError):
                return web.Response(status=400, text="Bad map_id")
            png = coordinator._cached_pngs_by_id.get(map_id)
        else:
            png = coordinator.cached_map_png
```

After Step 3 the rename has updated `_cached_pngs_by_id` to `_static_map_pngs_by_id`. Update the `else` branch to read `_main_view_png`:

```python
        map_id_raw = request.query.get("map_id")
        if map_id_raw is not None:
            try:
                map_id = int(map_id_raw)
            except (TypeError, ValueError):
                return web.Response(status=400, text="Bad map_id")
            png = coordinator._static_map_pngs_by_id.get(map_id)
        else:
            # Active-map (Main view) PNG.
            png = coordinator._main_view_png
```

- [ ] **Step 5: Run the full test suite — fix breakage iteratively**

```
python -m pytest -q
```

Expected: a wave of failures from tests that:
- still set `coord._cached_pngs_by_id` (rename should fix automatically — Step 3)
- still read `coord.cached_map_png` → replace with `coord._main_view_png`
- still set `coord._render_map_id` → delete those lines (no longer used)
- still read `coord._replay_counter` → delete those lines

Walk each failure, update the test, re-run. The commit should bring `python -m pytest -q` back to 0 failures.

- [ ] **Step 6: Commit**

```
git add custom_components/dreame_a2_mower/ tests/
git commit -m "refactor: drop _render_map_id + cached_map_png + _replay_counter; rename _cached_pngs_by_id → _static_map_pngs_by_id"
```

---

## Task 12: Update dashboard YAML, version bump, release

**Files:**
- Modify: `dashboards/mower/dashboard.yaml`
- Modify: `manifest.json` (via `tools/release.sh`)

- [ ] **Step 1: Update `dashboards/mower/dashboard.yaml`**

Find the existing "Sessions" view (currently at line ~338 — search for `title: Sessions`). Apply these changes:

1. View `title: Sessions` → `title: Work Logs`
2. View `path: sessions` → `path: work_logs`
3. View `icon` stays as `mdi:history`
4. Picture-entity card on this view currently references `entity: camera.dreame_a2_mower_map` — change to `entity: camera.dreame_a2_mower_work_log`. Drop `camera_view: live` if present (the work-log camera doesn't need a live polling mode; it serves a static byte stream that changes only on picker select).
5. The select reference (entities card or whichever card lists `select.dreame_a2_mower_replay_session`) → `select.dreame_a2_mower_work_log`.

Validate:

```
python -c "import yaml; yaml.safe_load(open('dashboards/mower/dashboard.yaml')); print('YAML OK')"
```

Expected: `YAML OK`.

Search the rest of the dashboard for stale references to ensure no card still points at the old entity:

```
grep -n "replay_session\|dreame_a2_mower_map\b" dashboards/mower/dashboard.yaml
```

The Mower-tab live map should still reference `camera.dreame_a2_mower_map` (Main view) — that stays. Only the Sessions/Work Logs view changed.

- [ ] **Step 2: Run the full suite a final time**

```
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Stage uncommitted dashboard change + commit**

```
git add dashboards/mower/dashboard.yaml
git commit -m "feat(dashboard): rename Sessions view → Work Logs; point at camera.work_log"
```

- [ ] **Step 4: Cut release**

Per memory `feedback_hacs_version_ladder.md`, when crossing aN→a(N+1) at a 9→10 boundary, bump the patch instead. Last shipped was `v1.0.1a2`; auto-bump would give `v1.0.1a3`. Either is fine here (no 9→10 crossover).

Write the release notes file:

```
cat > /tmp/release_1_0_1a3_notes.md <<'EOF'
## v1.0.1a3 — Work Logs cleanup + map-render z-order

Holistic redesign of the replay-session pipeline + map-render layering,
addressing 6 issues observed after v1.0.1a2:

1. M_PATH overlay color too close to live trail color → black now
2. M_PATH z-order under transparent zone fills → moved above zones
3. Replay map showed latest session even with no picker selection → independent cache slot
4. Replay sessions with stale data model → strict historical-only picker
5. Map 1 session rendered on top of Map 2 base → independent render pipelines
6. 10-20s revert from picker pick → no shared cache, no race

Architecture: three independent render pipelines:
- Main view (`_main_view_png`) — active map + live trail. No M_PATH.
- Per-map static (`_static_map_pngs_by_id`) — base + black M_PATH above zones.
- Work Logs (`_work_log_png`) — picker-selected archive only.

Renames:
- `select.dreame_a2_mower_replay_session` → `select.dreame_a2_mower_work_log`
- Dashboard view "Sessions" → "Work Logs"

New entities:
- `camera.dreame_a2_mower_work_log` — work log camera with independent cache

Removed plumbing:
- `cached_map_png` getter/setter
- `_render_map_id` state field
- `_replay_counter`

In-progress sessions no longer appear in the Work Log picker (they're
visible on the Main view live). Architecture left room for a future
`[Patrol]`-prefixed picker option (Patrol Logs).

Spec: `docs/superpowers/specs/2026-05-08-replay-session-cleanup-design.md`
Plan: `docs/superpowers/plans/2026-05-08-replay-session-cleanup.md`

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
```

Run the release:

```
tools/release.sh --notes-file /tmp/release_1_0_1a3_notes.md
```

Expected: tests pass, manifest bumped, tag pushed, GitHub release created (Latest, not prerelease, not draft), HACS refresh triggered.

If HACS shows the wrong version after a few minutes, restart HA per the existing memory.

- [ ] **Step 5: Verify in the running HA instance**

After HACS picks up the new release:

1. Restart HA, wait for the integration to settle (~30s).
2. Check that `camera.dreame_a2_mower_map` shows the live view of the active map — no historical M_PATH visible, replay-session pick should NOT change this camera.
3. Pick a session in the Work Logs view of the dashboard — verify `camera.dreame_a2_mower_work_log` updates immediately, the Main view stays unchanged, the picker holds its selection across the next 10-20 seconds.
4. Pick the placeholder option — Work Log camera goes to "Image not available".
5. On the per-map static cameras (`camera.dreame_a2_mower_map_1` etc.), verify the M_PATH overlay is now visibly black and clearly visible over the green mowing zones.

If anything misbehaves, dump diagnostics via `dreame_a2_mower.discover_cloud_api` and read the result; otherwise the release is good.
