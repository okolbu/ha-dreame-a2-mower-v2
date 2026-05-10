"""Coordinator syncs HA devices to match _cached_maps_by_id."""
from unittest.mock import MagicMock, patch

from custom_components.dreame_a2_mower.const import DOMAIN


def test_sync_creates_subdevice_per_map_id(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    with patch.object(coord, "_get_device_registry") as mock_reg:
        registry = MagicMock()
        registry.devices.values.return_value = []  # nothing pre-existing
        mock_reg.return_value = registry
        coord._sync_map_subdevices()

    calls = registry.async_get_or_create.call_args_list
    identifiers = [c.kwargs["identifiers"] for c in calls]
    assert {(DOMAIN, "G2408053AEE0006232_map_0")} in identifiers
    assert {(DOMAIN, "G2408053AEE0006232_map_1")} in identifiers


def test_sync_removes_subdevice_for_dropped_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    coord._cached_maps_by_id = {0: coord._cached_maps_by_id[0]}  # drop map 1
    with patch.object(coord, "_get_device_registry") as mock_reg:
        registry = MagicMock()
        # Pretend map_1 is registered.
        existing = MagicMock()
        existing.identifiers = {(DOMAIN, "G2408053AEE0006232_map_1")}
        existing.id = "dev_map_1"
        registry.devices.values.return_value = [existing]
        mock_reg.return_value = registry
        coord._sync_map_subdevices()

    registry.async_remove_device.assert_called_with("dev_map_1")
