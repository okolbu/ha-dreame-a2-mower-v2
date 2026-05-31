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
