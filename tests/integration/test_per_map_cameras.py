"""Per-map cameras attached to their map sub-device."""
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
