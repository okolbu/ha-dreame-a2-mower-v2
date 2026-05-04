# Replay Map — Obstacle Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the legacy integration's "blue blob" obstacle overlay on the replay map so users can see where the mower bumped into things during a session.

**Architecture:** `protocol/session_summary.py` already decodes `obstacles: tuple[Obstacle, ...]` (metres-space polygons). We add a metres→pixels overlay helper in `live_map/trail.py`, extend `map_render.render_with_trail` with an `obstacle_polygons_m` parameter that draws the polygons in the same flipped-frame composite as the trail, and wire `SessionSummary.obstacles` through `coordinator.replay_session`. Live-session callers pass `None` and are unaffected.

**Tech Stack:** Python 3.13, Pillow (`PIL.ImageDraw`), pytest. Pure-Python protocol/render layers (no `homeassistant.*` imports).

**Scope notes:**
- `ai_obstacle` (`tuple[Any, ...]`) has unknown wire shape on g2408; the test fixture has zero entries. Out of scope — documented in Task 4 as a deferred follow-up.
- Live mowing renderer is unchanged: only the replay path passes obstacle polygons.
- Colour comes from legacy `protocol/trail_overlay.py` to match the original visual.

**Working dir:** `/data/claude/homeassistant/ha-dreame-a2-mower/`. Use `git -C <path>` and absolute paths; one-shot `cd` in a single Bash invocation is OK. Don't push until the end of the plan; controller pushes after the version bump task.

**Reference repo:** legacy at `/data/claude/homeassistant/ha-dreame-a2-mower-legacy/`. Key paths (read-only):
- `custom_components/dreame_a2_mower/protocol/trail_overlay.py:105-106` — `OBSTACLE_COLOR` / `OBSTACLE_OUTLINE` RGBA constants.
- `custom_components/dreame_a2_mower/protocol/trail_overlay.py:344-353` — `set_obstacles` polygon-to-pixel conversion (uses `self._m_to_px`, identical formula to our `render_trail_overlay`).
- `custom_components/dreame_a2_mower/protocol/trail_overlay.py:498-499` — `draw.polygon(poly, fill=OBSTACLE_COLOR, outline=OBSTACLE_OUTLINE)` — single primitive draws filled blob + edge.

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `custom_components/dreame_a2_mower/live_map/trail.py` | Modify | Add `render_obstacle_overlay(polygons_m, bx2, by2, pixel_size_mm)` mirroring `render_trail_overlay`. |
| `custom_components/dreame_a2_mower/map_render.py` | Modify | Add module-level `_OBSTACLE_FILL` / `_OBSTACLE_OUTLINE` colour constants; extend `render_with_trail` signature with `obstacle_polygons_m`; draw polygons in the flipped frame. |
| `custom_components/dreame_a2_mower/coordinator.py` | Modify | In `replay_session`, extract `[obs.polygon for obs in summary.obstacles]` and pass to `render_with_trail`. |
| `tests/live_map/test_trail.py` | Modify (or create if absent) | Test `render_obstacle_overlay` transform. |
| `tests/integration/test_map_render.py` | Modify | Test `render_with_trail` with obstacles parameter. |
| `tests/integration/test_coordinator.py` | Modify | Verify `replay_session` threads obstacles into the renderer. |
| `docs/TODO.md` | Modify | Strike the "Replay map: render session obstacles as blue blobs" entry; add a one-line follow-up for `ai_obstacle`. |
| `custom_components/dreame_a2_mower/manifest.json` | Modify | Bump `version` to `1.0.0a64`. |

---

## Task 1: Add `render_obstacle_overlay` helper in `live_map/trail.py`

**Files:**
- Modify: `custom_components/dreame_a2_mower/live_map/trail.py`
- Test: `tests/live_map/test_trail.py`

**Why:** The transform from metres to pixel coords for obstacle polygons is identical to the one already done by `render_trail_overlay` for trail legs. Extracting a sibling function (rather than reusing the trail one) keeps the call sites self-documenting and the unit shape (closed polygon vs. open path) explicit.

- [ ] **Step 1.1: Locate the existing test file or create it**

```bash
ls /data/claude/homeassistant/ha-dreame-a2-mower/tests/live_map/test_trail.py 2>/dev/null && echo exists || echo create
```

If "create", scaffold it:

```python
# tests/live_map/test_trail.py
"""Unit tests for live_map.trail helpers."""
from __future__ import annotations

import os
import sys

# Make custom_components importable for pure-Python imports.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from custom_components.dreame_a2_mower.live_map.trail import (  # noqa: E402
    render_trail_overlay,
)
```

If it already exists, just append the new tests in Step 1.2 to it; reuse whatever sys.path bootstrap is already there.

- [ ] **Step 1.2: Write the failing test**

Append to `tests/live_map/test_trail.py`:

```python
from custom_components.dreame_a2_mower.live_map.trail import (
    render_obstacle_overlay,
)


class TestRenderObstacleOverlay:
    """Obstacle polygons (metres) → pixel-coord polygons."""

    def test_empty_input_returns_empty_list(self):
        assert render_obstacle_overlay(
            polygons=[], bx2=10000.0, by2=10000.0, pixel_size_mm=50.0
        ) == []

    def test_none_input_returns_empty_list(self):
        assert render_obstacle_overlay(
            polygons=None, bx2=10000.0, by2=10000.0, pixel_size_mm=50.0
        ) == []

    def test_single_polygon_metres_to_pixels(self):
        # bx2 = 10000 mm, by2 = 10000 mm, grid = 50 mm/px.
        # Point (1.0, 2.0) m → cloud (1000, 2000) mm
        #   → px = (10000 - 1000)/50 = 180
        #   → py = (10000 - 2000)/50 = 160
        result = render_obstacle_overlay(
            polygons=[[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]],
            bx2=10000.0,
            by2=10000.0,
            pixel_size_mm=50.0,
        )
        assert result == [
            [(180.0, 160.0), (140.0, 120.0), (100.0, 80.0)],
        ]

    def test_skips_polygon_with_fewer_than_three_points(self):
        # A polygon needs at least 3 points to enclose area; ImageDraw
        # would degenerate and the legacy renderer drops these too.
        result = render_obstacle_overlay(
            polygons=[
                [(0.0, 0.0)],
                [(0.0, 0.0), (1.0, 1.0)],
                [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],  # kept
            ],
            bx2=10000.0,
            by2=10000.0,
            pixel_size_mm=50.0,
        )
        assert len(result) == 1
        assert len(result[0]) == 3

    def test_skips_malformed_points(self):
        # Defensive: points with <2 coords are dropped, rest of polygon kept.
        result = render_obstacle_overlay(
            polygons=[[(0.0, 0.0), (1.0,), (1.0, 0.0), (1.0, 1.0)]],
            bx2=10000.0,
            by2=10000.0,
            pixel_size_mm=50.0,
        )
        assert len(result) == 1
        assert len(result[0]) == 3  # one point dropped
```

- [ ] **Step 1.3: Run the test — verify it fails with ImportError**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest tests/live_map/test_trail.py::TestRenderObstacleOverlay -v 2>&1 | tail -15
```
Expected: ImportError or AttributeError on `render_obstacle_overlay`.

- [ ] **Step 1.4: Implement the helper**

Append to `custom_components/dreame_a2_mower/live_map/trail.py`:

```python
def render_obstacle_overlay(
    polygons: Iterable[Iterable[Point]] | None,
    bx2: float,
    by2: float,
    pixel_size_mm: float,
) -> list[list[tuple[float, float]]]:
    """Convert obstacle polygons (metres) to pixel-coord polygons.

    Uses the same flip transform as :func:`render_trail_overlay` so the
    obstacle blobs align with the lawn polygon rendered by the F2 base
    renderer.

    Args:
        polygons: Iterable of polygons; each polygon is an iterable of
            ``(x_m, y_m)`` tuples.  ``None`` is treated as empty.
        bx2: Right edge of the map bounding box in cloud-frame mm.
        by2: Bottom edge of the map bounding box in cloud-frame mm.
        pixel_size_mm: Grid resolution in mm/pixel (50.0 for g2408).

    Returns:
        List of pixel-coord polygons; each is a list of ``(px, py)``
        floats.  Polygons with fewer than 3 valid points are dropped
        (the legacy renderer dropped them too — a 2-point "polygon"
        renders as a degenerate line).
    """
    result: list[list[tuple[float, float]]] = []
    if not polygons:
        return result
    for poly in polygons:
        pts: list[tuple[float, float]] = []
        for p in poly:
            try:
                x_m = float(p[0])
                y_m = float(p[1])
            except (IndexError, TypeError, ValueError):
                continue
            cloud_x = x_m * _MM_PER_M
            cloud_y = y_m * _MM_PER_M
            px = (bx2 - cloud_x) / pixel_size_mm
            py = (by2 - cloud_y) / pixel_size_mm
            pts.append((px, py))
        if len(pts) >= 3:
            result.append(pts)
    return result
```

- [ ] **Step 1.5: Run the test — verify it passes**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest tests/live_map/test_trail.py::TestRenderObstacleOverlay -v 2>&1 | tail -15
```
Expected: 5 passed.

- [ ] **Step 1.6: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower add custom_components/dreame_a2_mower/live_map/trail.py tests/live_map/test_trail.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower commit -m "live_map/trail: add render_obstacle_overlay (m→px polygon transform)"
```

---

## Task 2: Extend `render_with_trail` with `obstacle_polygons_m` parameter

**Files:**
- Modify: `custom_components/dreame_a2_mower/map_render.py:396-508`
- Test: `tests/integration/test_map_render.py`

**Why:** The replay path needs the renderer to accept obstacle polygons and draw them on the composited image. New parameter is optional and defaults to `None`, so the live-session callers (coordinator lines 1311, 1374, 1530) keep working without changes — even though we'll only pass non-None from replay.

- [ ] **Step 2.1: Write the failing test**

Append to `tests/integration/test_map_render.py` inside the `TestRenderWithTrail` class (or in a sibling class — match whatever style is used for the class containing `test_empty_legs_returns_base_map`):

```python
def test_obstacles_change_output(self):
    """render_with_trail with obstacles produces different bytes than without."""
    md = _map_data()
    no_obs = render_with_trail(md, [])
    with_obs = render_with_trail(
        md,
        [],
        obstacle_polygons_m=[
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        ],
    )
    assert no_obs != with_obs, (
        "render_with_trail should paint obstacle polygons, "
        "yielding different bytes than the no-obstacle render"
    )

def test_obstacle_polygons_none_is_noop(self):
    """obstacle_polygons_m=None should equal obstacle_polygons_m unset."""
    md = _map_data()
    a = render_with_trail(md, [])
    b = render_with_trail(md, [], obstacle_polygons_m=None)
    assert a == b

def test_obstacle_polygons_empty_is_noop(self):
    """An empty obstacle list should equal the base+trail render with no obstacles."""
    md = _map_data()
    a = render_with_trail(md, [])
    b = render_with_trail(md, [], obstacle_polygons_m=[])
    assert a == b

def test_polygon_with_fewer_than_three_points_is_dropped(self):
    """Degenerate polygons (<3 pts) should not affect the output."""
    md = _map_data()
    a = render_with_trail(md, [], obstacle_polygons_m=[])
    b = render_with_trail(
        md,
        [],
        obstacle_polygons_m=[[(0.0, 0.0)], [(0.0, 0.0), (1.0, 1.0)]],
    )
    assert a == b
```

- [ ] **Step 2.2: Run the tests — verify they fail with TypeError**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest tests/integration/test_map_render.py -v -k "obstacle" 2>&1 | tail -15
```
Expected: TypeError "unexpected keyword argument 'obstacle_polygons_m'" on all four tests.

- [ ] **Step 2.3: Add colour constants near the existing trail constants in `map_render.py`**

Find the existing `_TRAIL_COLOR` declaration (around line 367) and add directly below it:

```python
# ---------------------------------------------------------------------------
# Replay-only obstacle overlay constants. Lifted from legacy
# protocol/trail_overlay.py:105-106 so the visual matches the pre-greenfield
# integration. RGBA — semi-transparent fill + slightly more opaque outline.
# ---------------------------------------------------------------------------
_OBSTACLE_FILL: tuple[int, int, int, int] = (90, 140, 230, 170)
_OBSTACLE_OUTLINE: tuple[int, int, int, int] = (40, 80, 200, 230)
```

- [ ] **Step 2.4: Update the `render_with_trail` signature and import**

Replace the signature at line 396 (currently 5-arg) with:

```python
def render_with_trail(
    map_data: "MapData",
    legs: "list[Leg] | None",
    palette: dict | None = None,
    mower_position_m: "tuple[float, float] | None" = None,
    mower_heading_deg: "float | None" = None,
    obstacle_polygons_m: "list[list[tuple[float, float]]] | None" = None,
) -> bytes:
```

Update the docstring `Args:` block to describe the new parameter (insert before the `Returns:` section):

```
        obstacle_polygons_m: Optional list of obstacle polygons in
            metres-space (e.g. ``SessionSummary.obstacles``).  Drawn
            as semi-transparent blue filled polygons.  ``None`` (the
            default) or empty list draws nothing — used by every live
            caller; only the replay path passes non-empty data.
```

Update the early-return predicate so the obstacle overlay can short-circuit base-only when nothing else is drawn. Change:

```python
    # If we have neither a trail to draw nor a mower position to mark,
    # the base map is the final output.
    if not legs and mower_position_m is None:
        return base_png
```

to:

```python
    # If we have nothing to overlay, the base map is the final output.
    if not legs and mower_position_m is None and not obstacle_polygons_m:
        return base_png
```

- [ ] **Step 2.5: Draw the obstacle polygons inside the flipped frame**

Locate this block (immediately after the trail-leg loop, just before the `if mower_position_m is not None:` block):

```python
        draw.line(leg_px, fill=_TRAIL_COLOR, width=_TRAIL_LINE_WIDTH)
        drawn_legs += 1
        drawn_points += len(leg_px)
```

Insert the obstacle overlay block immediately after the leg loop ends (i.e. after the `for leg_px in pixel_legs:` body) and before the existing `if mower_position_m is not None:` block:

```python
    drawn_obstacles = 0
    if obstacle_polygons_m:
        from .live_map.trail import render_obstacle_overlay

        pixel_polys = render_obstacle_overlay(
            polygons=obstacle_polygons_m,
            bx2=map_data.bx2,
            by2=map_data.by2,
            pixel_size_mm=map_data.pixel_size_mm,
        )
        for poly_px in pixel_polys:
            draw.polygon(poly_px, fill=_OBSTACLE_FILL, outline=_OBSTACLE_OUTLINE)
            drawn_obstacles += 1
```

Then update the trailing log line so the count surfaces. Replace:

```python
    _LOGGER.debug(
        "render_with_trail: drew %d legs / %d points → %d-byte PNG",
        drawn_legs,
        drawn_points,
        len(png_bytes),
    )
```

with:

```python
    _LOGGER.debug(
        "render_with_trail: drew %d legs / %d points / %d obstacles → %d-byte PNG",
        drawn_legs,
        drawn_points,
        drawn_obstacles,
        len(png_bytes),
    )
```

- [ ] **Step 2.6: Run the new tests — verify they pass**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest tests/integration/test_map_render.py -v -k "obstacle" 2>&1 | tail -15
```
Expected: 4 passed.

- [ ] **Step 2.7: Run the full map_render test file to confirm no regression**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest tests/integration/test_map_render.py -v 2>&1 | tail -25
```
Expected: every test still passes (existing tests were 0-arg or 5-arg; the new keyword-only addition with default `None` is backwards compatible).

- [ ] **Step 2.8: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower add custom_components/dreame_a2_mower/map_render.py tests/integration/test_map_render.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower commit -m "map_render: render_with_trail draws optional obstacle polygons

Lifts colour constants from legacy protocol/trail_overlay.py so the
replay map visually matches the pre-greenfield integration. Live
callers pass None and are unaffected."
```

---

## Task 3: Wire `SessionSummary.obstacles` through `replay_session`

**Files:**
- Modify: `custom_components/dreame_a2_mower/coordinator.py:1383-1545` (the `replay_session` method)
- Test: `tests/integration/test_coordinator.py`

**Why:** This is the only render path with access to a `SessionSummary` (live mowing builds legs incrementally and never has obstacle data). Pulling obstacles here keeps the live path zero-cost.

- [ ] **Step 3.1: Locate the relevant test class**

Run:
```bash
grep -n "replay_session\|class Test" /data/claude/homeassistant/ha-dreame-a2-mower/tests/integration/test_coordinator.py | head -25
```

Use the existing `replay_session` test class (most likely `TestReplaySession` or similar). If there isn't one yet, add the new tests alongside the closest existing replay test. Note the class name for Step 3.3.

- [ ] **Step 3.2: Inspect the existing replay test pattern**

Run:
```bash
grep -B2 -A40 "def test.*replay" /data/claude/homeassistant/ha-dreame-a2-mower/tests/integration/test_coordinator.py | head -80
```

Note how the test stubs `render_with_trail` (likely via `monkeypatch` or a captured call list). Mirror that pattern in Step 3.3.

- [ ] **Step 3.3: Write the failing test**

Add to the same test class identified in Step 3.1. Adapt the stub style to match the existing pattern (this is a sketch — substitute the class name and the existing fixture/helper names from grep output):

```python
async def test_replay_session_passes_obstacles_to_renderer(
    self, hass, coordinator_with_archive_fixture
):
    """replay_session should extract Obstacle.polygon tuples and pass
    them to render_with_trail under the obstacle_polygons_m kwarg.
    """
    # Capture the kwargs of render_with_trail for assertion.
    captured: dict = {}

    def fake_render(map_data, legs, *args, **kwargs):
        captured["legs"] = legs
        captured["kwargs"] = kwargs
        return b"PNGFAKE"

    # Patch the symbol the coordinator imports inside replay_session.
    import custom_components.dreame_a2_mower.map_render as map_render_mod
    monkeypatch.setattr(map_render_mod, "render_with_trail", fake_render)

    # Drive: archive contains the 2026-04-18 fixture (7 obstacles).
    await coordinator_with_archive_fixture.replay_session(
        FIXTURE_SESSION_MD5_OR_FILENAME
    )

    polys = captured["kwargs"].get("obstacle_polygons_m")
    assert polys is not None, "replay_session must pass obstacle_polygons_m"
    assert len(polys) == 7, "fixture has 7 obstacle polygons"
    # Each polygon is a list/tuple of (x_m, y_m) pairs in metres.
    for poly in polys:
        assert len(poly) >= 3
        for x, y in poly:
            assert isinstance(x, float)
            assert isinstance(y, float)


async def test_replay_session_with_no_obstacles_passes_empty_list(
    self, hass, coordinator_with_no_obstacle_fixture
):
    """A session with zero obstacles still passes an empty list (not
    None) so the renderer's overlay branch is consistent."""
    captured: dict = {}

    def fake_render(map_data, legs, *args, **kwargs):
        captured["kwargs"] = kwargs
        return b"PNGFAKE"

    import custom_components.dreame_a2_mower.map_render as map_render_mod
    monkeypatch.setattr(map_render_mod, "render_with_trail", fake_render)

    await coordinator_with_no_obstacle_fixture.replay_session(NO_OBS_KEY)
    polys = captured["kwargs"].get("obstacle_polygons_m")
    assert polys == []
```

If the existing test file uses class-scoped patches (`@pytest.fixture` returning the patched module) instead of `monkeypatch`, refactor the snippet to match. The behavioural assertions are the load-bearing part — the patching style is style-only.

- [ ] **Step 3.4: Run the test — verify it fails**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest tests/integration/test_coordinator.py -v -k "replay_session_passes_obstacles or replay_session_with_no_obstacles" 2>&1 | tail -20
```
Expected: AssertionError — `polys` is `None` because the coordinator doesn't pass obstacles yet.

- [ ] **Step 3.5: Update `replay_session` to extract and pass obstacles**

In `custom_components/dreame_a2_mower/coordinator.py`, find the section after `summary = _session_summary.parse_session_summary(raw_dict)` (around line 1453). Right after the existing `legs = [list(seg) for seg in summary.track_segments]` block (around line 1463-1465), add:

```python
        # Replay-only overlay: each Obstacle.polygon is already a tuple
        # of (x_m, y_m) pairs (the protocol decoder handled the cm→m
        # conversion). Pass empty list rather than None when the session
        # has none, so the renderer's branch is consistent.
        obstacle_polygons_m: list[list[tuple[float, float]]] = [
            list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3
        ]
```

Then locate the final `render_with_trail` call (around line 1529-1531):

```python
        png = await self.hass.async_add_executor_job(
            render_with_trail, map_data, legs
        )
```

Replace with a call that uses keyword args (matches the new signature):

```python
        from functools import partial

        png = await self.hass.async_add_executor_job(
            partial(
                render_with_trail,
                map_data,
                legs,
                obstacle_polygons_m=obstacle_polygons_m,
            )
        )
```

(`async_add_executor_job` does not pass keyword arguments, hence `partial`.)

- [ ] **Step 3.6: Run the new tests — verify they pass**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest tests/integration/test_coordinator.py -v -k "replay_session_passes_obstacles or replay_session_with_no_obstacles" 2>&1 | tail -20
```
Expected: 2 passed.

- [ ] **Step 3.7: Run the full coordinator test file to confirm no regressions**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest tests/integration/test_coordinator.py -v 2>&1 | tail -25
```
Expected: all tests pass.

- [ ] **Step 3.8: Run the full test suite as a smoke check**

Run:
```bash
cd /data/claude/homeassistant/ha-dreame-a2-mower && pytest -q 2>&1 | tail -15
```
Expected: full pass count, no failures.

- [ ] **Step 3.9: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower add custom_components/dreame_a2_mower/coordinator.py tests/integration/test_coordinator.py
git -C /data/claude/homeassistant/ha-dreame-a2-mower commit -m "coordinator: replay_session draws session obstacles on the map"
```

---

## Task 4: Update TODO.md and bump version

**Files:**
- Modify: `docs/TODO.md`
- Modify: `custom_components/dreame_a2_mower/manifest.json`

**Why:** Strike the implemented item from the TODO and add a small follow-up note for the deferred `ai_obstacle` work so the rationale isn't lost. Bump the manifest version so HACS surfaces an update.

- [ ] **Step 4.1: Strike the TODO entry and add the deferred note**

In `docs/TODO.md`, remove the entire `### Replay map: render session obstacles as blue blobs` section (the block beginning around line 37 and ending before the next `###` heading, currently `### Patrol Logs ...`).

Add a short follow-up entry under the next available place (immediately above the next `###` heading, or inline as a one-liner inside an existing investigation entry — pick whichever reads better in context):

```markdown
### `ai_obstacle` blob format — capture wire shape

`SessionSummary.ai_obstacle` is currently typed as `tuple[Any, ...]`
because no g2408 session in the corpus has produced one (every captured
session has `ai_obstacle: []`). Likely an AI-detected obstacle (pet,
person, etc.) tied to the AI camera; the legacy integration treated
ai_obstacles separately from regular obstacles. When the first
non-empty payload appears, decode it in `protocol/session_summary.py`
and decide whether to render in a different colour (e.g. orange) on
the replay map.

Capture procedure:

1. Bookmark the probe log + snapshot the session_summary fetch.
2. Drive the mower past a pet / person / known AI-trigger object
   during a session.
3. End the session, retrieve the OSS JSON from the cloud, save the
   `ai_obstacle` array as a fixture under
   `tests/protocol/fixtures/`.
4. Update `Obstacle`-style decoder + tests + renderer to distinguish.
```

Update the "Last updated" line near the top of TODO.md to reflect today's date and the upcoming version: change `Last updated: 2026-04-30 (v1.0.0a60).` to `Last updated: 2026-05-04 (v1.0.0a64).`

Also add a new "Recently shipped" bullet at the top of that section:

```markdown
- **v1.0.0a64** — Replay map redraws session obstacles as semi-transparent
  blue polygons (lifted colour from legacy `protocol/trail_overlay.py`).
  `render_with_trail` gains an optional `obstacle_polygons_m` parameter;
  `coordinator.replay_session` extracts `summary.obstacles` and passes
  them through. Live mowing renderer is unchanged. `ai_obstacle` is
  still un-rendered — see open item.
```

- [ ] **Step 4.2: Bump the manifest version**

Edit `custom_components/dreame_a2_mower/manifest.json`:

```diff
-  "version": "1.0.0a63"
+  "version": "1.0.0a64"
```

- [ ] **Step 4.3: Commit**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower add docs/TODO.md custom_components/dreame_a2_mower/manifest.json
git -C /data/claude/homeassistant/ha-dreame-a2-mower commit -m "v1.0.0a64: replay-map obstacle overlay shipped"
```

---

## Task 5: Tag, push, and cut a GitHub Release

**Files:** none (git operations only)

**Why:** Memory entry "Every version needs a GitHub Release" — HACS reads Releases, not commits or tags alone. This task ships the change to users.

- [ ] **Step 5.1: Push main**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower push origin main
```

- [ ] **Step 5.2: Tag**

```bash
git -C /data/claude/homeassistant/ha-dreame-a2-mower tag -a v1.0.0a64 -m "v1.0.0a64: replay map renders session obstacle polygons"
git -C /data/claude/homeassistant/ha-dreame-a2-mower push origin v1.0.0a64
```

- [ ] **Step 5.3: Create the GitHub Release**

```bash
gh release create v1.0.0a64 \
  --repo okolbu/ha-dreame-a2-mower \
  --prerelease \
  --title "v1.0.0a64 — Replay map obstacle overlay" \
  --notes "$(cat <<'EOF'
## Replay map redraws session obstacles

The legacy integration's blue-blob obstacle overlay is back on the
replay map. Each obstacle the mower bumped into during a session is
drawn as a semi-transparent blue polygon at its actual encounter
position.

Affects:
- `lawn_mower` camera entity / dashboard replay views
- The `dreame_a2_mower.replay_session` service

No changes to live mowing rendering.

### Known gaps

- `ai_obstacle` (AI-camera-detected obstacles like pets / people)
  is still un-rendered — its wire format hasn't been captured yet.
  See `docs/TODO.md` for the capture procedure.
EOF
)"
```

- [ ] **Step 5.4: Verify HACS sees the new release**

```bash
gh release view v1.0.0a64 --repo okolbu/ha-dreame-a2-mower --json tagName,isPrerelease,publishedAt
```
Expected: `tagName: v1.0.0a64`, `isPrerelease: true`.

---

## Self-review checklist (run before handing off)

1. **Spec coverage**: TODO entry called for (a) extending the renderer, (b) picking a legacy-matching colour, (c) distinguishing `obstacle` vs `ai_obstacle`. Tasks 1+2 cover (a), Task 2 colour constants cover (b), Task 4 documents the deferred decision on (c) with rationale.
2. **No placeholders**: each step has the exact code/command/diff. The Task 3 test sketch flags "substitute the existing fixture/helper names" — this is intentional because the actual fixture names are not in this conversation's context; Step 3.1/3.2 are explicit grep steps to pin them down before writing.
3. **Type consistency**: parameter is `obstacle_polygons_m: list[list[tuple[float, float]]] | None` everywhere it appears (signature, coordinator call site, helper). Helper return type is `list[list[tuple[float, float]]]`.
4. **Frequent commits**: 5 commits across 5 tasks, one push at the end.
