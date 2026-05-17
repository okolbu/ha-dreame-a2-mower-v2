"""render_base_map honours lawn_mode=dark for active/finished mow renders."""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import (
    _DEFAULT_PALETTE,
    render_base_map,
)


def _tiny_map() -> MapData:
    """10m × 10m map with one mowing zone (zone_id=1 → zone_fills[0])."""
    return MapData(
        md5="test-lawn-mode",
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
                zone_id=1,  # zone_id=1 → zone_fills[(1-1) % n] = zone_fills[0]
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


def _pixel_set(png_bytes: bytes) -> set:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


def test_default_lawn_mode_light_green():
    """Default (lawn_mode='light') renders zone 1 in zone_fills[0] (light green)."""
    png = render_base_map(_tiny_map())
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    assert light_green in _pixel_set(png), (
        f"Expected light-green zone fill {light_green!r} with default lawn_mode"
    )


def test_lawn_mode_dark_uses_dark_green():
    """lawn_mode='dark' swaps zone_fills[0] to dark_green."""
    dark_green = _DEFAULT_PALETTE["dark_green"]
    png = render_base_map(_tiny_map(), lawn_mode="dark")
    assert dark_green in _pixel_set(png), (
        f"Expected dark_green {dark_green!r} pixels with lawn_mode='dark'"
    )


def test_lawn_mode_light_explicit_same_as_default():
    """lawn_mode='light' is identical to the implicit default."""
    a = render_base_map(_tiny_map())
    b = render_base_map(_tiny_map(), lawn_mode="light")
    assert a == b, "lawn_mode='light' should produce identical output to default"


def test_lawn_mode_dark_no_light_green_zone_fill():
    """With lawn_mode='dark', the light-green zone fill should not be the
    primary zone colour (dark_green has replaced zone_fills[0])."""
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    dark_green = _DEFAULT_PALETTE["dark_green"]
    # They must differ for this test to be meaningful.
    assert light_green != dark_green

    png = render_base_map(_tiny_map(), lawn_mode="dark")
    px = _pixel_set(png)
    assert dark_green in px, f"dark_green {dark_green!r} must be present"
    # light_green should NOT appear as a zone fill (it's still in the palette
    # but zone_fills[0] was replaced; light_green may appear from trail strokes
    # in render_with_trail callers, but render_base_map alone won't draw it).
    assert light_green not in px, (
        f"light-green {light_green!r} should not appear in dark-mode base render "
        f"(zone_fills[0] was replaced by dark_green)"
    )
