"""Active-map select uses SN-based unique_id on the mower device."""
from custom_components.dreame_a2_mower.const import DOMAIN


def test_active_map_select_unique_id_uses_sn(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ActiveMapSelect

    e = DreameA2ActiveMapSelect(coord)
    assert e._attr_unique_id == "G2408053AEE0006232_active_map"
    assert e._attr_device_info["identifiers"] == {(DOMAIN, "G2408053AEE0006232")}
