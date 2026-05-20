"""Per-map name / area / segment-count sensors."""
from unittest.mock import MagicMock


def _make_coord_with_two_maps():
    coord = MagicMock()
    coord.entry.entry_id = "fake"

    map0 = MagicMock()
    map0.name = "Front lawn"
    map0.total_area_m2 = 240.5
    map0.mowing_zones = (MagicMock(), MagicMock(), MagicMock())
    map1 = MagicMock()
    map1.name = "Back garden"
    map1.total_area_m2 = 410.0
    map1.mowing_zones = (MagicMock(),)

    coord.cloud_state.maps_by_id = {0: map0, 1: map1}
    coord.data = MagicMock()
    return coord


def test_map_name_sensor_per_map():
    from custom_components.dreame_a2_mower.sensor import DreameA2MapNameSensor
    coord = _make_coord_with_two_maps()
    assert DreameA2MapNameSensor(coord, map_id=0).native_value == "Front lawn"
    assert DreameA2MapNameSensor(coord, map_id=1).native_value == "Back garden"


def test_map_area_sensor_per_map():
    from custom_components.dreame_a2_mower.sensor import DreameA2MapAreaSensor
    coord = _make_coord_with_two_maps()
    s0 = DreameA2MapAreaSensor(coord, map_id=0)
    s1 = DreameA2MapAreaSensor(coord, map_id=1)
    assert s0.native_value == 240.5
    assert s1.native_value == 410.0
    assert s0._attr_native_unit_of_measurement == "m²"


def test_map_segment_count_sensor_per_map():
    from custom_components.dreame_a2_mower.sensor import DreameA2MapSegmentCountSensor
    coord = _make_coord_with_two_maps()
    assert DreameA2MapSegmentCountSensor(coord, map_id=0).native_value == 3
    assert DreameA2MapSegmentCountSensor(coord, map_id=1).native_value == 1


def test_sensors_returns_none_when_map_absent():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapNameSensor,
        DreameA2MapAreaSensor,
        DreameA2MapSegmentCountSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord.cloud_state.maps_by_id = {}
    for cls in (DreameA2MapNameSensor, DreameA2MapAreaSensor, DreameA2MapSegmentCountSensor):
        assert cls(coord, map_id=0).native_value is None


def test_sensors_attached_to_map_subdevice():
    from custom_components.dreame_a2_mower.sensor import DreameA2MapNameSensor
    coord = _make_coord_with_two_maps()
    s = DreameA2MapNameSensor(coord, map_id=0)
    info = s._attr_device_info
    ident = list(info["identifiers"])[0]
    assert ident[1].endswith("_map_0")
