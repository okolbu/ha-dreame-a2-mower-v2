"""Tests for live_map/trail.py::render_trail_overlay.

Covers:
- Empty legs → empty list
- Single leg with 3 points → 1 leg-of-pixel-coords with 3 entries
- Two legs → 2 leg-paths
- Single-point leg → included as-is (1 pixel-coord entry)
- Coord-transform sanity: (x_m=0, y_m=0) maps to (bx2/grid, by2/grid)
- Negative x_m (mower moved in -X direction) shifts pixel right
"""
from __future__ import annotations

import sys
import pathlib

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from custom_components.dreame_a2_mower.live_map.trail import render_trail_overlay


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

# Bounding-box values matching _MINIMAL_MAP in test_map_decoder.py
# (bx1=-10920, bx2=20890, by1=-14080, by2=20961, pixel_size_mm=50)
_BX2 = 20890.0
_BY2 = 20961.0
_GRID = 50.0


# ---------------------------------------------------------------------------
# Empty / trivial cases
# ---------------------------------------------------------------------------


def test_render_trail_overlay_empty_legs_returns_empty():
    """Empty legs iterable → empty list."""
    result = render_trail_overlay([], _BX2, _BY2, _GRID)
    assert result == []


def test_render_trail_overlay_single_empty_leg():
    """A leg with zero points is passed through as an empty pixel-coord list."""
    result = render_trail_overlay([[]], _BX2, _BY2, _GRID)
    assert result == [[]]


# ---------------------------------------------------------------------------
# Point-count preservation
# ---------------------------------------------------------------------------


def test_render_trail_overlay_single_leg_three_points():
    """Single leg with 3 points → list of 1 leg containing 3 pixel-coord tuples."""
    legs = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]]
    result = render_trail_overlay(legs, _BX2, _BY2, _GRID)
    assert len(result) == 1, "Expected 1 leg"
    assert len(result[0]) == 3, "Expected 3 pixel-coord entries in the leg"


def test_render_trail_overlay_two_legs():
    """Two legs → two pixel-coord leg-paths (pen-up gap preserved)."""
    legs = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)],
    ]
    result = render_trail_overlay(legs, _BX2, _BY2, _GRID)
    assert len(result) == 2, "Expected 2 leg-paths"
    assert len(result[0]) == 2, "First leg should have 2 points"
    assert len(result[1]) == 3, "Second leg should have 3 points"


# ---------------------------------------------------------------------------
# Coordinate-transform sanity checks
# ---------------------------------------------------------------------------


def test_coord_transform_origin():
    """(x_m=0, y_m=0) maps to pixel (bx2/grid, by2/grid).

    cloud_x = 0 * 1000 = 0
    cloud_y = 0 * 1000 = 0
    px = (bx2 - 0) / grid = bx2 / grid
    py = (by2 - 0) / grid = by2 / grid
    """
    legs = [[(0.0, 0.0)]]
    result = render_trail_overlay(legs, _BX2, _BY2, _GRID)
    assert len(result) == 1
    assert len(result[0]) == 1
    px, py = result[0][0]
    assert abs(px - _BX2 / _GRID) < 1e-6, f"Expected px={_BX2/_GRID:.4f}, got {px:.4f}"
    assert abs(py - _BY2 / _GRID) < 1e-6, f"Expected py={_BY2/_GRID:.4f}, got {py:.4f}"


def test_coord_transform_positive_x_moves_pixel_left():
    """Positive x_m (mower moved away from dock in +X) shifts pixel left.

    cloud_x = x_m * 1000 > 0
    px = (bx2 - cloud_x) / grid  →  smaller than at origin.
    """
    legs_origin = [[(0.0, 0.0)]]
    legs_right = [[(1.0, 0.0)]]  # 1 m in +X

    px_origin = render_trail_overlay(legs_origin, _BX2, _BY2, _GRID)[0][0][0]
    px_right = render_trail_overlay(legs_right, _BX2, _BY2, _GRID)[0][0][0]

    assert px_right < px_origin, (
        "Positive x_m should reduce px (cloud frame is flipped to pixel frame)"
    )


def test_coord_transform_unit_step():
    """A 1-metre step in +X corresponds to exactly 1000/grid pixels shift."""
    bx2, by2, grid = 10000.0, 10000.0, 50.0
    legs = [[(0.0, 0.0), (1.0, 0.0)]]  # 1 m step in X
    result = render_trail_overlay(legs, bx2, by2, grid)
    px0, _ = result[0][0]
    px1, _ = result[0][1]
    # Δpx = (bx2 - 1000) / grid - (bx2 - 0) / grid = -1000/grid
    expected_delta = -1000.0 / grid
    actual_delta = px1 - px0
    assert abs(actual_delta - expected_delta) < 1e-9, (
        f"Expected pixel delta {expected_delta}, got {actual_delta}"
    )


def test_coord_transform_returns_floats():
    """All pixel coords are floats (not ints)."""
    legs = [[(1.5, 2.3)]]
    result = render_trail_overlay(legs, _BX2, _BY2, _GRID)
    px, py = result[0][0]
    assert isinstance(px, float)
    assert isinstance(py, float)
