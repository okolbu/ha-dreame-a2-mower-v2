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


def test_sync_tolerates_3_tuple_identifiers_from_other_integrations(
    coordinator_with_two_maps,
):
    """Some integrations store 3-tuple identifiers; iteration must not crash.

    Real bug: a HA install had a device registered by some other integration
    with a 3-tuple identifier (e.g. (domain, type, id)), and the rigid
    `for domain, ident in dev.identifiers` unpacking raised
    ValueError: too many values to unpack (expected 2, got 3).
    """
    coord = coordinator_with_two_maps
    with patch.object(coord, "_get_device_registry") as mock_reg:
        registry = MagicMock()
        # An unrelated 3-tuple device that should be silently ignored.
        weird = MagicMock()
        weird.identifiers = {("other_integration", "type_x", "id_42")}
        weird.id = "dev_other"
        # Plus a normal 2-tuple device for our domain that should sync.
        ours = MagicMock()
        ours.identifiers = {(DOMAIN, "G2408053AEE0006232_map_99")}  # not in wanted
        ours.id = "dev_ours"
        registry.devices.values.return_value = [weird, ours]
        mock_reg.return_value = registry
        # Must NOT raise.
        coord._sync_map_subdevices()

    # The unrelated device was never touched.
    calls_to_remove = [
        c.args[0] for c in registry.async_remove_device.call_args_list
    ]
    assert "dev_other" not in calls_to_remove
    # Our orphan was removed normally.
    assert "dev_ours" in calls_to_remove


def test_coord_sn_falls_back_to_data_hardware_serial():
    """Real-world scenario: cloud `_handle_device_info` doesn't see `sn`
    in the device-info response (`get_devices()` payload omits it on g2408),
    but `_refresh_dev` fetches it via routed-action s2.50 t='DEV' and
    stashes it on `coord.data.hardware_serial`. The `sn` property must
    pick that up so migration can run on the next setup pass.
    """
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.coordinator import (
        DreameA2MowerCoordinator,
    )

    # Build a synthetic coordinator using the real `sn` property on a
    # plain object stub.
    coord = MagicMock(spec=DreameA2MowerCoordinator)
    cloud = MagicMock()
    cloud.serial_number = None  # Cloud info path failed to capture SN.
    coord._cloud = cloud
    state = MagicMock()
    state.hardware_serial = "G2408053AEE0006232"
    coord.data = state
    # Real sn property bound to the stub.
    coord.sn = DreameA2MowerCoordinator.sn.fget(coord)
    assert coord.sn == "G2408053AEE0006232"


def test_coord_sn_prefers_cloud_serial_number_over_data():
    """When both sources have a value, the cloud-side SN wins (it's the
    earlier/more specific source from the device-info call).
    """
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.coordinator import (
        DreameA2MowerCoordinator,
    )

    coord = MagicMock(spec=DreameA2MowerCoordinator)
    cloud = MagicMock()
    cloud.serial_number = "FROM_CLOUD"
    coord._cloud = cloud
    state = MagicMock()
    state.hardware_serial = "FROM_DEV"
    coord.data = state
    coord.sn = DreameA2MowerCoordinator.sn.fget(coord)
    assert coord.sn == "FROM_CLOUD"
