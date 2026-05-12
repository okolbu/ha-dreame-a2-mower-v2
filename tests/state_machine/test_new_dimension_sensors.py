"""New sensors for dimension state."""
from __future__ import annotations
import dataclasses
from unittest.mock import MagicMock


def _coord(**overrides):
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord.state_machine.snapshot.return_value = dataclasses.replace(
        StateSnapshot.initial(), **overrides,
    )
    return coord


def test_current_activity_sensor():
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2CurrentActivitySensor,
    )
    coord = _coord(current_activity=CurrentActivity.CRUISING_TO_POINT)
    s = DreameA2CurrentActivitySensor(coord)
    assert s.native_value == "cruising_to_point"


def test_location_sensor():
    from custom_components.dreame_a2_mower.mower.state_snapshot import Location
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2LocationSensor,
    )
    coord = _coord(location=Location.AT_POINT)
    s = DreameA2LocationSensor(coord)
    assert s.native_value == "at_point"


def test_positioning_health_sensor():
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        PositioningHealth,
    )
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2PositioningHealthSensor,
    )
    coord = _coord(positioning_health=PositioningHealth.STUCK)
    s = DreameA2PositioningHealthSensor(coord)
    assert s.native_value == "stuck"


def test_mqtt_connectivity_sensor():
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Connectivity,
    )
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MqttConnectivitySensor,
    )
    coord = _coord(mqtt_connectivity=Connectivity.STALE)
    s = DreameA2MqttConnectivitySensor(coord)
    assert s.native_value == "stale"


def test_sensors_are_enum_device_class():
    """All 4 dimension sensors expose SensorDeviceClass.ENUM with options."""
    from homeassistant.components.sensor import SensorDeviceClass
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2CurrentActivitySensor,
        DreameA2LocationSensor,
        DreameA2PositioningHealthSensor,
        DreameA2MqttConnectivitySensor,
    )
    for cls in (DreameA2CurrentActivitySensor, DreameA2LocationSensor,
                DreameA2PositioningHealthSensor, DreameA2MqttConnectivitySensor):
        assert cls._attr_device_class == SensorDeviceClass.ENUM
        assert isinstance(cls._attr_options, list)
        assert len(cls._attr_options) > 0
