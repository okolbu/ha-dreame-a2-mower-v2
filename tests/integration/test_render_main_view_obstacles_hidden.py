"""Tests for Fix 3: live map hides last-session obstacles during IN_SESSION.

_render_main_view must pass obstacles=None to render_main_view when
MowSession.IN_SESSION, and pass the cached obstacle list otherwise.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_map_data():
    from custom_components.dreame_a2_mower.map_decoder import MapData

    return MapData(
        md5="test",
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
            (0.0, 0.0),
            (5000.0, 0.0),
            (5000.0, 5000.0),
            (0.0, 5000.0),
        ),
        mowing_zones=(),
        exclusion_zones=(),
        spot_zones=(),
        contour_paths=(),
        available_contour_ids=(),
        maintenance_points=(),
        dock_xy=None,
        total_area_m2=10.0,
        nav_paths=(),
    )


# ---------------------------------------------------------------------------
# Source-level check: ensure the fix is present in _rendering.py
# ---------------------------------------------------------------------------

def test_render_main_view_hides_obstacles_in_session_in_source():
    """Verify the source of _render_main_view uses IN_SESSION to gate obstacles."""
    import re
    from pathlib import Path

    src = Path(
        "custom_components/dreame_a2_mower/coordinator/_rendering.py"
    ).read_text()

    # The fix must compare mow_session == _MowSession.IN_SESSION (or similar)
    # and supply obstacle_polygons_m = None in that branch.
    assert "IN_SESSION" in src, (
        "_rendering.py must reference IN_SESSION to gate obstacle display"
    )
    assert "obstacle_polygons_m = None" in src, (
        "_render_main_view must set obstacle_polygons_m = None during IN_SESSION"
    )


# ---------------------------------------------------------------------------
# Behavioural test: _render_main_view passes obstacles=None when IN_SESSION
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_render_main_view_passes_none_obstacles_during_in_session():
    """When MowSession.IN_SESSION, _render_main_view passes None obstacles."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._active_map_id = 0
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {0: _make_map_data()}
    coord._main_view_png = None
    coord._active_map_base_png = None
    coord._active_map_base_md5 = None
    coord._last_session_obstacles_by_map = {0: [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]]}

    # Live map is active during IN_SESSION.
    live_map = MagicMock()
    live_map.is_active.return_value = True
    live_map.track = []
    coord.live_map = live_map

    # State machine returns IN_SESSION snapshot.
    snap = MagicMock()
    snap.mow_session = MowSession.IN_SESSION
    snap.position_x_m = None
    snap.position_y_m = None
    sm = MagicMock()
    sm.snapshot.return_value = snap
    coord.state_machine = sm

    coord.data = MagicMock()
    coord.data.position_heading_deg = None
    coord.data.trail_render_width = 3
    coord.data.action_mode = None

    hass = MagicMock()
    coord.hass = hass

    # Capture what obstacle_polygons_m value is passed to render_main_view.
    captured_obstacles: list = []

    def fake_render(map_data, *, mower_position_m, mower_heading_deg,
                    obstacle_polygons_m, state, map_id, mow_session, trail_width_px,
                    legs=None, legs_timeline=None, mowing_legs=None,
                    traversal_legs=None):
        captured_obstacles.append(obstacle_polygons_m)
        return b"\x89PNG"

    # async_add_executor_job calls its first arg with the rest; partial wraps it.
    async def fake_executor(func_or_partial, *args, **kwargs):
        # functools.partial wraps the real render call; call it.
        import functools
        if isinstance(func_or_partial, functools.partial):
            return func_or_partial()
        return func_or_partial(*args, **kwargs)

    hass.async_add_executor_job.side_effect = fake_executor

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_main_view",
        side_effect=fake_render,
    ):
        coord._render_active_map_base = AsyncMock(return_value=None)
        await coord._render_main_view()

    assert len(captured_obstacles) == 1, "render_main_view should be called once"
    assert captured_obstacles[0] is None, (
        f"During IN_SESSION, obstacle_polygons_m must be None; "
        f"got {captured_obstacles[0]!r}"
    )


@pytest.mark.asyncio
async def test_render_main_view_passes_obstacles_between_sessions():
    """Between sessions (BETWEEN_SESSIONS), obstacles are loaded and passed."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._active_map_id = 0
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {0: _make_map_data()}
    coord._main_view_png = None
    coord._active_map_base_png = None
    coord._active_map_base_md5 = None

    OBSTACLE_POLY = [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]]
    # Cache pre-populated so _load_last_session_obstacles returns it.
    coord._last_session_obstacles_by_map = {0: OBSTACLE_POLY}

    live_map = MagicMock()
    live_map.is_active.return_value = False
    live_map.track = []
    coord.live_map = live_map

    snap = MagicMock()
    snap.mow_session = MowSession.BETWEEN_SESSIONS
    snap.position_x_m = None
    snap.position_y_m = None
    sm = MagicMock()
    sm.snapshot.return_value = snap
    coord.state_machine = sm

    coord.data = MagicMock()
    coord.data.position_heading_deg = None
    coord.data.trail_render_width = 3
    coord.data.action_mode = None

    hass = MagicMock()
    coord.hass = hass

    captured_obstacles: list = []

    def fake_render(map_data, *, mower_position_m, mower_heading_deg,
                    obstacle_polygons_m, state, map_id, mow_session, trail_width_px,
                    legs=None, legs_timeline=None, mowing_legs=None,
                    traversal_legs=None):
        captured_obstacles.append(obstacle_polygons_m)
        return b"\x89PNG"

    async def fake_executor(func_or_partial, *args, **kwargs):
        import functools
        if isinstance(func_or_partial, functools.partial):
            return func_or_partial()
        return func_or_partial(*args, **kwargs)

    hass.async_add_executor_job.side_effect = fake_executor

    with patch(
        "custom_components.dreame_a2_mower.map_render.render_main_view",
        side_effect=fake_render,
    ):
        coord._render_active_map_base = AsyncMock(return_value=None)
        await coord._render_main_view()

    assert len(captured_obstacles) == 1
    # Between sessions the last-session obstacles should be passed through
    # (they may be non-None when the cache is populated).
    # The key assertion: it's not unconditionally None.
    assert captured_obstacles[0] is not None, (
        f"Between sessions, obstacle_polygons_m must not be None when cache is "
        f"populated; got {captured_obstacles[0]!r}"
    )
    assert captured_obstacles[0] == OBSTACLE_POLY
