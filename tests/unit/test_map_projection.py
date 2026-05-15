"""Unit tests for map_render.extract_projection."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.dreame_a2_mower.map_render import extract_projection


def test_extract_projection_returns_five_keys():
    map_data = SimpleNamespace(
        bx2=12345.6, by2=7890.1, pixel_size_mm=50.0,
        width_px=637, height_px=717,
    )
    proj = extract_projection(map_data)
    assert proj == {
        "bx2_mm": 12345.6,
        "by2_mm": 7890.1,
        "pixel_size_mm": 50.0,
        "width_px": 637,
        "height_px": 717,
    }
    # Guard against accidental key additions / drops.
    assert len(proj) == 5


def test_extract_projection_none_returns_none():
    """Sessions may be picked before MapData is fetched. Don't crash."""
    assert extract_projection(None) is None
