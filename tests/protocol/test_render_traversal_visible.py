"""End-to-end: render_with_trail draws mowing in light-green and traversal in grey."""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import (
    _DEFAULT_PALETTE,
    render_with_trail,
)


def _tiny_map() -> MapData:
    """Build a 10m × 10m (10000mm × 10000mm) map with one mowing zone.

    Uses the same MapData field layout as other protocol tests.
    Coordinates are in cloud-frame mm.
    """
    return MapData(
        md5="test-traversal",
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


def _collect_pixels(png_bytes: bytes) -> set:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


# Legs are in metres (x_m, y_m) — same as live_map.legs and track_segments.
# Map is 10m × 10m (bx2=10000mm, by2=10000mm).

def test_traversal_color_appears_when_local_leg_extends_past_cloud():
    """Cloud has a short mowing segment; local leg continues past it (dock return).

    The post-cloud points must render in traversal_color, not mow_trail_color.
    Local legs and cloud_segments are in metres, matching the live-map / session
    track data format.
    """
    # Cloud: mowing segment from (2,5) to (4,5) metres
    cloud = [[(2.0, 5.0), (4.0, 5.0)]]
    # Local: same mowing segment + a traversal tail to (8,8)
    local = [[(2.0, 5.0), (4.0, 5.0), (8.0, 8.0)]]

    png = render_with_trail(
        _tiny_map(),
        local_legs=local,
        cloud_segments=cloud,
    )
    px = _collect_pixels(png)

    grey = _DEFAULT_PALETTE["traversal_color"]
    light = _DEFAULT_PALETTE["mow_trail_color"]
    assert light in px, f"expected mow_trail_color {light} pixels, got none"
    assert grey in px, f"expected traversal_color {grey} pixels, got none"


def test_no_traversal_when_local_matches_cloud_exactly():
    """When local trail == cloud trail exactly, no traversal pixels should appear."""
    cloud = [[(2.0, 5.0), (4.0, 5.0)]]
    local = [[(2.0, 5.0), (4.0, 5.0)]]

    png = render_with_trail(
        _tiny_map(),
        local_legs=local,
        cloud_segments=cloud,
    )
    px = _collect_pixels(png)
    grey = _DEFAULT_PALETTE["traversal_color"]
    assert grey not in px, (
        f"no traversal pixels expected when local == cloud, but found {grey}"
    )


def test_legacy_legs_kwarg_still_works():
    """Back-compat: passing the old positional/legacy 'legs' kwarg still renders."""
    legs = [[(2.0, 5.0), (4.0, 5.0)]]
    # Old call style: render_with_trail(map_data, legs, ...)
    png = render_with_trail(_tiny_map(), legs)
    assert isinstance(png, bytes)
    assert len(png) > 0
