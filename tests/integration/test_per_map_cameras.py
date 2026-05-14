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


# ---------------------------------------------------------------------------
# v1.0.10a6+ — WiFi heatmap age sensor
# ---------------------------------------------------------------------------


def test_wifi_heatmap_age_sensor_none_when_archive_empty(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2WifiHeatmapAgeSensor,
    )

    coord = coordinator_with_two_maps
    coord._wifi_archive_index = []
    sensor = DreameA2WifiHeatmapAgeSensor(coord)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_wifi_heatmap_age_sensor_reports_seconds_since_newest(
    coordinator_with_two_maps,
):
    """Native value is now - newest unix_ts (seconds)."""
    import time as _time
    from types import SimpleNamespace
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2WifiHeatmapAgeSensor,
    )

    coord = coordinator_with_two_maps
    now = int(_time.time())
    coord._wifi_archive_index = [
        SimpleNamespace(object_name="old", unix_ts=now - 3600, map_id=0),
        SimpleNamespace(object_name="new", unix_ts=now - 60, map_id=1),
    ]
    sensor = DreameA2WifiHeatmapAgeSensor(coord)
    val = sensor.native_value
    assert val is not None
    # Newest is 60s old — allow a couple of seconds drift since the
    # sensor reads its own _time.time() internally.
    assert 55 <= val <= 65
    attrs = sensor.extra_state_attributes
    assert attrs["newest_unix_ts"] == now - 60
    assert attrs["archive_total"] == 2


def test_wifi_heatmap_age_sensor_skips_zero_unix_ts(coordinator_with_two_maps):
    """Entries with unix_ts==0 (un-parseable) are ignored when picking newest."""
    import time as _time
    from types import SimpleNamespace
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2WifiHeatmapAgeSensor,
    )

    coord = coordinator_with_two_maps
    now = int(_time.time())
    coord._wifi_archive_index = [
        SimpleNamespace(object_name="bad", unix_ts=0, map_id=0),
        SimpleNamespace(object_name="real", unix_ts=now - 120, map_id=1),
    ]
    sensor = DreameA2WifiHeatmapAgeSensor(coord)
    assert sensor.native_value is not None
    # All-zero archive returns None.
    coord._wifi_archive_index = [
        SimpleNamespace(object_name="bad", unix_ts=0, map_id=0),
    ]
    sensor2 = DreameA2WifiHeatmapAgeSensor(coord)
    assert sensor2.native_value is None


# ---------------------------------------------------------------------------
# v1.0.10a6+ — DreameA2WifiPerMapCamera
# ---------------------------------------------------------------------------


def test_wifi_per_map_camera_unique_id_uses_map_subdevice(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.camera import DreameA2WifiPerMapCamera

    coord = coordinator_with_two_maps
    cam0 = DreameA2WifiPerMapCamera(coord, map_id=0)
    cam1 = DreameA2WifiPerMapCamera(coord, map_id=1)
    assert cam0._attr_unique_id == "G2408053AEE0006232_map_0_wifi_heatmap"
    assert cam1._attr_unique_id == "G2408053AEE0006232_map_1_wifi_heatmap"
    assert cam0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_wifi_per_map_camera_resolve_entry_filters_by_map_id(
    coordinator_with_two_maps,
):
    from types import SimpleNamespace
    from custom_components.dreame_a2_mower.camera import DreameA2WifiPerMapCamera

    coord = coordinator_with_two_maps
    # Three entries — two for map 0 (different unix_ts), one for map 1.
    coord._wifi_archive_index = [
        SimpleNamespace(object_name="a", unix_ts=1000, map_id=0),
        SimpleNamespace(object_name="b", unix_ts=2000, map_id=0),
        SimpleNamespace(object_name="c", unix_ts=1500, map_id=1),
    ]
    cam0 = DreameA2WifiPerMapCamera(coord, map_id=0)
    cam1 = DreameA2WifiPerMapCamera(coord, map_id=1)
    # Newest map-0 entry should win.
    assert cam0._resolve_entry().object_name == "b"
    assert cam1._resolve_entry().object_name == "c"


def test_wifi_per_map_camera_unavailable_when_no_match(coordinator_with_two_maps):
    from types import SimpleNamespace
    from custom_components.dreame_a2_mower.camera import DreameA2WifiPerMapCamera

    coord = coordinator_with_two_maps
    coord._wifi_archive_index = [
        SimpleNamespace(object_name="a", unix_ts=1000, map_id=-1),
        SimpleNamespace(object_name="b", unix_ts=2000, map_id=0),
    ]
    cam_no_map = DreameA2WifiPerMapCamera(coord, map_id=5)
    assert cam_no_map._resolve_entry() is None
    assert cam_no_map.available is False
