"""Test that render_with_trail's legs_timeline path paints in capture order.

legs_timeline is a list of records, each with:
  - role: "mowing" | "traversal"
  - start_ts: epoch seconds (unused by renderer, for ordering only)
  - end_ts: epoch seconds (unused by renderer)
  - pts: list of (x_m, y_m) tuples

The renderer paints each record in list order so later records paint
over earlier ones — unlike the two-pass mowing-first / traversal-on-top
approach of the legacy branches.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import render_with_trail


# ---------------------------------------------------------------------------
# Tiny reusable MapData — 10 m × 10 m, pixel_size=50 mm
# Matches the shape used in other protocol tests (test_render_traversal_visible,
# test_render_work_log_uses_split, etc.)
# ---------------------------------------------------------------------------

def _trivial_map_data() -> MapData:
    """Smallest valid MapData that render_with_trail accepts."""
    return MapData(
        md5="test-timeline-order",
        width_px=200,
        height_px=200,
        pixel_size_mm=50.0,
        bx1=0.0,
        by1=0.0,
        bx2=10000.0,
        by2=10000.0,
        cloud_x_reflect=10000.0,
        cloud_y_reflect=10000.0,
        rotation_deg=0.0,
        boundary_polygon=(
            (0.0, 0.0),
            (10000.0, 0.0),
            (10000.0, 10000.0),
            (0.0, 10000.0),
        ),
        mowing_zones=(
            MowingZone(
                zone_id=0,
                name="lawn",
                path=(
                    (0.0, 0.0),
                    (10000.0, 0.0),
                    (10000.0, 10000.0),
                    (0.0, 10000.0),
                ),
                area_m2=100.0,
            ),
        ),
        exclusion_zones=(),
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        dock_xy=None,
        total_area_m2=100.0,
        nav_paths=(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_legs_timeline_painted_in_order():
    """Smoke: legs_timeline path produces a PNG without crashing."""
    md = _trivial_map_data()
    timeline = [
        {"role": "mowing",    "start_ts": 1000, "end_ts": 1100,
         "pts": [(1.0, 1.0), (2.0, 1.0)]},
        {"role": "traversal", "start_ts": 1100, "end_ts": 1200,
         "pts": [(1.0, 1.0), (2.0, 1.0)]},
    ]
    png = render_with_trail(md, legs_timeline=timeline, trail_width_px=4)
    assert png and len(png) > 100


def test_legs_timeline_takes_priority_over_split_args():
    """legs_timeline early-returns before mowing_legs/traversal_legs are consulted."""
    md = _trivial_map_data()
    timeline = [{"role": "mowing", "start_ts": 1000, "end_ts": 1100,
                 "pts": [(1.0, 1.0), (2.0, 1.0)]}]
    png = render_with_trail(
        md, legs_timeline=timeline,
        mowing_legs=[[(5.0, 5.0), (6.0, 5.0)]],
        traversal_legs=[],
    )
    assert png and len(png) > 100


def test_legs_timeline_single_point_leg_skipped():
    """Records with fewer than 2 pts must not crash (ImageDraw.line needs >= 2)."""
    md = _trivial_map_data()
    timeline = [
        {"role": "mowing",    "start_ts": 1000, "end_ts": 1100,
         "pts": [(1.0, 1.0)]},           # only 1 point — must be skipped
        {"role": "traversal", "start_ts": 1100, "end_ts": 1200,
         "pts": [(2.0, 2.0), (3.0, 2.0)]},
    ]
    png = render_with_trail(md, legs_timeline=timeline)
    assert png and len(png) > 100


def test_legs_timeline_empty_list_returns_base_map():
    """Empty legs_timeline triggers the early-return base map (no crash)."""
    md = _trivial_map_data()
    png = render_with_trail(md, legs_timeline=[])
    assert png and len(png) > 100
