"""Active-map select uses SN-based unique_id on the mower device."""
from custom_components.dreame_a2_mower.const import DOMAIN


def test_active_map_select_unique_id_uses_sn(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ActiveMapSelect

    e = DreameA2ActiveMapSelect(coord)
    assert e._attr_unique_id == "G2408053AEE0006232_active_map"
    assert e._attr_device_info["identifiers"] == {(DOMAIN, "G2408053AEE0006232")}


def test_active_map_select_exposes_current_map_id_attribute(
    coordinator_with_two_maps,
):
    """Dashboard `conditional` cards key off attributes.current_map_id.

    The select's state is the user-renameable friendly name; the
    attribute is a stable integer that survives renames.
    """
    coord = coordinator_with_two_maps
    coord._active_map_id = 1

    from custom_components.dreame_a2_mower.select import (
        DreameA2ActiveMapSelect,
    )
    e = DreameA2ActiveMapSelect(coord)
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] == 1

    coord._active_map_id = 0
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] == 0

    coord._active_map_id = None
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] is None
