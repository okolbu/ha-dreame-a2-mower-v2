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


def test_positioning_failed_off_on_standby_return():
    """s2p2=71 (standby-too-long auto-return) must NOT trip positioning_failed.
    The state machine resolves a plain 71 to LOCALIZED; the sensor must follow
    the snapshot, not raw error_code==71 (which false-trips on every standby
    auto-return — the 2026-05-30 18:26:50 bug)."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth,
    )
    from custom_components.dreame_a2_mower import binary_sensor
    coord = _coord_with_snapshot(positioning_health=PositioningHealth.LOCALIZED)
    coord.data.error_code = 71  # standby-return code is present but not stuck
    description = next(
        d for d in binary_sensor.BINARY_SENSORS if d.key == "positioning_failed"
    )
    assert description.value_fn(coord) is False


def test_positioning_failed_on_when_health_stuck():
    """positioning_failed fires only when the state machine resolves STUCK
    (s2p2=71 followed by 31/33 within the disambiguation window)."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth,
    )
    from custom_components.dreame_a2_mower import binary_sensor
    coord = _coord_with_snapshot(positioning_health=PositioningHealth.STUCK)
    description = next(
        d for d in binary_sensor.BINARY_SENSORS if d.key == "positioning_failed"
    )
    assert description.value_fn(coord) is True


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
