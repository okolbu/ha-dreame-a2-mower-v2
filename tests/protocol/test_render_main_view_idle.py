"""render_main_view: idle pre-start preview branches by action_mode."""
from __future__ import annotations

import io

from PIL import Image

from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
from custom_components.dreame_a2_mower.map_render import (
    _DEFAULT_PALETTE,
    render_main_view,
)
from custom_components.dreame_a2_mower.mower.state import ActionMode, MowerState
from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession


def _tiny_map() -> MapData:
    """10m × 10m map with one mowing zone (zone_id=1 → zone_fills[0])."""
    return MapData(
        md5="test-idle-dispatch",
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


def _pixels(png_bytes: bytes) -> set:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


def test_idle_all_areas_shows_stripes():
    """Idle + ALL_AREAS → stripe overlay with both dark+light bands."""
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    px = _pixels(png)
    dark_green = _DEFAULT_PALETTE["dark_green"]
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    assert dark_green in px, f"Expected dark_green {dark_green!r} in stripe preview"
    assert light_green in px, f"Expected light_green {light_green!r} in stripe preview"


def test_idle_zone_shows_stripes():
    """Idle + ZONE → same stripe overlay as ALL_AREAS."""
    state = MowerState(action_mode=ActionMode.ZONE)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    px = _pixels(png)
    dark_green = _DEFAULT_PALETTE["dark_green"]
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    assert dark_green in px, f"Expected dark_green in ZONE stripe preview"
    assert light_green in px, f"Expected light_green in ZONE stripe preview"


def test_idle_edge_all_light_green():
    """Idle + EDGE → all-light-green base, minimal dark-green."""
    state = MowerState(action_mode=ActionMode.EDGE)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    px = _pixels(png)
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    assert light_green in px, f"Expected light_green {light_green!r} in edge preview"
    # EDGE mode → no stripe overlay → dark_green should appear at most as
    # zone-outline pixels (outline stroke only, not a bulk fill).
    # 200×200 canvas = 40 000 pixels; outline pixels < 5% = 2 000 is conservative.
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    dark_count = sum(
        1 for p in img.getdata() if p == _DEFAULT_PALETTE["dark_green"]
    )
    total_px = img.width * img.height
    assert dark_count < total_px * 0.05, (
        f"edge-mode preview should have minimal dark-green (outline only); "
        f"got {dark_count} / {total_px} ({100 * dark_count / total_px:.1f}%)"
    )


def test_idle_spot_all_light_green():
    """Idle + SPOT → same all-light-green base as EDGE."""
    state = MowerState(action_mode=ActionMode.SPOT)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    px = _pixels(png)
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    assert light_green in px, f"Expected light_green in SPOT preview"


def test_in_session_uses_trail_render():
    """Active mow → trail render (dark-green base, no stripe overlay forced)."""
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.IN_SESSION,
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    px = _pixels(png)
    # Active session → existing trail render (lawn_mode=dark → dark_green base).
    assert _DEFAULT_PALETTE["dark_green"] in px, (
        "IN_SESSION should use trail render (dark_green base)"
    )


def test_legacy_no_state_uses_trail_render():
    """Pre-T17 callers (no state/mow_session kwargs) get trail render unchanged."""
    png = render_main_view(
        _tiny_map(),
        legs=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    # Should not crash; produces some output.
    assert len(png) > 100, "Legacy call should produce non-empty PNG"
