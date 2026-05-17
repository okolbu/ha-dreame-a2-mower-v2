"""Unit tests for map_render.extract_projection."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.dreame_a2_mower.map_render import extract_projection


def test_extract_projection_returns_expected_keys():
    map_data = SimpleNamespace(
        bx1=100.0, by1=200.0,
        bx2=12345.6, by2=7890.1, pixel_size_mm=50.0,
        width_px=637, height_px=717,
        dock_xy=(500.0, 1500.0),
    )
    proj = extract_projection(map_data)
    assert proj == {
        "bx1_mm": 100.0,
        "by1_mm": 200.0,
        "bx2_mm": 12345.6,
        "by2_mm": 7890.1,
        "pixel_size_mm": 50.0,
        "width_px": 637,
        "height_px": 717,
        "dock_xy_mm": [500.0, 1500.0],
    }
    # Guard against accidental key additions / drops.
    assert len(proj) == 8


def test_extract_projection_omits_dock_when_none():
    """dock_xy_mm only present when MapData has a dock position."""
    map_data = SimpleNamespace(
        bx1=0.0, by1=0.0, bx2=10000.0, by2=10000.0,
        pixel_size_mm=50.0, width_px=200, height_px=200,
        dock_xy=None,
    )
    proj = extract_projection(map_data)
    assert "dock_xy_mm" not in proj
    assert len(proj) == 7


def test_extract_projection_none_returns_none():
    """Sessions may be picked before MapData is fetched. Don't crash."""
    assert extract_projection(None) is None
