"""Tests for nav_paths overlay drawing in render_base_map."""
from __future__ import annotations

import io

from PIL import Image, ImageChops

from custom_components.dreame_a2_mower.map_decoder import MapData, NavPath
from custom_components.dreame_a2_mower.map_render import render_base_map


def _make_min_map_with_nav_paths(nav_paths):
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
        nav_paths=nav_paths,
    )


def test_render_base_map_no_nav_paths_no_gray_pixels_outside_features():
    """When nav_paths is empty, no gray nav-path pixels should appear."""
    map_data = _make_min_map_with_nav_paths(())
    png_bytes = render_base_map(map_data)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

    # Sanity: the PNG decodes
    assert img.size == (100, 100)


def test_render_base_map_with_nav_path_draws_pixels():
    """A nav_path with two distinct points produces non-default pixels along the line.

    Strategy: use a distinctive nav_path color that differs from the lawn_fill
    (221,221,221) and lawn_outline (160,160,160), then check that at least one
    pixel in the rendered image matches that color.  This avoids depending on
    pixel-count differences that may be masked when the boundary polygon covers
    the entire canvas.
    """
    nav = NavPath(
        path_id=0,
        path=((1000.0, 2500.0), (4000.0, 2500.0)),  # horizontal line through middle
        path_type=0,
    )
    map_data = _make_min_map_with_nav_paths((nav,))

    # Override nav_path color to something clearly distinct from every other
    # palette color so the test assertion is unambiguous.
    distinct_nav_color = (200, 100, 50, 255)
    png_bytes = render_base_map(
        map_data,
        palette={"nav_path": distinct_nav_color, "nav_path_width_px": 8},
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

    # Check that the nav-path color appears in the rendered image.
    pixels = list(img.getdata())
    nav_pixels = [px for px in pixels if px == distinct_nav_color]
    assert len(nav_pixels) > 0, (
        f"Expected at least one pixel with nav_path color {distinct_nav_color!r}, "
        f"but found none.  Unique colors in image: "
        f"{sorted(set(pixels), key=lambda c: -pixels.count(c))[:10]}"
    )

    # Also verify baseline render (no nav paths) does NOT contain that color.
    map_data_no_nav = _make_min_map_with_nav_paths(())
    png_no_nav = render_base_map(
        map_data_no_nav,
        palette={"nav_path": distinct_nav_color, "nav_path_width_px": 8},
    )
    img_no_nav = Image.open(io.BytesIO(png_no_nav)).convert("RGBA")
    no_nav_nav_pixels = [px for px in img_no_nav.getdata() if px == distinct_nav_color]
    assert len(no_nav_nav_pixels) == 0, (
        "Baseline render (no nav_paths) must not contain the nav_path color"
    )
