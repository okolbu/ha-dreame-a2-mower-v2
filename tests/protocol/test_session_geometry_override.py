"""Tests for apply_session_geometry — session-time no-go/spot override.

Verifies the reflection matches parse_cloud_map's exclusion convention
(x_reflect - x_mm) and that the canvas/projection is untouched (so trail
alignment is preserved).
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.map_decoder import (
    apply_session_geometry,
    parse_cloud_map,
)


def _base_map():
    md = parse_cloud_map(
        {"boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000},
         "mowingAreas": {}, "totalArea": 100}
    )
    assert md is not None
    # x_reflect = bx1+bx2 = 10000, y_reflect = 10000
    assert md.cloud_x_reflect == 10000 and md.cloud_y_reflect == 10000
    return md


def test_exclusion_reflected_into_renderer_coords():
    base = _base_map()
    xr, yr = base.cloud_x_reflect, base.cloud_y_reflect
    # exclusion polygon in METRES (charger-relative, trail frame)
    excl = [[(1.0, 2.0), (1.5, 2.0), (1.5, 2.5), (1.0, 2.5)]]
    out = apply_session_geometry(base, exclusion_polys_m=excl, spot_polys_m=[])
    assert len(out.exclusion_zones) == 1
    pts = out.exclusion_zones[0].points
    # metres → mm (×1000), then midline reflect (x_reflect - x_mm)
    assert pts[0] == (xr - 1000.0, yr - 2000.0)
    assert pts[1] == (xr - 1500.0, yr - 2000.0)
    assert pts[2] == (xr - 1500.0, yr - 2500.0)


def test_canvas_and_projection_unchanged():
    base = _base_map()
    out = apply_session_geometry(
        base,
        exclusion_polys_m=[[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]],
        spot_polys_m=[],
    )
    # boundary box + reflections + pixel grid are untouched (trail still aligns)
    assert (out.bx1, out.by1, out.bx2, out.by2) == (base.bx1, base.by1, base.bx2, base.by2)
    assert out.cloud_x_reflect == base.cloud_x_reflect
    assert out.width_px == base.width_px and out.height_px == base.height_px


def test_degenerate_dropped_and_spots_reflected():
    base = _base_map()
    out = apply_session_geometry(
        base,
        exclusion_polys_m=[[(1.0, 1.0), (2.0, 1.0)]],  # <3 pts → dropped
        spot_polys_m=[[(3.0, 3.0), (4.0, 3.0), (4.0, 4.0), (3.0, 4.0)]],
    )
    assert out.exclusion_zones == ()
    assert len(out.spot_zones) == 1
    assert out.spot_zones[0].points[0] == (
        base.cloud_x_reflect - 3000.0, base.cloud_y_reflect - 3000.0,
    )


def test_empty_inputs_clear_zones():
    base = _base_map()
    out = apply_session_geometry(base, exclusion_polys_m=[], spot_polys_m=[])
    assert out.exclusion_zones == ()
    assert out.spot_zones == ()
