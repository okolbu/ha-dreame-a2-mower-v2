"""Verify render_work_log correctly forwards local_legs + cloud_segments to
render_with_trail so that traversal arcs render in grey, not mowing green.

This is the unit-level regression for the Phase 1 plumbing drop:
render_work_log_session was passing only legs= (cloud track_segments) to
render_work_log, so split_trail always received local_legs=[] and classified
everything as mowing (all light-green).
"""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import (
    _DEFAULT_PALETTE,
    render_work_log,
    render_with_trail,
)


# ---------------------------------------------------------------------------
# Tiny reusable MapData — 10 m × 10 m, pixel_size=50 mm
# ---------------------------------------------------------------------------

def _tiny_map() -> MapData:
    return MapData(
        md5="test-worklog-split",
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


def _pixels(png_bytes: bytes) -> set:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_render_work_log_local_plus_cloud_gives_both_colors():
    """render_work_log with local_legs + cloud_segments produces both green and grey.

    Regression for: render_work_log_session passed only legs= (cloud segments),
    leaving local_legs=[] so split_trail classified everything as mowing → all green.
    """
    # Cloud mowing segment: (2,5)→(4,5)
    cloud = [[(2.0, 5.0), (4.0, 5.0)]]
    # Local full trail: same mowing + traversal tail (8,8) = dock return
    local = [[(2.0, 5.0), (4.0, 5.0), (8.0, 8.0)]]

    png = render_work_log(_tiny_map(), local_legs=local, cloud_segments=cloud)
    px = _pixels(png)

    mow_color = _DEFAULT_PALETTE["mow_trail_color"]
    trav_color = _DEFAULT_PALETTE["traversal_color"]

    assert mow_color in px, (
        f"mow_trail_color {mow_color} not found — cloud segment missing from render"
    )
    assert trav_color in px, (
        f"traversal_color {trav_color} not found — traversal arc rendered as mowing"
    )


def test_render_work_log_legacy_legs_kwarg_still_works():
    """Back-compat: old callers passing legs= alone still get a valid PNG."""
    legs = [[(2.0, 5.0), (4.0, 5.0)]]
    png = render_work_log(_tiny_map(), legs=legs)
    assert isinstance(png, bytes) and len(png) > 0


def test_render_work_log_empty_legs_does_not_crash():
    """Empty inputs fall through to base-map render (no trail) gracefully."""
    png = render_work_log(_tiny_map(), local_legs=[], cloud_segments=[])
    assert isinstance(png, bytes) and len(png) > 0


def test_render_work_log_only_cloud_segments_all_mowing():
    """Supplying only cloud_segments (no local) → everything classified as mowing."""
    cloud = [[(2.0, 5.0), (4.0, 5.0)]]
    png = render_work_log(_tiny_map(), cloud_segments=cloud)
    px = _pixels(png)

    mow_color = _DEFAULT_PALETTE["mow_trail_color"]
    trav_color = _DEFAULT_PALETTE["traversal_color"]

    assert mow_color in px, "mowing color missing when only cloud_segments provided"
    assert trav_color not in px, (
        "traversal color should not appear when no local_legs provided"
    )
