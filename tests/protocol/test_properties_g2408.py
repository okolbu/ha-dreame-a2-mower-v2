"""Tests for the g2408 siid/piid property map."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.protocol.properties_g2408 import (
    Property,
    PROPERTY_MAP,
    ChargingStatus,
    siid_piid,
    property_for,
    charging_label,
)


def test_property_map_returns_battery_siid_piid():
    assert siid_piid(Property.BATTERY_LEVEL) == (3, 1)


def test_property_map_returns_telemetry_blob_siid_piid():
    assert siid_piid(Property.MOWING_TELEMETRY) == (1, 4)


def test_property_map_returns_heartbeat_blob_siid_piid():
    assert siid_piid(Property.HEARTBEAT) == (1, 1)


def test_property_map_returns_obstacle_flag_siid_piid():
    assert siid_piid(Property.OBSTACLE_FLAG) == (1, 53)


def test_property_map_returns_multiplexed_config_siid_piid():
    assert siid_piid(Property.MULTIPLEXED_CONFIG) == (2, 51)


def test_property_for_reverse_lookup_known_siid_piid():
    assert property_for(3, 1) is Property.BATTERY_LEVEL
    assert property_for(1, 4) is Property.MOWING_TELEMETRY


def test_property_for_unknown_siid_piid_returns_none():
    assert property_for(99, 99) is None


def test_property_map_does_not_route_2_2_to_state():
    # Regression: an early revision claimed Property.STATE = (2, 2). The
    # actual STATE enum lives at (2, 1); (2, 2) carries the apk fault
    # index. PROPERTY_MAP must not expose a STATE alias for either slot.
    assert (2, 2) not in PROPERTY_MAP.values()
    assert not hasattr(Property, "STATE")


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (0, "not_charging"),
        (1, "charging"),
        (2, "charged"),
    ],
)
def test_charging_label_translates_g2408_s3p2_codes(code, label):
    assert charging_label(ChargingStatus(code)) == label


def test_charging_label_unknown_returns_unknown_with_raw():
    assert charging_label(42) == "unknown_42"
