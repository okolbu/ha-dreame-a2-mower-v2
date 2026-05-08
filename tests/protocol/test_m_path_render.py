"""Tests for M_PATH overlay drawing in render_base_map."""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.cloud_state import MowPathData
from custom_components.dreame_a2_mower.map_decoder import MapData
from custom_components.dreame_a2_mower.map_render import render_base_map


def _make_min_map():
    return MapData(
        md5="test",
        width_px=100,
        height_px=100,
        pixel_size_mm=50.0,
        bx1=0.0, by1=0.0, bx2=5000.0, by2=5000.0,
        cloud_x_reflect=5000.0, cloud_y_reflect=5000.0,
        rotation_deg=0.0,
        boundary_polygon=((0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0), (0.0, 5000.0)),
        mowing_zones=(),
        exclusion_zones=(),
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        dock_xy=None,
        total_area_m2=10.0,
        nav_paths=(),
    )


def test_render_base_map_with_m_path_draws_pixels():
    """A MowPathData with one 2-point segment produces colored pixels along the line."""
    mp = MowPathData(
        map_id=0,
        segments=(((1000, 2500), (4000, 2500)),),  # horizontal line through middle
    )
    map_data = _make_min_map()
    distinct_color = (10, 200, 80, 255)
    png_bytes = render_base_map(
        map_data,
        palette={"m_path": distinct_color, "m_path_width_px": 4},
        m_path=mp,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    pixels = list(img.getdata())
    matching = [px for px in pixels if px == distinct_color]
    assert len(matching) > 0, (
        f"Expected at least one pixel with m_path color {distinct_color!r}, "
        f"got 0. Top colors: "
        f"{sorted(set(pixels), key=lambda c: -pixels.count(c))[:5]}"
    )


def test_render_base_map_without_m_path_no_overlay_color():
    """Baseline (m_path=None) doesn't contain the override color."""
    map_data = _make_min_map()
    distinct_color = (10, 200, 80, 255)
    png_bytes = render_base_map(
        map_data,
        palette={"m_path": distinct_color, "m_path_width_px": 4},
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    matching = [px for px in img.getdata() if px == distinct_color]
    assert len(matching) == 0


def test_render_base_map_with_empty_segments():
    """An m_path with no segments doesn't crash and draws nothing override-colored."""
    mp = MowPathData(map_id=0, segments=())
    map_data = _make_min_map()
    distinct_color = (10, 200, 80, 255)
    png_bytes = render_base_map(
        map_data,
        palette={"m_path": distinct_color, "m_path_width_px": 4},
        m_path=mp,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    matching = [px for px in img.getdata() if px == distinct_color]
    assert len(matching) == 0


def test_render_base_map_with_multi_segment_m_path():
    """Two distinct segments both produce colored pixels (segment-break sentinel)."""
    mp = MowPathData(
        map_id=0,
        segments=(
            ((1000, 1000), (4000, 1000)),  # bottom horizontal
            ((1000, 4000), (4000, 4000)),  # top horizontal
        ),
    )
    map_data = _make_min_map()
    distinct_color = (10, 200, 80, 255)
    png_bytes = render_base_map(
        map_data,
        palette={"m_path": distinct_color, "m_path_width_px": 4},
        m_path=mp,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    matching = [px for px in img.getdata() if px == distinct_color]
    assert len(matching) > 0


def test_default_m_path_palette_is_black():
    """The default _DEFAULT_PALETTE['m_path'] is opaque black."""
    from custom_components.dreame_a2_mower.map_render import _DEFAULT_PALETTE

    assert _DEFAULT_PALETTE["m_path"] == (0, 0, 0, 255)
    # Width unchanged from Task 14 of cloud-discovery integration.
    assert _DEFAULT_PALETTE["m_path_width_px"] == 4


def test_m_path_drawn_above_mowing_zones():
    """An M_PATH segment crossing a mowing-zone polygon should be the
    M_PATH color, not zone-tinted (would mean it's drawn under the zone)."""
    from custom_components.dreame_a2_mower.map_decoder import MowingZone

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
        ), name="zone1"),),
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
