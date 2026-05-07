"""Tests for SET_ACTIVE_MAP action dispatch payload."""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.mower.actions import (
    ACTION_TABLE,
    MowerAction,
    _set_active_map_payload,
)


def test_set_active_map_payload_extracts_idx():
    payload = _set_active_map_payload({"map_id": 1})
    assert payload == {"idx": 1}


def test_set_active_map_payload_coerces_map_id_to_int():
    payload = _set_active_map_payload({"map_id": "0"})
    assert payload == {"idx": 0}


def test_set_active_map_payload_raises_without_map_id():
    with pytest.raises(ValueError, match="SET_ACTIVE_MAP requires 'map_id'"):
        _set_active_map_payload({})


def test_set_active_map_dispatch_table_routed_to_op_200():
    entry = ACTION_TABLE[MowerAction.SET_ACTIVE_MAP]
    assert entry["routed_t"] == "TASK"
    assert entry["routed_o"] == 200
    assert entry["payload_fn"] is _set_active_map_payload
