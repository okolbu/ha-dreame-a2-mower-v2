"""Regression: mower icon is drawn at last-known position even between sessions.

TDD test written BEFORE the fix.  The test is RED (fails) when the pre-start
preview renderers (_render_pre_start_with_stripes / _render_pre_start_edge /
_render_pre_start_spot) return without compositing the mower icon.  It turns
GREEN once render_main_view composites the icon on top of every idle-preview
branch when mower_position_m is supplied.

Covers:
- ALL_AREAS idle preview + known position → icon pixels present
- ZONE idle preview + known position → icon pixels present
- EDGE idle preview + known position → icon pixels present
- SPOT idle preview + known position → icon pixels present
- IN_SESSION with known position → icon pixels present (existing trail path, guard only)
- position=None → no icon pixels at centre (no crash)
"""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import render_main_view
from custom_components.dreame_a2_mower.mower.state import ActionMode, MowerState
from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tiny_map() -> MapData:
    """10 m × 10 m map (200 × 200 px @ 50 mm/px) with one mowing zone."""
    return MapData(
        md5="test-icon-between-sessions",
        width_px=200,
        height_px=200,
        pixel_size_mm=50.0,
        bx1=0.0,
        by1=0.0,
        bx2=10000.0,
        by2=10000.0,
        cloud_x_reflect=10000.0,
        cloud_y_reflect=10000.0,
        rotation_deg=0.0,
        boundary_polygon=(
            (0.0, 0.0),
            (10000.0, 0.0),
            (10000.0, 10000.0),
            (0.0, 10000.0),
        ),
        mowing_zones=(
            MowingZone(
                zone_id=1,
                name="lawn",
                path=(
                    (0.0, 0.0),
                    (10000.0, 0.0),
                    (10000.0, 10000.0),
                    (0.0, 10000.0),
                ),
                area_m2=100.0,
            ),
        ),
        exclusion_zones=(),
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        dock_xy=None,
        total_area_m2=100.0,
        nav_paths=(),
    )


# Place the mower at the centre of the map: cloud-frame (5 m, 5 m).
# bx2=10000 mm, pixel_size_mm=50 → px = (10000 - 5000)/50 = 100
# by2=10000 mm → py = (10000 - 5000)/50 = 100  (PRE-FLIP)
# After FLIP_TOP_BOTTOM py becomes height - 1 - 100 = 99.
# The icon is 32 × 32 px, so the centre region (~85..115, ~85..115) should
# contain icon pixels.
_MOWER_POS_M = (5.0, 5.0)
# Icon is grey — these are NOT lawn-green colours, so their presence
# indicates the icon was drawn.
_GREY_RANGE = (30, 200)  # approximate R/G/B band for grey icon pixels


def _open_rgba(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _has_icon_pixels(png: bytes, *, x_centre: int = 100, y_centre: int = 99,
                     radius: int = 20) -> bool:
    """Return True if the icon-sized crop around (x_centre, y_centre) contains
    grey pixels that are NOT the lawn-green family.

    The mower icon is a product photograph rendered in grey tones; the lawn is
    drawn in greens (R<180, G>150, B<150 approximately).  Any pixel in the crop
    that is sufficiently grey and non-green counts as icon evidence.
    """
    img = _open_rgba(png)
    x0 = max(0, x_centre - radius)
    x1 = min(img.width, x_centre + radius)
    y0 = max(0, y_centre - radius)
    y1 = min(img.height, y_centre + radius)
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b, a = img.getpixel((x, y))
            if a < 30:
                continue  # transparent pixel — not the icon
            # Grey check: all channels roughly equal AND not lawn-green
            # (lawn-green ~(178,223,138,255) has G >> B; grey has equal channels)
            channel_spread = max(r, g, b) - min(r, g, b)
            if channel_spread < 40 and _GREY_RANGE[0] <= r <= _GREY_RANGE[1]:
                return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_idle_all_areas_with_position_shows_mower_icon():
    """Idle ALL_AREAS + mower position → icon must appear in the output PNG.

    This is a RED test when the pre-start preview renderer returns without
    compositing the mower icon.
    """
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        mower_position_m=_MOWER_POS_M,
        mower_heading_deg=None,
    )
    assert _has_icon_pixels(png), (
        "Idle ALL_AREAS preview with mower_position_m should contain mower icon "
        "grey pixels near the map centre, but none were found.  The pre-start "
        "renderer is not compositing the mower icon."
    )


def test_idle_zone_with_position_shows_mower_icon():
    """Idle ZONE + mower position → icon present."""
    state = MowerState(action_mode=ActionMode.ZONE)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        mower_position_m=_MOWER_POS_M,
        mower_heading_deg=None,
    )
    assert _has_icon_pixels(png), (
        "Idle ZONE preview with mower_position_m should show mower icon."
    )


def test_idle_edge_with_position_shows_mower_icon():
    """Idle EDGE + mower position → icon present."""
    state = MowerState(action_mode=ActionMode.EDGE)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        mower_position_m=_MOWER_POS_M,
        mower_heading_deg=None,
    )
    assert _has_icon_pixels(png), (
        "Idle EDGE preview with mower_position_m should show mower icon."
    )


def test_idle_spot_with_position_shows_mower_icon():
    """Idle SPOT + mower position → icon present."""
    state = MowerState(action_mode=ActionMode.SPOT)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        mower_position_m=_MOWER_POS_M,
        mower_heading_deg=None,
    )
    assert _has_icon_pixels(png), (
        "Idle SPOT preview with mower_position_m should show mower icon."
    )


def test_in_session_with_position_shows_mower_icon():
    """Active session + mower position → icon present (existing trail path, guard)."""
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.IN_SESSION,
        mower_position_m=_MOWER_POS_M,
        mower_heading_deg=None,
        legs_timeline=[],
    )
    assert _has_icon_pixels(png), (
        "Active session with mower_position_m should show mower icon (trail path)."
    )


def test_idle_no_position_does_not_crash():
    """Idle with position=None → no crash, returns valid PNG."""
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    assert len(png) > 100, "Should produce a valid PNG even without position"
