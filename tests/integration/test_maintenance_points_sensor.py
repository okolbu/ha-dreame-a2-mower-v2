"""Per-map maintenance-points sensor (read-only)."""
from unittest.mock import MagicMock


def _make_coord_with_points():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    map0.name = "Front lawn"
    p1 = MagicMock(); p1.point_id = 1; p1.x_mm = 2820.0; p1.y_mm = 12760.0
    p2 = MagicMock(); p2.point_id = 5; p2.x_mm = 1500.0; p2.y_mm = 800.0
    map0.maintenance_points = (p1, p2)
    coord._cached_maps_by_id = {0: map0}
    coord.cloud_state.maps_by_id = coord._cached_maps_by_id
    coord.data = MagicMock()
    return coord


def test_maintenance_points_count_is_state():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MaintenancePointsSensor,
    )
    coord = _make_coord_with_points()
    sensor = DreameA2MaintenancePointsSensor(coord, map_id=0)
    assert sensor.native_value == 2


def test_maintenance_points_list_in_attributes():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MaintenancePointsSensor,
    )
    coord = _make_coord_with_points()
    sensor = DreameA2MaintenancePointsSensor(coord, map_id=0)
    attrs = sensor.extra_state_attributes
    assert "points" in attrs
    assert attrs["points"] == [
        {"id": 1, "x_mm": 2820.0, "y_mm": 12760.0},
        {"id": 5, "x_mm": 1500.0, "y_mm": 800.0},
    ]


def test_maintenance_points_empty_list_when_no_points():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MaintenancePointsSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    map0.name = "Empty"
    map0.maintenance_points = ()
    coord._cached_maps_by_id = {0: map0}
    coord.cloud_state.maps_by_id = coord._cached_maps_by_id
    sensor = DreameA2MaintenancePointsSensor(coord, map_id=0)
    assert sensor.native_value == 0
    assert sensor.extra_state_attributes["points"] == []


def test_maintenance_points_returns_zero_when_map_absent():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MaintenancePointsSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._cached_maps_by_id = {}
    coord.cloud_state.maps_by_id = coord._cached_maps_by_id
    sensor = DreameA2MaintenancePointsSensor(coord, map_id=0)
    # Per base class contract, native_value is None when map is absent.
    assert sensor.native_value is None
    # extra_state_attributes should be defensive too.
    assert sensor.extra_state_attributes.get("points") == []
