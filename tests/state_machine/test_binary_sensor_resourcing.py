"""binary_sensor migration to snapshot fields."""
from __future__ import annotations
import dataclasses
from unittest.mock import MagicMock


def _coord_with_snapshot(**overrides):
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    snap = dataclasses.replace(StateSnapshot.initial(), **overrides)
    coord.state_machine.snapshot.return_value = snap
    return coord


def test_mower_in_dock_is_on_when_location_at_dock():
    """Whatever entity exposes mower_in_dock, its is_on should be True
    when snapshot.location == AT_DOCK."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import Location
    coord = _coord_with_snapshot(location=Location.AT_DOCK)
    from custom_components.dreame_a2_mower import binary_sensor
    description = next(
        d for d in binary_sensor.BINARY_SENSORS if d.key == "mower_in_dock"
    )
    result = description.value_fn(coord)
    assert result is True


def test_mower_in_dock_is_off_when_location_elsewhere():
    from custom_components.dreame_a2_mower.mower.state_snapshot import Location
    from custom_components.dreame_a2_mower import binary_sensor
    description = next(
        d for d in binary_sensor.BINARY_SENSORS if d.key == "mower_in_dock"
    )
    for loc in (Location.ON_LAWN, Location.AT_POINT, Location.OUTSIDE_KNOWN_AREA):
        coord = _coord_with_snapshot(location=loc)
        assert description.value_fn(coord) is False, f"expected False for {loc}"


def test_mowing_session_active_true_only_in_mow_session():
    """Cruise must NOT trigger mowing_session_active."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        MowSession, CurrentActivity,
    )
    from custom_components.dreame_a2_mower import binary_sensor
    description = next(
        d for d in binary_sensor.BINARY_SENSORS if d.key == "mowing_session_active"
    )
    # In-mow -> True
    coord_mow = _coord_with_snapshot(
        mow_session=MowSession.IN_SESSION,
        current_activity=CurrentActivity.MOWING,
    )
    assert description.value_fn(coord_mow) is True
    # Cruise -> False (between_sessions even when cruise active)
    coord_cruise = _coord_with_snapshot(
        mow_session=MowSession.BETWEEN_SESSIONS,
        current_activity=CurrentActivity.CRUISING_TO_POINT,
    )
    assert description.value_fn(coord_cruise) is False
