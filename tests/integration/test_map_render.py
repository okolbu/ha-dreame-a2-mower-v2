"""Smoke tests for map_render.render_base_map.

Uses the same synthetic MapData payload as test_map_decoder.py (the
_MINIMAL_MAP fixture) to exercise the renderer without a live mower.

Verifies:
- Result is non-empty bytes.
- Result starts with PNG signature ``\\x89PNG\\r\\n\\x1a\\n``.
- Decoded image has the expected (width_px, height_px) dimensions.
- The function is tolerant of edge cases (no zones, no dock).
"""
from __future__ import annotations

import io
import sys
import pathlib

# ---------------------------------------------------------------------------
# Path wiring — same as test_map_decoder.py.
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Re-use the synthetic fixture from test_map_decoder.
# ---------------------------------------------------------------------------
from tests.integration.test_map_decoder import _MINIMAL_MAP  # noqa: E402

from custom_components.dreame_a2_mower.map_decoder import parse_cloud_map  # noqa: E402
from custom_components.dreame_a2_mower.map_render import render_base_map, render_with_trail  # noqa: E402

# PNG magic bytes.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _map_data():
    """Return a freshly parsed MapData from _MINIMAL_MAP."""
    md = parse_cloud_map(_MINIMAL_MAP)
    assert md is not None, "parse_cloud_map returned None for _MINIMAL_MAP"
    return md


class TestRenderBaseMap:
    """Core render_base_map behaviour."""

    def test_returns_bytes(self):
        """render_base_map returns a bytes object."""
        result = render_base_map(_map_data())
        assert isinstance(result, bytes)

    def test_result_non_empty(self):
        """Rendered PNG is not empty."""
        result = render_base_map(_map_data())
        assert len(result) > 0

    def test_png_signature(self):
        """Result starts with the 8-byte PNG magic signature."""
        result = render_base_map(_map_data())
        assert result[:8] == _PNG_SIGNATURE, (
            f"Expected PNG signature {_PNG_SIGNATURE!r}, got {result[:8]!r}"
        )

    def test_image_dimensions(self):
        """Decoded image has width_px × height_px dimensions."""
        from PIL import Image

        md = _map_data()
        result = render_base_map(md)
        img = Image.open(io.BytesIO(result))
        assert img.width == md.width_px, (
            f"Expected width {md.width_px}, got {img.width}"
        )
        assert img.height == md.height_px, (
            f"Expected height {md.height_px}, got {img.height}"
        )

    def test_image_mode_rgba(self):
        """Image is RGBA (transparent background)."""
        from PIL import Image

        result = render_base_map(_map_data())
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGBA", f"Expected RGBA mode, got {img.mode}"

    def test_custom_palette_accepted(self):
        """Passing a partial palette override doesn't crash."""
        md = _map_data()
        result = render_base_map(
            md,
            palette={
                "lawn_fill": (0, 200, 0, 255),
                "dock_fill": (255, 0, 0, 255),
            },
        )
        assert result[:8] == _PNG_SIGNATURE

    def test_no_mowing_zones(self):
        """Map with zero mowing zones still renders successfully."""
        import copy

        payload = copy.deepcopy(_MINIMAL_MAP)
        payload["mowingAreas"] = {"value": []}
        md = parse_cloud_map(payload)
        assert md is not None
        result = render_base_map(md)
        assert result[:8] == _PNG_SIGNATURE

    def test_no_exclusion_zones(self):
        """Map with zero exclusion zones still renders successfully."""
        import copy

        payload = copy.deepcopy(_MINIMAL_MAP)
        payload["forbiddenAreas"] = {"value": []}
        md = parse_cloud_map(payload)
        assert md is not None
        result = render_base_map(md)
        assert result[:8] == _PNG_SIGNATURE

    def test_no_dock_xy(self):
        """dock_xy=None (degenerate bbox) skips dock icon without crash."""
        import copy

        from custom_components.dreame_a2_mower.map_decoder import (
            MapData,
            GRID_SIZE_MM,
        )

        md = _map_data()
        # Build a minimal MapData without dock.
        no_dock = MapData(
            md5=md.md5,
            width_px=md.width_px,
            height_px=md.height_px,
            pixel_size_mm=md.pixel_size_mm,
            bx1=md.bx1,
            by1=md.by1,
            bx2=md.bx2,
            by2=md.by2,
            cloud_x_reflect=md.cloud_x_reflect,
            cloud_y_reflect=md.cloud_y_reflect,
            rotation_deg=md.rotation_deg,
            boundary_polygon=md.boundary_polygon,
            mowing_zones=md.mowing_zones,
            exclusion_zones=md.exclusion_zones,
            contour_paths=md.contour_paths,
            maintenance_points=md.maintenance_points,
            dock_xy=None,  # <<< no dock
            total_area_m2=md.total_area_m2,
        )
        result = render_base_map(no_dock)
        assert result[:8] == _PNG_SIGNATURE

    def test_multiple_mowing_zones(self):
        """Multiple mowing zones are rendered (colour rotation doesn't crash)."""
        import copy

        payload = copy.deepcopy(_MINIMAL_MAP)
        # Add three more zones (zone_id 2, 3, 4) to exercise colour rotation.
        payload["mowingAreas"]["value"].extend([
            [2, {"path": [
                {"x": -4000, "y": -4000}, {"x": 0, "y": -4000},
                {"x": 0, "y": 0}, {"x": -4000, "y": 0},
            ], "name": "Back"}],
            [3, {"path": [
                {"x": 1000, "y": 1000}, {"x": 3000, "y": 1000},
                {"x": 3000, "y": 3000}, {"x": 1000, "y": 3000},
            ], "name": "Side"}],
            [4, {"path": [
                {"x": 5000, "y": 5000}, {"x": 7000, "y": 5000},
                {"x": 7000, "y": 7000}, {"x": 5000, "y": 7000},
            ], "name": "Corner"}],
        ])
        md = parse_cloud_map(payload)
        assert md is not None
        result = render_base_map(md)
        assert result[:8] == _PNG_SIGNATURE

    def test_result_is_deterministic(self):
        """Two calls with the same MapData produce identical bytes."""
        md = _map_data()
        r1 = render_base_map(md)
        r2 = render_base_map(md)
        assert r1 == r2


class TestRenderWithTrail:
    """Tests for render_with_trail — trail overlay composited on base map."""

    def test_empty_legs_returns_base_map(self):
        """render_with_trail with empty legs returns same bytes as render_base_map."""
        md = _map_data()
        base_png = render_base_map(md)
        trail_png = render_with_trail(md, [])
        assert trail_png == base_png, (
            "render_with_trail with no legs should equal render_base_map output"
        )

    def test_none_legs_returns_base_map(self):
        """render_with_trail with legs=None returns same bytes as render_base_map."""
        md = _map_data()
        base_png = render_base_map(md)
        trail_png = render_with_trail(md, None)
        assert trail_png == base_png

    def test_nonempty_legs_returns_png_bytes(self):
        """render_with_trail with a real leg returns non-empty PNG bytes."""
        md = _map_data()
        # Two-point leg somewhere on the map (cloud-frame coords → metres)
        # _MINIMAL_MAP bx2=20890, by2=20961 → origin at (20890/1000, 20961/1000) = 20.89 m, 20.961 m
        # Use a point near the map centre (~5 m, ~5 m in cloud metres)
        legs = [[(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]]
        result = render_with_trail(md, legs)
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:8] == _PNG_SIGNATURE

    def test_nonempty_legs_differs_from_base(self):
        """render_with_trail with a real leg produces different bytes than base map.

        The trail polyline changes at least one pixel, so the PNG should differ.
        """
        md = _map_data()
        base_png = render_base_map(md)
        legs = [[(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]]
        trail_png = render_with_trail(md, legs)
        assert trail_png != base_png, (
            "Trail-overlaid PNG should differ from base PNG (some pixels painted red)"
        )

    def test_result_is_valid_png(self):
        """render_with_trail result starts with the PNG signature."""
        md = _map_data()
        legs = [[(0.0, 0.0), (1.0, 0.0)]]
        result = render_with_trail(md, legs)
        assert result[:8] == _PNG_SIGNATURE

    def test_image_dimensions_unchanged(self):
        """Trail overlay does not change the image dimensions."""
        from PIL import Image

        md = _map_data()
        legs = [[(5.0, 5.0), (6.0, 5.0)]]
        result = render_with_trail(md, legs)
        img = Image.open(io.BytesIO(result))
        assert img.width == md.width_px
        assert img.height == md.height_px

    def test_single_point_leg_does_not_crash(self):
        """A single-point leg (no line segment) does not raise."""
        md = _map_data()
        legs = [[(5.0, 5.0)]]
        result = render_with_trail(md, legs)
        assert result[:8] == _PNG_SIGNATURE

    def test_multiple_legs_renders_all(self):
        """Multiple legs are all drawn (function iterates all legs)."""
        md = _map_data()
        legs = [
            [(0.0, 0.0), (1.0, 0.0)],
            [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)],
        ]
        result = render_with_trail(md, legs)
        assert result[:8] == _PNG_SIGNATURE


# ---------------------------------------------------------------------------
# v1.0.0a3 regression: exclusion zones + dock land on the same pixel as the
# lawn formula picks for the original cloud point.
# ---------------------------------------------------------------------------


def test_renderer_to_px_inverts_decoder_midline_reflection():
    """For any cloud point (X, Y), running it through the decoder's
    midline-reflection formula and then through `_renderer_to_px` must
    yield the same pixel `_cloud_to_px` would produce.  This is the
    invariant the v1.0.0a3 fix restored — pre-fix the lawn and overlays
    landed on different sides of the canvas."""
    from custom_components.dreame_a2_mower.map_render import (
        _cloud_to_px,
        _renderer_to_px,
    )

    bx1, by1 = -10920.0, -14079.0
    bx2, by2 = 20890.0, 20960.0
    grid = 50.0

    for cloud_x, cloud_y in [
        (0.0, 0.0),         # cloud origin (where dock sits)
        (5000.0, 7000.0),   # arbitrary inside-lawn point
        (-5000.0, -8000.0), # arbitrary point in negative quadrant
        (bx2, by2),         # corner: top-left in pixel mask
        (bx1, by1),         # corner: bottom-right in pixel mask
    ]:
        # Decoder reflects cloud → renderer mm.
        rx = (bx1 + bx2) - cloud_x
        ry = (by1 + by2) - cloud_y
        # Renderer should land on the same pixel as the lawn formula.
        cloud_pixel = _cloud_to_px(cloud_x, cloud_y, bx2, by2, grid)
        renderer_pixel = _renderer_to_px(rx, ry, bx1, by1, grid)
        assert renderer_pixel == cloud_pixel, (
            f"For cloud ({cloud_x}, {cloud_y}): "
            f"_cloud_to_px → {cloud_pixel}, "
            f"_renderer_to_px(reflected) → {renderer_pixel}"
        )
