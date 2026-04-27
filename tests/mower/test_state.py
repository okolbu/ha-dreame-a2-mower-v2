"""Regression tests for MowerState — the typed domain model."""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.mower.state import (
    ChargingStatus,
    MowerState,
    State,
)


def test_mower_state_defaults_are_unknown():
    """Fresh MowerState has unknown values — represents 'no data yet'."""
    s = MowerState()
    assert s.state is None
    assert s.battery_level is None
    assert s.charging_status is None


def test_state_enum_covers_g2408_apk_values():
    """The State enum must include every value the apk decompilation
    documents on g2408 per protocol-doc §2.1."""
    expected = {1, 2, 3, 5, 6, 11, 13, 14}
    actual = {s.value for s in State}
    assert expected.issubset(actual), f"missing: {expected - actual}"


def test_charging_status_enum_covers_g2408_values():
    """ChargingStatus enum covers the {0, 1, 2} range observed on g2408."""
    expected = {0, 1, 2}
    actual = {c.value for c in ChargingStatus}
    assert expected == actual


def test_mower_state_with_all_fields_set():
    """MowerState supports keyword construction with all fields."""
    s = MowerState(
        state=State.WORKING,
        battery_level=72,
        charging_status=ChargingStatus.NOT_CHARGING,
    )
    assert s.state == State.WORKING
    assert s.battery_level == 72
    assert s.charging_status == ChargingStatus.NOT_CHARGING
