"""Per-map maintenance-point select: options, per-map (map_id, point_id) store."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.const import DOMAIN
from custom_components.dreame_a2_mower.mower.state import MowerState


def _points(*ids):
    out = []
    for i in ids:
        p = MagicMock(); p.point_id = i; p.x_mm = 0.0; p.y_mm = 0.0
        out.append(p)
    return tuple(out)


def _setup(coord):
    coord.cloud_state.maps_by_id[0].maintenance_points = _points(1, 5)
    coord.cloud_state.maps_by_id[1].maintenance_points = ()
    coord.data = MowerState()


def test_options_are_point_labels_plus_placeholder(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    e0 = DreameA2MaintenancePointSelect(coord, map_id=0)
    assert e0.options == ["(no point selected)", "Point 1", "Point 5"]


def test_empty_map_shows_no_points_placeholder(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    e1 = DreameA2MaintenancePointSelect(coord, map_id=1)
    assert e1.options == ["(no points on this map)"]


def test_unique_id_and_device_are_per_map(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    e0 = DreameA2MaintenancePointSelect(coord, map_id=0)
    assert e0._attr_unique_id == "G2408053AEE0006232_map_0_maintenance_point"
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


async def test_select_stores_map_scoped_pick(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    e0 = DreameA2MaintenancePointSelect(coord, map_id=0)
    await e0.async_select_option("Point 5")
    new_state = coord.async_set_updated_data.call_args.args[0]
    assert new_state.active_selection_point == (0, 5)


def test_current_option_is_map_scoped(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.select import (
        DreameA2MaintenancePointSelect,
    )
    coord = coordinator_with_two_maps
    _setup(coord)
    coord.data = MowerState(active_selection_point=(0, 1))
    e0 = DreameA2MaintenancePointSelect(coord, map_id=0)
    e1 = DreameA2MaintenancePointSelect(coord, map_id=1)
    assert e0.current_option == "Point 1"
    assert e1.current_option == "(no points on this map)"
