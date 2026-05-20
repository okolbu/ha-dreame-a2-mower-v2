"""Zone/spot/edge selects: one entity per map, on map sub-device."""
from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.const import DOMAIN


def test_zone_select_per_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ZoneSelect
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coord.data = MowerState()

    e0 = DreameA2ZoneSelect(coord, map_id=0)
    e1 = DreameA2ZoneSelect(coord, map_id=1)

    # Actual key is "zone_target" from _DreameA2DynamicTargetSelect.
    assert "G2408053AEE0006232_map_0_zone_target" == e0._attr_unique_id
    assert "G2408053AEE0006232_map_1_zone_target" == e1._attr_unique_id
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }
    assert e1._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_1")
    }


def test_spot_select_per_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2SpotSelect
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coord.data = MowerState()

    e0 = DreameA2SpotSelect(coord, map_id=0)

    # Actual key is "spot_target".
    assert "G2408053AEE0006232_map_0_spot_target" == e0._attr_unique_id
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_edge_select_per_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2EdgeSelect
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coord.data = MowerState()

    e0 = DreameA2EdgeSelect(coord, map_id=0)

    # Actual key is "edge_target".
    assert "G2408053AEE0006232_map_0_edge_target" == e0._attr_unique_id
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_zone_select_reads_own_map_data(coordinator_with_two_maps):
    """Each entity reads its own map's mowing_zones, not the active map."""
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ZoneSelect
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coord.data = MowerState()

    # Set up distinct zones on each map.
    z0 = MagicMock()
    z0.zone_id = 1
    z0.name = "Front Zone"
    z1 = MagicMock()
    z1.zone_id = 2
    z1.name = "Back Zone"

    coord.cloud_state.maps_by_id[0].mowing_zones = [z0]
    coord.cloud_state.maps_by_id[1].mowing_zones = [z1]

    e0 = DreameA2ZoneSelect(coord, map_id=0)
    e1 = DreameA2ZoneSelect(coord, map_id=1)

    entries0 = e0._entries()
    entries1 = e1._entries()

    assert entries0 == [(1, "Front Zone")]
    assert entries1 == [(2, "Back Zone")]


def test_edge_select_reads_own_map_data(coordinator_with_two_maps):
    """Edge select uses its own map_id, not active_map_id."""
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2EdgeSelect
    from custom_components.dreame_a2_mower.mower.state import MowerState

    coord.data = MowerState()

    coord.cloud_state.maps_by_id[0].available_contour_ids = ((1, 0),)
    coord.cloud_state.maps_by_id[1].available_contour_ids = ((2, 0),)

    e0 = DreameA2EdgeSelect(coord, map_id=0)
    e1 = DreameA2EdgeSelect(coord, map_id=1)

    outers0 = e0._outer_contour_ids()
    outers1 = e1._outer_contour_ids()

    assert outers0 == ((1, 0),)
    assert outers1 == ((2, 0),)
