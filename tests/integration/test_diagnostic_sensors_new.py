"""New diagnostic sensors: cloud device-id, API endpoint, integration version."""
from __future__ import annotations
from unittest.mock import MagicMock


def _coord():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    cloud = MagicMock()
    cloud.device_id = "BM169439"
    cloud.host = "eu.iot.dreame.tech"
    coord._cloud = cloud
    return coord


def test_cloud_device_id_sensor():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2CloudDeviceIdSensor,
    )
    s = DreameA2CloudDeviceIdSensor(_coord())
    assert s.native_value == "BM169439"
    # conftest stubs EntityCategory as a class with plain-string members.
    assert s._attr_entity_category == "diagnostic"


def test_cloud_device_id_sensor_unknown_when_missing():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2CloudDeviceIdSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._cloud = None
    s = DreameA2CloudDeviceIdSensor(coord)
    assert s.native_value is None


def test_api_endpoint_sensor():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2ApiEndpointSensor,
    )
    s = DreameA2ApiEndpointSensor(_coord())
    assert s.native_value == "eu.iot.dreame.tech:19973"


def test_integration_version_sensor():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2IntegrationVersionSensor,
    )
    s = DreameA2IntegrationVersionSensor(_coord())
    val = s.native_value
    assert isinstance(val, str)
    assert val
