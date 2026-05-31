"""op=109 go-to-point: action payload + table wiring."""
import pytest


def test_go_to_point_payload_builds_point_list():
    from custom_components.dreame_a2_mower.mower.actions import _go_to_point_payload
    assert _go_to_point_payload({"point_id": 1}) == {"point": [1]}
    assert _go_to_point_payload({"point_id": "5"}) == {"point": [5]}


def test_go_to_point_payload_requires_point_id():
    from custom_components.dreame_a2_mower.mower.actions import _go_to_point_payload
    with pytest.raises(ValueError):
        _go_to_point_payload({})


def test_go_to_point_action_table_entry():
    from custom_components.dreame_a2_mower.mower.actions import (
        ACTION_TABLE,
        MowerAction,
        _go_to_point_payload,
    )
    entry = ACTION_TABLE[MowerAction.GO_TO_POINT]
    assert entry["routed_o"] == 109
    assert entry["routed_t"] == "TASK"
    assert entry["payload_fn"] is _go_to_point_payload


def test_mower_state_active_selection_point_defaults_none():
    import dataclasses
    from custom_components.dreame_a2_mower.mower.state import MowerState
    s = MowerState()
    assert s.active_selection_point is None
    s2 = dataclasses.replace(s, active_selection_point=(0, 1))
    assert s2.active_selection_point == (0, 1)


async def test_start_go_to_point_switches_map_then_dispatches():
    from unittest.mock import AsyncMock
    from custom_components.dreame_a2_mower.coordinator._writes import _WritesMixin
    from custom_components.dreame_a2_mower.mower.actions import MowerAction

    class _Stub(_WritesMixin):
        def __init__(self):
            self._ensure_active_map = AsyncMock()
            self.dispatch_action = AsyncMock()

    c = _Stub()
    await c.start_go_to_point(map_id=2, point_id=7)
    c._ensure_active_map.assert_awaited_once_with(2)
    c.dispatch_action.assert_awaited_once_with(
        MowerAction.GO_TO_POINT, {"point_id": 7}
    )
