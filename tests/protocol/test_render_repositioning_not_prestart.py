"""Render branch: current_activity==REPOSITIONING must skip the idle pre-start preview.

During the REPOSITIONING window (~42s from undock until the op echo), the session
has not started yet (mow_session=BETWEEN_SESSIONS, no s2p56 active yet), but the
mower has left the dock. The render must NOT show the striped pre-start preview —
it should show the plain dark-green base (trail render path).

This test verifies that passing current_activity=REPOSITIONING via the 'state'
object causes render_main_view to skip the stripe branch even when
mow_session=BETWEEN_SESSIONS.
"""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import (
    _DEFAULT_PALETTE,
    render_main_view,
)
from custom_components.dreame_a2_mower.mower.state import ActionMode, MowerState
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    MowSession,
)


def _tiny_map() -> MapData:
    """10m × 10m map with one mowing zone."""
    return MapData(
        md5="test-repositioning-render",
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


def _count_light_green(png_bytes: bytes) -> int:
    """Count pixels matching light_green in the image."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    return sum(1 for p in img.getdata() if p == light_green)


def test_repositioning_skips_prestart_stripe_preview():
    """REPOSITIONING + ALL_AREAS + BETWEEN_SESSIONS must NOT show stripes.

    The stripe preview has both dark-green AND light-green bands. When
    REPOSITIONING, we expect the dark-green base (trail path) with NO
    light-green stripe fill.

    This test confirms that render_main_view detects REPOSITIONING and takes
    the trail path (dark-green base, no stripe overlay).
    """
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    # Inject current_activity=REPOSITIONING into a MowerState-like object
    # The render checks state.action_mode and the condition we add:
    # current_activity == REPOSITIONING → skip pre-start.
    # We use a simple object that has the right attributes.

    class _StateWithRepositioning:
        action_mode = ActionMode.ALL_AREAS
        last_all_area_mow_direction_deg = {}
        settings_mowing_direction_mode = None
        # The key attribute: current_activity signals REPOSITIONING
        current_activity = CurrentActivity.REPOSITIONING

    png = render_main_view(
        _tiny_map(),
        state=_StateWithRepositioning(),
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )

    # In the stripe preview, light_green is a significant fill color.
    # In the plain dark-green trail-path render, light_green should NOT appear
    # (no mow trail, no stripe overlay).
    light_green_count = _count_light_green(png)
    total_px = 200 * 200
    assert light_green_count < total_px * 0.01, (
        f"REPOSITIONING must skip stripe preview — found {light_green_count} "
        f"light_green pixels ({100 * light_green_count / total_px:.1f}%); "
        "expected < 1% (only background noise, not a stripe fill)"
    )

    # Confirm dark_green IS present (trail render path → dark-green base)
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    dark_green = _DEFAULT_PALETTE["dark_green"]
    dark_count = sum(1 for p in img.getdata() if p == dark_green)
    assert dark_count > total_px * 0.5, (
        f"REPOSITIONING should use dark-green trail-mode base; "
        f"got {dark_count} / {total_px} dark_green pixels"
    )


def test_idle_all_areas_still_shows_stripes_when_not_repositioning():
    """Sanity: IDLE (not REPOSITIONING) + ALL_AREAS + BETWEEN_SESSIONS → stripe preview.

    Ensures the REPOSITIONING guard doesn't accidentally suppress stripes for
    the normal idle case.
    """

    class _IdleState:
        action_mode = ActionMode.ALL_AREAS
        last_all_area_mow_direction_deg = {}
        settings_mowing_direction_mode = None
        current_activity = CurrentActivity.IDLE

    png = render_main_view(
        _tiny_map(),
        state=_IdleState(),
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    light_green_count = _count_light_green(png)
    total_px = 200 * 200
    # IDLE + ALL_AREAS stripe preview → must have significant light_green fill
    assert light_green_count > total_px * 0.1, (
        f"IDLE + ALL_AREAS should show stripe preview with light_green; "
        f"got only {light_green_count} pixels"
    )
