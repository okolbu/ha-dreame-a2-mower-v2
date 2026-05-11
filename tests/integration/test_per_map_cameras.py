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


def test_wifi_refresh_status_sensor_never_when_no_fetches(coordinator_with_two_maps):
    """DreameA2WifiRefreshStatusSensor reports 'never' before any fetch."""
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    coord._wifi_archive_last_refresh = {}
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    assert sensor.native_value == "never"
    assert sensor.extra_state_attributes == {}


def test_wifi_refresh_status_sensor_downloaded(coordinator_with_two_maps):
    """DreameA2WifiRefreshStatusSensor reports 'downloaded' after a successful fetch."""
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    coord._wifi_archive_last_refresh = {
        "last_attempt_unix": 1000,
        "result": "downloaded",
        "fetched": 2,
        "new": 1,
    }
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    assert sensor.native_value == "downloaded"
    assert sensor.extra_state_attributes["result"] == "downloaded"
    assert sensor.extra_state_attributes["new"] == 1


def test_wifi_refresh_status_sensor_no_data(coordinator_with_two_maps):
    """Sensor reports no_data when archive refresh found nothing new."""
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    coord._wifi_archive_last_refresh = {
        "last_attempt_unix": 2000,
        "result": "no_data",
        "fetched": 3,
        "new": 0,
    }
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    assert sensor.native_value == "no_data"
