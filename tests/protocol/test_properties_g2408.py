"""Tests for the g2408 siid/piid property map."""

from __future__ import annotations

import pytest

from protocol.properties_g2408 import (
    Property,
    PROPERTY_MAP,
    StateCode,
    ChargingStatus,
    siid_piid,
    property_for,
    state_label,
    charging_label,
)


def test_property_map_returns_battery_siid_piid():
    assert siid_piid(Property.BATTERY_LEVEL) == (3, 1)


def test_property_map_returns_state_siid_piid():
    assert siid_piid(Property.STATE) == (2, 2)


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


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (70, "mowing"),
        (54, "returning"),
        (48, "mowing_complete"),
        (50, "session_started"),
        (27, "idle"),
    ],
)
def test_state_label_translates_known_g2408_s2p2_codes(code, label):
    assert state_label(StateCode(code)) == label


def test_state_label_unknown_code_returns_unknown_with_raw():
    assert state_label(999) == "unknown_999"


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
