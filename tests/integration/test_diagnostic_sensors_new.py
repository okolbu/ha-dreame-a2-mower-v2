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


def _cloud_device_id_descriptor():
    from custom_components.dreame_a2_mower.sensor import DIAGNOSTIC_SENSORS
    return next(d for d in DIAGNOSTIC_SENSORS if d.key == "cloud_device_id")


def test_cloud_device_id_sensor():
    d = _cloud_device_id_descriptor()
    assert d.value_fn(_coord()) == "BM169439"
    assert d.entity_category == "diagnostic"


def test_cloud_device_id_sensor_none_when_missing():
    """When the cloud client isn't ready, returns None. The entity is
    `entity_registry_enabled_default=False`, so HA's auto-disable on
    None doesn't bite — the user explicitly enables it if they want it."""
    coord = MagicMock()
    coord._cloud = None
    assert _cloud_device_id_descriptor().value_fn(coord) is None


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
