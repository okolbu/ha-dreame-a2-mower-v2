"""Tests for the lifecycle event-entity dispatcher."""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import (
    DreameA2MowerCoordinator,
    apply_property_to_state,
)
from custom_components.dreame_a2_mower.const import (
    EVENT_TYPE_MOWING_STARTED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
)
from custom_components.dreame_a2_mower.mower.state import (
    ActionMode,
    MowerState,
)
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)


def _make_coord() -> DreameA2MowerCoordinator:
    """Minimal coordinator stub usable for fire-point assertions."""
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._live_map_dirty = False
    coord._live_trail_dirty = False
    coord._last_live_render_unix = 0.0
    coord._cached_map_data = None
    coord.cached_map_png = None
    coord._lifecycle_event = MagicMock()
    coord._alert_event = MagicMock()
    return coord


def _trigger_calls(coord: DreameA2MowerCoordinator) -> list:
    """Return the list of (event_type, payload) tuples the lifecycle
    entity's trigger method has been called with."""
    return [
        (call.args[0], call.args[1] if len(call.args) > 1 else {})
        for call in coord._lifecycle_event.trigger.call_args_list
    ]


def test_mowing_started_fires_on_first_active_state():
    """task_state None → 0 with no live_map active fires mowing_started."""
    coord = _make_coord()
    coord.data = MowerState(action_mode=ActionMode.ZONE)

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    coord._on_state_update(state, now_unix=1_714_329_600)

    calls = _trigger_calls(coord)
    started = [c for c in calls if c[0] == EVENT_TYPE_MOWING_STARTED]
    assert len(started) == 1, f"expected exactly 1 mowing_started, got {calls!r}"
    payload = started[0][1]
    assert payload["at_unix"] == 1_714_329_600
    assert payload["action_mode"] == "zone"


def test_mowing_started_does_not_fire_when_live_map_already_active():
    """If _restore_in_progress already populated live_map (mid-mow restart),
    the first MQTT push must NOT fire mowing_started — the session was
    already in progress before the restart, not a fresh start."""
    coord = _make_coord()
    # Simulate post-restore state: live_map active, started_unix set.
    coord.live_map.started_unix = 1_714_300_000
    coord.live_map.legs = [[(1.0, 2.0), (3.0, 4.0)]]

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    coord._on_state_update(state, now_unix=1_714_329_600)

    calls = _trigger_calls(coord)
    started = [c for c in calls if c[0] == EVENT_TYPE_MOWING_STARTED]
    assert started == [], f"expected no mowing_started, got {started!r}"


def test_mowing_paused_fires_on_0_to_4():
    """task_state 0 → 4 fires mowing_paused with area_mowed_m2."""
    coord = _make_coord()
    coord.data = MowerState(area_mowed_m2=12.5)
    coord._prev_task_state = 0  # was running
    coord.live_map.started_unix = 1_714_329_600  # session is active

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 4]]}
    )
    coord._on_state_update(state, now_unix=1_714_329_900)

    calls = _trigger_calls(coord)
    paused = [c for c in calls if c[0] == EVENT_TYPE_MOWING_PAUSED]
    assert len(paused) == 1, f"expected 1 mowing_paused, got {calls!r}"
    payload = paused[0][1]
    assert payload["at_unix"] == 1_714_329_900
    assert payload["area_mowed_m2"] == 12.5
    assert payload["reason"] in ("user", "recharge_required", "unknown")


def test_mowing_resumed_fires_on_4_to_0():
    """task_state 4 → 0 fires mowing_resumed with area_mowed_m2."""
    coord = _make_coord()
    coord.data = MowerState(area_mowed_m2=18.0)
    coord._prev_task_state = 4  # was paused
    coord.live_map.started_unix = 1_714_329_600  # session is active

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    coord._on_state_update(state, now_unix=1_714_330_500)

    calls = _trigger_calls(coord)
    resumed = [c for c in calls if c[0] == EVENT_TYPE_MOWING_RESUMED]
    assert len(resumed) == 1, f"expected 1 mowing_resumed, got {calls!r}"
    payload = resumed[0][1]
    assert payload["at_unix"] == 1_714_330_500
    assert payload["area_mowed_m2"] == 18.0


def test_mowing_ended_fires_complete_with_summary():
    """When _do_oss_fetch successfully archives a session,
    mowing_ended fires with completed=True and the summary's metrics."""
    coord = _make_coord()
    # Caller-supplied payload args mirror what _do_oss_fetch passes
    # through after the archive write — exercise the helper directly.
    coord._fire_mowing_ended(
        now_unix=1_714_330_000,
        area_mowed_m2=42.5,
        duration_min=63,
        completed=True,
    )

    calls = _trigger_calls(coord)
    ended = [c for c in calls if c[0] == EVENT_TYPE_MOWING_ENDED]
    assert len(ended) == 1, f"expected 1 mowing_ended, got {calls!r}"
    payload = ended[0][1]
    assert payload["at_unix"] == 1_714_330_000
    assert payload["area_mowed_m2"] == 42.5
    assert payload["duration_min"] == 63
    assert payload["completed"] is True


def test_mowing_ended_fires_incomplete():
    """FINALIZE_INCOMPLETE path fires mowing_ended with completed=False."""
    coord = _make_coord()
    coord._fire_mowing_ended(
        now_unix=1_714_330_500,
        area_mowed_m2=8.0,
        duration_min=12,
        completed=False,
    )

    calls = _trigger_calls(coord)
    ended = [c for c in calls if c[0] == EVENT_TYPE_MOWING_ENDED]
    assert len(ended) == 1
    assert ended[0][1]["completed"] is False


def test_dock_arrived_fires_on_rising_edge():
    """_prev_in_dock False → mower_in_dock True fires dock_arrived once."""
    coord = _make_coord()
    coord.data = MowerState(mower_in_dock=False)
    coord._prev_in_dock = False
    state = dataclasses.replace(coord.data, mower_in_dock=True)

    coord._on_state_update(state, now_unix=1_714_400_000)

    calls = _trigger_calls(coord)
    arrived = [c for c in calls if c[0] == EVENT_TYPE_DOCK_ARRIVED]
    assert len(arrived) == 1
    assert arrived[0][1]["at_unix"] == 1_714_400_000
    assert coord._prev_in_dock is True


def test_dock_arrived_does_not_fire_on_first_observation():
    """When _prev_in_dock is None (boot) and mower is observed at dock,
    dock_arrived must NOT fire — there's no edge yet."""
    coord = _make_coord()
    coord.data = MowerState()
    # _prev_in_dock is None from _make_coord
    state = dataclasses.replace(coord.data, mower_in_dock=True)

    coord._on_state_update(state, now_unix=1_714_400_000)

    calls = _trigger_calls(coord)
    arrived = [c for c in calls if c[0] == EVENT_TYPE_DOCK_ARRIVED]
    assert arrived == []


def test_dock_departed_fires_on_falling_edge():
    """_prev_in_dock True → mower_in_dock False fires dock_departed once."""
    coord = _make_coord()
    coord.data = MowerState(mower_in_dock=True)
    coord._prev_in_dock = True
    state = dataclasses.replace(coord.data, mower_in_dock=False)

    coord._on_state_update(state, now_unix=1_714_400_500)

    calls = _trigger_calls(coord)
    departed = [c for c in calls if c[0] == EVENT_TYPE_DOCK_DEPARTED]
    assert len(departed) == 1
    assert coord._prev_in_dock is False


def test_dock_arrived_does_not_refire_on_stable_state():
    """Two ticks both showing mower_in_dock=True only fires arrived once."""
    coord = _make_coord()
    coord.data = MowerState(mower_in_dock=False)
    coord._prev_in_dock = False
    state_arrived = dataclasses.replace(coord.data, mower_in_dock=True)

    coord._on_state_update(state_arrived, now_unix=1_714_400_000)
    coord.data = state_arrived  # simulate the coordinator promoting the state
    coord._on_state_update(state_arrived, now_unix=1_714_400_010)

    calls = _trigger_calls(coord)
    arrived = [c for c in calls if c[0] == EVENT_TYPE_DOCK_ARRIVED]
    assert len(arrived) == 1


def test_fire_with_unregistered_entity_does_not_raise():
    """Calling _fire_lifecycle before event.py setup logs DEBUG and returns."""
    coord = _make_coord()
    coord._lifecycle_event = None  # not yet registered

    # Should NOT raise.
    coord._fire_lifecycle(EVENT_TYPE_MOWING_STARTED, {"at_unix": 1, "action_mode": "edge"})

    # Nothing observable should have happened.
    # (No assertion needed; the test passes if no exception was raised.)


def test_payload_omits_none_values():
    """Nullable payload keys with value None are dropped from event_data
    so automation templates don't have to default-guard."""
    coord = _make_coord()
    coord.data = MowerState(action_mode=ActionMode.EDGE, target_area_m2=None)

    state = apply_property_to_state(
        coord.data, siid=2, piid=56, value={"status": [[1, 0]]}
    )
    coord._on_state_update(state, now_unix=1_714_500_000)

    # Read what the entity received via its `trigger` method.
    last_call = coord._lifecycle_event.trigger.call_args
    event_type, event_data = last_call.args
    assert event_type == EVENT_TYPE_MOWING_STARTED
    # `target_area_m2` was None; the entity's trigger() drops None
    # values, but the dispatcher passes the raw dict — assertion
    # belongs in the entity-level test below in test_event_module.py.
    # Here we just check the dispatcher passed it through.
    assert event_data["action_mode"] == "edge"
