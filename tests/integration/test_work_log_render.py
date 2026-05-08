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
