# tests/test_extract_projection.py
from custom_components.dreame_a2_mower.map_render import extract_projection
from types import SimpleNamespace


def test_projection_includes_dock_when_available():
    md = SimpleNamespace(
        bx1=0, by1=0, bx2=10000, by2=10000,
        pixel_size_mm=50, width_px=200, height_px=200,
        dock_xy=(5000, 5000),
    )
    out = extract_projection(md)
    assert out["dock_xy_mm"] == [5000, 5000]


def test_projection_omits_dock_when_none():
    md = SimpleNamespace(
        bx1=0, by1=0, bx2=10000, by2=10000,
        pixel_size_mm=50, width_px=200, height_px=200,
        dock_xy=None,
    )
    out = extract_projection(md)
    assert "dock_xy_mm" not in out
