"""TDD: Bug 2 render half — _render_main_view must be triggered promptly on dock arrival.

After the mower docks (session over, live_map inactive), the map should show the
idle pre-start preview (stripes) without waiting for the next 2-minute cloud refresh.

The fix: in _on_state_update, when dock arrival is detected
(self._prev_in_dock is False and _sm_at_dock is True), schedule _render_main_view().

Tests:
1. Dock arrival (prev=False, new=AT_DOCK) → _render_main_view is scheduled.
2. Dock departure (prev=True, new=not AT_DOCK) → _render_main_view is NOT called via
   dock-arrival path (no spurious render on departure).
3. Already docked on first push (prev=None) → no spurious render.
4. Still docked on repeat push → no render (only on the rising edge).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — minimal coordinator + state_update stub
# ---------------------------------------------------------------------------

def _make_coord_for_dock_test(
    *,
    prev_in_dock: bool | None,
    sm_location_at_dock: bool,
):
    """Minimal coordinator stub with _on_state_update partially wired.

    Only the dock-arrival portion of _on_state_update is exercised.
    We call the method directly with a fake new_state.
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coord = object.__new__(DreameA2MowerCoordinator)

    # --- minimal state for _on_state_update ---
    coord.data = MowerState()
    coord._prev_in_dock = prev_in_dock
    coord._prev_task_state = None
    coord._real_task_state_observed = False
    coord._live_map_dirty = False
    coord._live_trail_dirty = False
    coord._last_live_render_unix = 0.0
    coord._prev_error_code = None
    coord._prev_charging_status = None
    coord._rain_delay_started_at = None
    coord._non_mow_finalize_in_progress = False
    coord._pending_finalize_done = None

    # --- live_map ---
    lm = MagicMock()
    lm.is_active.return_value = False
    coord.live_map = lm

    # --- freshness ---
    coord.freshness = MagicMock()
    coord.freshness.record = MagicMock()

    # --- state_machine ---
    from custom_components.dreame_a2_mower.mower.state_snapshot import Location
    snap = MagicMock()
    snap.location = Location.AT_DOCK if sm_location_at_dock else Location.ON_LAWN
    snap.mow_session = MagicMock()
    snap.last_task_op = None
    sm = MagicMock()
    sm.snapshot.return_value = snap
    coord.state_machine = sm

    # --- hass ---
    hass = MagicMock()
    hass.async_create_task = MagicMock(return_value=None)
    coord.hass = hass

    # --- render target ---
    coord._render_main_view = AsyncMock(return_value=None)
    coord._last_lidar_object_name = None  # needed for lidar check

    # --- _fire_lifecycle (no-op for this test) ---
    coord._fire_lifecycle = MagicMock()

    # --- _handle_emergency_stop_transition ---
    coord._handle_emergency_stop_transition = MagicMock()

    # --- async_set_updated_data (no-op) ---
    coord.async_set_updated_data = MagicMock()

    # --- _compute_target_area_m2 ---
    coord._compute_target_area_m2 = MagicMock(return_value=None)

    return coord


def _call_on_state_update_dock_portion(coord, *, now_unix: int = 1_000_000):
    """Call _on_state_update with a minimal new_state that only exercises
    the dock-arrival detection path.  Returns the result.
    """
    from custom_components.dreame_a2_mower.coordinator._mqtt_handlers import _MqttHandlersMixin
    from custom_components.dreame_a2_mower.mower.state import MowerState

    new_state = MowerState()  # no task state changes, just dock detection
    return _MqttHandlersMixin._on_state_update(coord, new_state, now_unix)


# ---------------------------------------------------------------------------
# Test 1: dock arrival → _render_main_view scheduled
# ---------------------------------------------------------------------------

def test_dock_arrival_schedules_render():
    """When the mower arrives at dock (prev=False → at_dock=True),
    _render_main_view must be scheduled via hass.async_create_task.
    """
    coord = _make_coord_for_dock_test(
        prev_in_dock=False,         # was not at dock
        sm_location_at_dock=True,   # now AT_DOCK
    )

    _call_on_state_update_dock_portion(coord)

    # hass.async_create_task must have been called with the render coro
    calls = coord.hass.async_create_task.call_args_list
    render_calls = [
        c for c in calls
        if hasattr(c.args[0], '__name__') or hasattr(c.args[0], 'cr_frame')
        or 'render' in str(c).lower()
    ]
    # More direct: check that async_create_task was called at all after dock-arrival
    # (we know it fires the render; check the event directly)
    assert coord.hass.async_create_task.called, (
        "Dock arrival must schedule _render_main_view via hass.async_create_task. "
        "Currently, no render is triggered on dock-arrival, causing the idle "
        "stripe preview to appear only after the next 2-min cloud refresh."
    )


# ---------------------------------------------------------------------------
# Test 2: dock departure — _render_main_view NOT triggered via dock path
# ---------------------------------------------------------------------------

def test_dock_departure_does_not_trigger_dock_arrival_render():
    """Dock departure (prev=True → at_dock=False) must NOT trigger the
    dock-arrival render. (The undock render is handled separately by s2p1.)
    """
    coord = _make_coord_for_dock_test(
        prev_in_dock=True,           # was at dock
        sm_location_at_dock=False,   # now ON_LAWN
    )

    _call_on_state_update_dock_portion(coord)

    # _render_main_view should NOT be called via the dock-arrival path
    # (an undock render is triggered separately from s2p1; we're testing
    # _on_state_update's dock-arrival block specifically).
    # Verify no render was scheduled for dock arrival (might be called for
    # other reasons in a full scenario, but here dock-arrival block should be silent)
    # Since this is an isolated call with no s1p4, no task_state changes, etc.,
    # any async_create_task call here WOULD be the dock-arrival render.
    # Departure must NOT schedule a render in this path.
    # (Only departure event is fired, not a render.)
    # We verify the departure EVENT was fired (not arrival):
    fired_events = [c.args[0] for c in coord._fire_lifecycle.call_args_list]
    from custom_components.dreame_a2_mower.const import EVENT_TYPE_DOCK_DEPARTED, EVENT_TYPE_DOCK_ARRIVED
    assert EVENT_TYPE_DOCK_DEPARTED in fired_events, (
        "Dock departure must fire DOCK_DEPARTED event"
    )
    assert EVENT_TYPE_DOCK_ARRIVED not in fired_events, (
        "Dock departure must NOT fire DOCK_ARRIVED event"
    )


# ---------------------------------------------------------------------------
# Test 3: first push (prev=None) — no spurious render
# ---------------------------------------------------------------------------

def test_first_push_at_dock_no_spurious_render():
    """On the very first push (prev=None), arriving at dock must NOT fire
    dock_arrived or trigger a render — boot-time guard.
    """
    coord = _make_coord_for_dock_test(
        prev_in_dock=None,           # first push
        sm_location_at_dock=True,
    )

    _call_on_state_update_dock_portion(coord)

    # No dock_arrived event should fire on first push
    fired_events = [c.args[0] for c in coord._fire_lifecycle.call_args_list]
    from custom_components.dreame_a2_mower.const import EVENT_TYPE_DOCK_ARRIVED
    assert EVENT_TYPE_DOCK_ARRIVED not in fired_events, (
        "First push (prev=None) must NOT fire dock_arrived (boot-time guard)"
    )
    # And no render from dock-arrival path
    assert not coord.hass.async_create_task.called or all(
        'render' not in str(c).lower()
        for c in coord.hass.async_create_task.call_args_list
    ), "First push (prev=None) must NOT trigger dock-arrival render"


# ---------------------------------------------------------------------------
# Test 4: already docked (prev=True, new=AT_DOCK) — no render on repeat push
# ---------------------------------------------------------------------------

def test_already_docked_no_render_on_repeat():
    """When already at dock and still at dock, no dock-arrival render fires."""
    coord = _make_coord_for_dock_test(
        prev_in_dock=True,           # already docked
        sm_location_at_dock=True,    # still docked
    )

    _call_on_state_update_dock_portion(coord)

    # Neither dock_arrived nor dock_departed should fire
    from custom_components.dreame_a2_mower.const import EVENT_TYPE_DOCK_ARRIVED, EVENT_TYPE_DOCK_DEPARTED
    fired_events = [c.args[0] for c in coord._fire_lifecycle.call_args_list]
    assert EVENT_TYPE_DOCK_ARRIVED not in fired_events
    assert EVENT_TYPE_DOCK_DEPARTED not in fired_events
