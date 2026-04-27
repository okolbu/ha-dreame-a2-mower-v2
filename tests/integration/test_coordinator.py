"""Coordinator tests — state update flow.

These use pytest-homeassistant-custom-component (added in F1.4.3).
F1.4.2 starts with a non-HA test that just verifies the
update-state-from-payload logic.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state import (
    ChargingStatus,
    MowerState,
    State,
)
from custom_components.dreame_a2_mower.coordinator import (
    apply_property_to_state,
)


def test_apply_battery_level_property():
    """A (3, 1) property push updates MowerState.battery_level."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=1, value=72)
    assert new_state.battery_level == 72
    # Other fields unchanged
    assert new_state.state is None
    assert new_state.charging_status is None


def test_apply_state_property():
    """A (2, 1) property push updates MowerState.state."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=2, piid=1, value=1)
    assert new_state.state == State.WORKING


def test_apply_charging_status_property():
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=2, value=1)
    assert new_state.charging_status == ChargingStatus.CHARGING


def test_apply_unknown_property_returns_unchanged_state():
    """Unknown (siid, piid) is logged elsewhere; the state is unchanged."""
    state = MowerState(battery_level=50)
    new_state = apply_property_to_state(state, siid=99, piid=99, value="weird")
    assert new_state == state


def test_apply_property_with_invalid_state_value_keeps_field_none():
    """Invalid enum values are dropped (the integration logs NOVEL elsewhere)."""
    state = MowerState()
    # 999 is not a valid State enum
    new_state = apply_property_to_state(state, siid=2, piid=1, value=999)
    assert new_state.state is None
