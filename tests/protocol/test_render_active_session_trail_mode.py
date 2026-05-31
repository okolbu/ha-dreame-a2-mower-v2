"""Render: any active task-start op forces trail mode (not pre-start stripe).

Verifies that render_main_view skips the idle pre-start preview branch
for ALL task-start ops (100-103, 108, 109), not just op=109.

Before the fix, only op=109 had the `_is_active_non_mow_session` bypass.
Mow ops (100-103) rely on mow_session=IN_SESSION to reach the trail path;
patrol (108) has no such mechanism so it could hit the stripe preview.

After the fix, any `last_task_op in TASK_START_OPS` (100-103, 108, 109)
forces trail mode regardless of mow_session.
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
from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession


def _tiny_map() -> MapData:
    """100×100 px, 5m×5m map with one mowing zone."""
    return MapData(
        md5="test-active-session",
        width_px=100,
        height_px=100,
        pixel_size_mm=50.0,
        bx1=0.0,
        by1=0.0,
        bx2=5000.0,
        by2=5000.0,
        cloud_x_reflect=5000.0,
        cloud_y_reflect=5000.0,
        rotation_deg=0.0,
        boundary_polygon=(
            (0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0), (0.0, 5000.0),
        ),
        mowing_zones=(
            MowingZone(
                zone_id=1,
                name="lawn",
                path=(
                    (0.0, 0.0), (5000.0, 0.0), (5000.0, 5000.0), (0.0, 5000.0),
                ),
                area_m2=25.0,
            ),
        ),
        exclusion_zones=(),
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        dock_xy=None,
        total_area_m2=25.0,
        nav_paths=(),
    )


def _pixel_set(png_bytes: bytes) -> set:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return set(img.getdata())


def _has_stripe_pattern(png_bytes: bytes) -> bool:
    """Detect whether the image has the idle stripe preview pattern.

    The stripe preview has BOTH dark_green AND a lighter zone_fill green
    (the stripe bands). The trail render only has dark_green.
    """
    px = _pixel_set(png_bytes)
    dark_green = _DEFAULT_PALETTE["dark_green"]
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    return dark_green in px and light_green in px


def _has_dark_base_only(png_bytes: bytes) -> bool:
    """True if the image has the dark trail base but NOT the light-green stripe fill.

    Trail render = dark base + possible grey traversal lines.
    Stripe preview = dark base + light green fills.
    """
    px = _pixel_set(png_bytes)
    dark_green = _DEFAULT_PALETTE["dark_green"]
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    return dark_green in px and light_green not in px


# ---------------------------------------------------------------------------
# Core: active task-start ops skip the idle pre-start branch
# ---------------------------------------------------------------------------


def test_op100_between_sessions_but_active_renders_trail():
    """op=100 with mow_session=IN_SESSION (standard mow): must render trail.

    This is the existing behavior that must be unchanged.
    """
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.IN_SESSION,
        last_task_op=100,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    dark_green = _DEFAULT_PALETTE["dark_green"]
    assert dark_green in _pixel_set(png), (
        "op=100 IN_SESSION must render dark-green base (trail path)"
    )


def test_op108_between_sessions_renders_trail_not_stripes():
    """op=108 (patrol): an ACTIVE patrol must render trail, not stripes.

    Patrol never enters mow_session=IN_SESSION. The active-session signal is
    ``live_map_active=True`` (the live_map session started when the patrol's
    s2p1=1 made task_state_code active). The render keys on that, NOT on the
    persisted last_task_op — so a stale 108 restored after a reboot (with
    live_map NOT active) correctly shows the idle preview instead.
    """
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        last_task_op=108,
        live_map_active=True,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    assert not _has_stripe_pattern(png), (
        "op=108 (patrol) with active session must NOT render idle stripe preview."
    )
    dark_green = _DEFAULT_PALETTE["dark_green"]
    assert dark_green in _pixel_set(png), (
        "op=108 active session must render dark-green base (trail path)"
    )


def test_op109_between_sessions_renders_trail_not_stripes():
    """op=109 (cruise-to-point): an ACTIVE cruise renders trail, not stripes.

    Keyed on live_map_active=True (the genuine active-session signal), not on
    the persisted last_task_op.
    """
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        last_task_op=109,
        live_map_active=True,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    assert not _has_stripe_pattern(png), (
        "op=109 (cruise) active session must NOT render idle stripe preview"
    )


def test_all_mow_ops_in_session_render_trail():
    """All mow ops (100-103) with IN_SESSION: trail render (unchanged from before)."""
    from custom_components.dreame_a2_mower.protocol.mode_enum import MOW_MODE_CODES

    for op in sorted(MOW_MODE_CODES):
        state = MowerState(action_mode=ActionMode.ALL_AREAS)
        png = render_main_view(
            _tiny_map(),
            state=state,
            map_id=0,
            mow_session=MowSession.IN_SESSION,
            last_task_op=op,
            mower_position_m=None,
            mower_heading_deg=None,
        )
        dark_green = _DEFAULT_PALETTE["dark_green"]
        assert dark_green in _pixel_set(png), (
            f"op={op} IN_SESSION must render dark-green base (trail path)"
        )


# ---------------------------------------------------------------------------
# Idle pre-start preview still fires when genuinely idle
# ---------------------------------------------------------------------------


def test_idle_with_none_last_task_op_still_shows_stripe_preview():
    """Genuine idle (last_task_op=None, mow_session=BETWEEN_SESSIONS): stripes."""
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        last_task_op=None,
        mower_position_m=None,
        mower_heading_deg=None,
    )
    assert _has_stripe_pattern(png), (
        "Genuine idle (last_task_op=None) must still render the stripe preview"
    )


def test_idle_with_old_mow_op_last_task_op_shows_stripe_preview():
    """After a session ends, last_task_op retains the finished op (e.g. 100).

    But mow_session=BETWEEN_SESSIONS (session is over). Since mow ops (100-103)
    require IN_SESSION to use trail mode, BETWEEN_SESSIONS + mow op still shows
    the idle stripe preview — the user is between mows.

    NOTE: This only applies to mow ops (100-103). Non-mow ops (108, 109) ALWAYS
    force trail mode regardless of mow_session, because they never enter IN_SESSION.
    The idle-stripe path for mow ops relies on mow_session=IN_SESSION (which the
    echo sets), so between sessions the stripe still shows correctly.
    """
    state = MowerState(action_mode=ActionMode.ALL_AREAS)
    png = render_main_view(
        _tiny_map(),
        state=state,
        map_id=0,
        mow_session=MowSession.BETWEEN_SESSIONS,
        last_task_op=100,  # previous mow finished, now idle
        mower_position_m=None,
        mower_heading_deg=None,
    )
    assert _has_stripe_pattern(png), (
        "After a mow ends (BETWEEN_SESSIONS + last_task_op=100), must show idle "
        "stripe preview — the mow is over, not currently active."
    )
