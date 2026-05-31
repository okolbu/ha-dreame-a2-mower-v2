"""TDD: the REPOSITIONING render trigger must fire where an s2p1 push ACTUALLY reaches.

ROOT CAUSE (placement bug):
    The undock render trigger lived inside handle_property_push's `_apply()`
    closure, which only runs when `apply_property_to_state` produces a CHANGED
    MowerState.  s2p1 (state) is a no-op in apply_property_to_state, so the
    push short-circuits at `new_state == self.data` BEFORE `_apply()` runs.
    The state machine, however, processes s2p1 LATER in `_on_mqtt_message`
    (via `handle_mqtt_property`), which is where current_activity becomes
    REPOSITIONING.  So the trigger sat in code an s2p1 push never reaches and
    never fired; the map only flipped at the first s1p4 MOVE ~42s later.

FIX:
    Fire the render in `_on_mqtt_message`, immediately AFTER
    `state_machine.handle_mqtt_property` has applied the s2p1 transition, when
    the snapshot now shows REPOSITIONING.

These tests drive the REAL `_on_mqtt_message` so they fail against the old
(unreachable) placement and pass once the trigger moves.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_coord_for_trigger_test(*, snapshot_activity_after_s2p1):
    """Minimal coordinator stub for driving `_on_mqtt_message`.

    `handle_property_push` is stubbed to a no-op (mirrors the real s2p1
    short-circuit — it never reaches `_apply()`).  `handle_mqtt_property` is
    stubbed to flip the snapshot's current_activity to the given value, which
    is exactly what `_apply_s2p1_task_state` does on the wire.
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)

    # --- live_map (used by the s2p50 capture branch only; inactive here) ---
    lm = MagicMock()
    lm.is_active.return_value = False
    coord.live_map = lm

    # --- snapshot starts non-REPOSITIONING; handle_mqtt_property flips it ---
    snap = MagicMock()
    snap.current_activity = None
    sm = MagicMock()
    sm.snapshot.return_value = snap

    def _apply_s2p1(siid, piid, value, now_unix):
        # The real state machine sets current_activity here for s2p1.
        if (int(siid), int(piid)) == (2, 1):
            snap.current_activity = snapshot_activity_after_s2p1

    sm.handle_mqtt_property.side_effect = _apply_s2p1
    coord.state_machine = sm

    # --- handle_property_push: s2p1 short-circuits (no-op) on the real path ---
    coord.handle_property_push = MagicMock(return_value=None)

    # --- hass ---
    hass = MagicMock()
    hass.async_create_task = MagicMock(return_value=None)
    hass.loop = MagicMock()
    hass.loop.call_soon_threadsafe = MagicMock(return_value=None)
    coord.hass = hass

    # --- render target: a sentinel coroutine so we can identify the call ---
    coord._render_main_view = MagicMock(name="_render_main_view")

    return coord


def _push_s2p1(coord, value):
    from custom_components.dreame_a2_mower.coordinator._mqtt_handlers import (
        _MqttHandlersMixin,
    )

    payload = {
        "method": "properties_changed",
        "params": [{"siid": 2, "piid": 1, "value": value}],
    }
    _MqttHandlersMixin._on_mqtt_message(coord, "topic", payload)


def _render_scheduled(coord) -> bool:
    """True if _render_main_view() was scheduled via hass.async_create_task."""
    render_coro = coord._render_main_view.return_value
    for c in coord.hass.async_create_task.call_args_list:
        if c.args and c.args[0] is render_coro:
            return True
    return False


# ---------------------------------------------------------------------------
# Test 1: undock s2p1 → REPOSITIONING fires the render
# ---------------------------------------------------------------------------

def test_undock_s2p1_repositioning_fires_render():
    """s2p1 push that results in current_activity==REPOSITIONING (undock,
    6/13→1) must schedule _render_main_view.  Regression guard for the
    placement bug: fails when the trigger sits in handle_property_push's
    `_apply()` closure (unreachable for s2p1).
    """
    from custom_components.dreame_a2_mower.mower.state_snapshot import CurrentActivity

    coord = _make_coord_for_trigger_test(
        snapshot_activity_after_s2p1=CurrentActivity.REPOSITIONING,
    )
    _push_s2p1(coord, 1)  # working

    assert _render_scheduled(coord), (
        "s2p1→REPOSITIONING (undock) must schedule _render_main_view where the "
        "push actually reaches (after handle_mqtt_property), not in the "
        "handle_property_push `_apply()` closure that s2p1 short-circuits before."
    )


# ---------------------------------------------------------------------------
# Test 2: return-leg s2p1 (AT_POINT → returning) → REPOSITIONING fires render
# ---------------------------------------------------------------------------

def test_return_leg_s2p1_repositioning_fires_render():
    """s2p1=5 (returning) from AT_POINT also enters REPOSITIONING in the state
    machine; the same trigger must fire the prompt render for the return leg.
    """
    from custom_components.dreame_a2_mower.mower.state_snapshot import CurrentActivity

    coord = _make_coord_for_trigger_test(
        snapshot_activity_after_s2p1=CurrentActivity.REPOSITIONING,
    )
    _push_s2p1(coord, 5)  # returning

    assert _render_scheduled(coord), (
        "Return-leg s2p1→REPOSITIONING must also schedule _render_main_view."
    )


# ---------------------------------------------------------------------------
# Test 3: non-REPOSITIONING s2p1 change → render NOT fired (for this trigger)
# ---------------------------------------------------------------------------

def test_non_repositioning_s2p1_does_not_fire_render():
    """An s2p1 change that does NOT result in REPOSITIONING (e.g. settling to
    IDLE) must NOT fire the undock render trigger.
    """
    from custom_components.dreame_a2_mower.mower.state_snapshot import CurrentActivity

    coord = _make_coord_for_trigger_test(
        snapshot_activity_after_s2p1=CurrentActivity.IDLE,
    )
    _push_s2p1(coord, 2)  # idle/done

    assert not _render_scheduled(coord), (
        "Non-REPOSITIONING s2p1 change must NOT trigger the undock render."
    )


# ---------------------------------------------------------------------------
# Test 4: the trigger fires exactly once per s2p1 push (no double-render)
# ---------------------------------------------------------------------------

def test_repositioning_s2p1_fires_render_exactly_once():
    """Guard against double-rendering: the REPOSITIONING render must be
    scheduled exactly once for a single s2p1 push.
    """
    from custom_components.dreame_a2_mower.mower.state_snapshot import CurrentActivity

    coord = _make_coord_for_trigger_test(
        snapshot_activity_after_s2p1=CurrentActivity.REPOSITIONING,
    )
    _push_s2p1(coord, 1)

    render_coro = coord._render_main_view.return_value
    render_schedule_count = sum(
        1
        for c in coord.hass.async_create_task.call_args_list
        if c.args and c.args[0] is render_coro
    )
    assert render_schedule_count == 1, (
        f"REPOSITIONING render must be scheduled exactly once per s2p1 push, "
        f"got {render_schedule_count}."
    )
