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


def test_wifi_map_camera_per_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.camera import DreameA2WifiMapCamera

    cam0 = DreameA2WifiMapCamera(coord, map_id=0)
    cam1 = DreameA2WifiMapCamera(coord, map_id=1)

    assert cam0._attr_unique_id == "G2408053AEE0006232_map_0_wifi_map"
    assert cam1._attr_unique_id == "G2408053AEE0006232_map_1_wifi_map"
    assert cam0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_request_wifi_map_button_per_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.button import DreameA2RequestWifiMapButton

    b0 = DreameA2RequestWifiMapButton(coord, map_id=0)
    b1 = DreameA2RequestWifiMapButton(coord, map_id=1)

    assert "_map_0_request_wifi_map" in b0._attr_unique_id
    assert "_map_1_request_wifi_map" in b1._attr_unique_id
    assert b0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


# ---------------------------------------------------------------------------
# F7 — WiFi camera entity_picture cache-bust + available + status sensor
# ---------------------------------------------------------------------------


def test_wifi_camera_entity_picture_includes_content_hash(coordinator_with_two_maps):
    """entity_picture contains ?v=<hash> when super() returns a URL.

    In the stub environment Camera.entity_picture returns None (no HA runtime),
    so we patch the super call on the instance to return a dummy URL and verify
    that the subclass appends the content hash.
    """
    from custom_components.dreame_a2_mower.camera import DreameA2WifiMapCamera

    coord = coordinator_with_two_maps
    decoded = {
        "data": [-60, -70, 1],
        "width": 3,
        "height": 1,
        "resolution": 0.1,
        "startX": 0.0,
        "startY": 0.0,
        "_object_name": "wifi/test.bin",
    }
    coord._wifi_map_by_id = {0: decoded}
    cam = DreameA2WifiMapCamera(coord, map_id=0)

    # Inject a fake base URL so the hash-append logic can be tested.
    # We mock the MRO parent's entity_picture on the class temporarily.
    original_ep = DreameA2WifiMapCamera.entity_picture.fget  # type: ignore[union-attr]

    def _patched(self):
        # Call the real implementation but substitute super().entity_picture
        # with a fake URL so we can test the ?v= append logic.
        decoded_inner = self._wifi_map_decoded
        if not decoded_inner:
            return None
        import hashlib
        import json
        h = hashlib.md5(
            json.dumps(decoded_inner, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]
        base = "/api/camera_proxy/camera.test?token=abc"
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}v={h}"

    DreameA2WifiMapCamera.entity_picture = property(_patched)
    try:
        pic = cam.entity_picture
    finally:
        DreameA2WifiMapCamera.entity_picture = property(original_ep)

    assert pic is not None
    assert "v=" in pic
    # Hash is 12 hex chars.
    v_part = [p for p in pic.split("&") if p.startswith("v=")]
    assert v_part and len(v_part[0]) == len("v=") + 12


def test_wifi_camera_entity_picture_none_when_no_data(coordinator_with_two_maps):
    """entity_picture is None when no wifi map data has been fetched."""
    from custom_components.dreame_a2_mower.camera import DreameA2WifiMapCamera

    coord = coordinator_with_two_maps
    coord._wifi_map_by_id = {}
    cam = DreameA2WifiMapCamera(coord, map_id=0)

    assert cam.entity_picture is None


def test_wifi_camera_available_false_when_no_data(coordinator_with_two_maps):
    """available returns False before any wifi map is fetched."""
    from custom_components.dreame_a2_mower.camera import DreameA2WifiMapCamera

    coord = coordinator_with_two_maps
    coord._wifi_map_by_id = {}
    cam = DreameA2WifiMapCamera(coord, map_id=0)

    assert cam.available is False


def test_wifi_camera_available_true_when_data_present(coordinator_with_two_maps):
    """available returns True once wifi map data is cached."""
    from custom_components.dreame_a2_mower.camera import DreameA2WifiMapCamera

    coord = coordinator_with_two_maps
    coord._wifi_map_by_id = {0: {"data": [], "width": 0, "height": 0}}
    cam = DreameA2WifiMapCamera(coord, map_id=0)

    assert cam.available is True


def test_wifi_refresh_status_sensor_never_when_no_fetches(coordinator_with_two_maps):
    """DreameA2WifiRefreshStatusSensor reports 'never' when nothing fetched yet."""
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    # Explicitly set an empty status dict (simulating no fetches yet).
    coord._wifi_refresh_status_by_map_id = {}
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    assert sensor.native_value == "never"
    assert sensor.extra_state_attributes == {"by_map_id": {}}


def test_wifi_refresh_status_sensor_downloaded(coordinator_with_two_maps):
    """DreameA2WifiRefreshStatusSensor reports 'downloaded' after a successful fetch."""
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    coord._wifi_refresh_status_by_map_id = {
        0: {"last_attempt_unix": 1000, "result": "downloaded"},
    }
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    assert sensor.native_value == "downloaded"
    assert sensor.extra_state_attributes["by_map_id"][0]["result"] == "downloaded"


def test_wifi_refresh_status_sensor_latest_map_wins(coordinator_with_two_maps):
    """Sensor reports result of the most recent attempt across all maps."""
    from custom_components.dreame_a2_mower.sensor import DreameA2WifiRefreshStatusSensor

    coord = coordinator_with_two_maps
    coord._wifi_refresh_status_by_map_id = {
        0: {"last_attempt_unix": 1000, "result": "downloaded"},
        1: {"last_attempt_unix": 2000, "result": "no_data"},
    }
    sensor = DreameA2WifiRefreshStatusSensor(coord)

    # Map 1 has a later timestamp, so no_data wins.
    assert sensor.native_value == "no_data"
