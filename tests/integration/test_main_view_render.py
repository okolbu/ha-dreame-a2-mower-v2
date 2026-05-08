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
