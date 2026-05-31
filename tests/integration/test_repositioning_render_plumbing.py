"""TDD: Bug 1 — _render_main_view must pass current_activity from the state machine
into render_main_view so the REPOSITIONING stripe-skip actually fires.

ROOT CAUSE:
    _rendering.py:_render_main_view passes `state=self.data` (a MowerState object).
    MowerState has NO `current_activity` attribute — that lives on StateSnapshot
    (from the state machine). render_main_view reads `getattr(state, "current_activity",
    None)`, which returns None, so `_is_repositioning` is always False.

FIX:
    Pass current_activity from state_machine.snapshot() into render_main_view.

Tests:
1. When state_machine.snapshot().current_activity == REPOSITIONING,
   render_main_view is called with state.current_activity == REPOSITIONING.
2. When state_machine.snapshot().current_activity == IDLE,
   render_main_view is NOT called with REPOSITIONING.
3. The render trigger on s2p1→REPOSITIONING fires _render_main_view
   (coordinator-level: checks hass.async_create_task was called with the render).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coord_for_render_test(*, current_activity, mow_session=None):
    """Build a minimal coordinator stub with state_machine.snapshot() returning
    the given current_activity.  The _render_main_view is replaced with an
    AsyncMock that records what render_main_view was called with.
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.mower.state_snapshot import MowSession

    coord = object.__new__(DreameA2MowerCoordinator)

    # --- state ---
    coord.data = MowerState()  # no current_activity attribute
    coord._active_map_id = 1

    # --- live_map ---
    lm = MagicMock()
    lm.is_active.return_value = False
    lm.track = []
    coord.live_map = lm

    # --- cloud_state ---
    from custom_components.dreame_a2_mower.map_decoder import MapData, MowingZone
    map_data = MapData(
        md5="test-plumbing",
        width_px=50, height_px=50, pixel_size_mm=50.0,
        bx1=0.0, by1=0.0, bx2=2500.0, by2=2500.0,
        cloud_x_reflect=2500.0, cloud_y_reflect=2500.0,
        rotation_deg=0.0,
        boundary_polygon=((0.0, 0.0), (2500.0, 0.0), (2500.0, 2500.0), (0.0, 2500.0)),
        mowing_zones=(MowingZone(zone_id=1, name="lawn",
            path=((0.0, 0.0), (2500.0, 0.0), (2500.0, 2500.0), (0.0, 2500.0)),
            area_m2=6.25),),
        exclusion_zones=(), spot_zones=(), contour_paths=(),
        available_contour_ids=(), maintenance_points=(), dock_xy=None,
        total_area_m2=6.25, nav_paths=(),
    )
    cs = MagicMock()
    cs.maps_by_id = {1: map_data}
    coord.cloud_state = cs

    # --- state_machine ---
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession as _MS,
    )
    snap = MagicMock()
    snap.current_activity = current_activity
    snap.mow_session = mow_session if mow_session is not None else _MS.BETWEEN_SESSIONS
    snap.last_task_op = None
    sm = MagicMock()
    sm.snapshot.return_value = snap
    coord.state_machine = sm

    # --- hass ---
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(return_value=b"fake-png")
    coord.hass = hass

    # --- misc rendering state ---
    coord._main_view_png = None
    coord._active_map_base_png = None
    coord._active_map_base_md5 = None
    coord._last_session_obstacles_by_map = {}
    coord.session_archive = MagicMock()
    coord.session_archive._index_loaded = False

    return coord


# ---------------------------------------------------------------------------
# Test 1: REPOSITIONING state machine activity is forwarded to render_main_view
# ---------------------------------------------------------------------------

async def test_render_main_view_forwards_repositioning_activity():
    """_render_main_view must pass current_activity=REPOSITIONING to render_main_view
    so the REPOSITIONING stripe-skip actually fires.

    The bug: self.data (MowerState) has no current_activity attribute.
    The fix: pass current_activity from state_machine.snapshot() explicitly.
    """
    from custom_components.dreame_a2_mower.mower.state_snapshot import CurrentActivity
    coord = _make_coord_for_render_test(current_activity=CurrentActivity.REPOSITIONING)

    captured_kwargs = {}

    async def fake_executor(fn, *args, **kwargs):
        # fn is functools.partial(render_main_view, map_data, ...)
        # Inspect the partial's keywords
        import functools
        if isinstance(fn, functools.partial):
            captured_kwargs.update(fn.keywords)
        return b"fake-png"

    coord.hass.async_add_executor_job.side_effect = fake_executor

    from custom_components.dreame_a2_mower.coordinator._rendering import _RenderingMixin
    await _RenderingMixin._render_main_view(coord)

    # The key assertion: state passed to render_main_view must have current_activity
    state_arg = captured_kwargs.get("state")
    assert state_arg is not None, (
        "_render_main_view must pass a 'state' kwarg to render_main_view"
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import CurrentActivity as CA
    activity = getattr(state_arg, "current_activity", None)
    assert activity == CA.REPOSITIONING, (
        f"state.current_activity must be REPOSITIONING but got {activity!r}. "
        "ROOT CAUSE: _render_main_view passes state=self.data (MowerState) which "
        "has no current_activity attribute — must forward from state_machine.snapshot()."
    )


# ---------------------------------------------------------------------------
# Test 2: IDLE state machine activity is NOT confused with REPOSITIONING
# ---------------------------------------------------------------------------

async def test_render_main_view_forwards_idle_activity_not_repositioning():
    """When state machine is IDLE, current_activity forwarded to render is IDLE,
    not REPOSITIONING.  Sanity guard against the fix accidentally always forcing REPOSITIONING.
    """
    from custom_components.dreame_a2_mower.mower.state_snapshot import CurrentActivity
    coord = _make_coord_for_render_test(current_activity=CurrentActivity.IDLE)

    captured_kwargs = {}

    async def fake_executor(fn, *args, **kwargs):
        import functools
        if isinstance(fn, functools.partial):
            captured_kwargs.update(fn.keywords)
        return b"fake-png"

    coord.hass.async_add_executor_job.side_effect = fake_executor

    from custom_components.dreame_a2_mower.coordinator._rendering import _RenderingMixin
    await _RenderingMixin._render_main_view(coord)

    state_arg = captured_kwargs.get("state")
    assert state_arg is not None
    activity = getattr(state_arg, "current_activity", None)
    from custom_components.dreame_a2_mower.mower.state_snapshot import CurrentActivity as CA
    assert activity == CA.IDLE, (
        f"IDLE state machine must forward IDLE to render, got {activity!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: End-to-end: REPOSITIONING + ALL_AREAS produces non-striped image
#         through the coordinator render path (plumbing integration test)
# ---------------------------------------------------------------------------

async def test_render_main_view_repositioning_produces_non_striped_png():
    """End-to-end: coordinator._render_main_view with REPOSITIONING state machine
    must produce a dark-green base (no stripe overlay), not the idle striped preview.

    This test uses a real (synchronous) render in the executor to confirm the
    plumbing actually suppresses stripes — not just that the kwarg is passed.
    """
    import io
    from PIL import Image
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    from custom_components.dreame_a2_mower.mower.state import ActionMode
    from custom_components.dreame_a2_mower.map_render import _DEFAULT_PALETTE

    coord = _make_coord_for_render_test(
        current_activity=CurrentActivity.REPOSITIONING,
        mow_session=MowSession.BETWEEN_SESSIONS,
    )
    # Give the state a recognizable action_mode so stripe would appear if REPOSITIONING is ignored
    coord.data.action_mode = ActionMode.ALL_AREAS

    # Run with a REAL synchronous executor (thread pool via run_in_executor would
    # be overkill here; use direct sync call to render_main_view)
    import asyncio
    import concurrent.futures

    real_png_holder = {}

    async def real_executor(fn, *args, **kwargs):
        import functools
        if isinstance(fn, functools.partial):
            result = fn()
            real_png_holder["png"] = result
            return result
        return fn(*args, **kwargs)

    coord.hass.async_add_executor_job.side_effect = real_executor

    from custom_components.dreame_a2_mower.coordinator._rendering import _RenderingMixin
    await _RenderingMixin._render_main_view(coord)

    png = real_png_holder.get("png")
    assert png is not None, "Render must have produced a PNG"
    assert isinstance(png, bytes), f"Expected bytes, got {type(png)}"
    assert len(png) > 0, "PNG must be non-empty"

    # Count light_green pixels — should be < 1% for non-stripe render
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    light_green = _DEFAULT_PALETTE["zone_fills"][0]
    pixels = list(img.getdata())
    light_green_count = sum(1 for p in pixels if p == light_green)
    total_px = len(pixels)
    light_green_pct = 100 * light_green_count / total_px if total_px else 0

    assert light_green_count < total_px * 0.01, (
        f"REPOSITIONING + ALL_AREAS via coordinator must NOT show stripes. "
        f"Got {light_green_count} light_green pixels ({light_green_pct:.1f}%). "
        "This indicates the plumbing bug: current_activity not forwarded from "
        "state_machine.snapshot() to render_main_view."
    )
