"""Per-map cameras attached to their map sub-device. Includes F7 wifi camera tests."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.const import DOMAIN


def test_per_map_snapshot_on_subdevice(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.camera import DreameA2PerMapCamera

    cam0 = DreameA2PerMapCamera(coord, map_id=0)
    cam1 = DreameA2PerMapCamera(coord, map_id=1)

    assert cam0._attr_unique_id == "G2408053AEE0006232_map_0_map"
    assert cam1._attr_unique_id == "G2408053AEE0006232_map_1_map"
    assert cam0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


# ---------------------------------------------------------------------------
# F7 — WiFi archive refresh status sensor
# ---------------------------------------------------------------------------


def test_wifi_refresh_status_sensor_none_when_no_fetches(coordinator_with_two_maps):
    """Sensor returns None before any fetch — HA renders as 'unknown'."""
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    coord._wifi_archive_last_refresh = {}
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_wifi_refresh_status_sensor_returns_timestamp_after_fetch(
    coordinator_with_two_maps,
):
    """After a refresh, native_value is the attempt timestamp as datetime."""
    from datetime import UTC, datetime
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    coord._wifi_archive_last_refresh = {
        "last_attempt_unix": 1000,
        "result": "downloaded",
        "fetched": 2,
        "new": 1,
    }
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    assert sensor.native_value == datetime(1970, 1, 1, 0, 16, 40, tzinfo=UTC)
    # last_attempt_unix is the state — should NOT appear in attributes.
    assert "last_attempt_unix" not in sensor.extra_state_attributes
    assert sensor.extra_state_attributes["result"] == "downloaded"
    assert sensor.extra_state_attributes["new"] == 1
    assert sensor.extra_state_attributes["fetched"] == 2


def test_wifi_refresh_status_sensor_no_data_still_records_timestamp(
    coordinator_with_two_maps,
):
    """A refresh that found no new objects still timestamps; result moves
    to an attribute, not the state."""
    from datetime import UTC, datetime
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    coord._wifi_archive_last_refresh = {
        "last_attempt_unix": 2000,
        "result": "no_data",
        "fetched": 3,
        "new": 0,
    }
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    assert sensor.native_value == datetime(1970, 1, 1, 0, 33, 20, tzinfo=UTC)
    assert sensor.extra_state_attributes["result"] == "no_data"


def test_wifi_refresh_status_sensor_has_timestamp_device_class():
    """Device class TIMESTAMP makes HA render the state as 'X minutes ago'."""
    from homeassistant.components.sensor import SensorDeviceClass
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    assert DreameA2WifiRefreshStatusSensor._attr_device_class == SensorDeviceClass.TIMESTAMP
