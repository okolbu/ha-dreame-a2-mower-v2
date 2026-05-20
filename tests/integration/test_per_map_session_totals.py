"""Per-map session totals aggregation.

Step 0 findings:
  - Archive object lives at coordinator.session_archive (not _session_archive).
  - In-memory index: coordinator.session_archive._index (list[ArchivedSession]).
  - ArchivedSession fields: map_id (int, -1 = unknown), area_mowed_m2 (float),
    duration_min (int).
  - Sensors read _index directly (sync); list_sessions() is executor-only.
"""
from unittest.mock import MagicMock


def _make_session(map_id, area_mowed_m2, duration_min):
    s = MagicMock()
    s.map_id = map_id
    s.area_mowed_m2 = area_mowed_m2
    s.duration_min = duration_min
    return s


def _make_coord_with_sessions():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    map0.name = "M0"
    map1 = MagicMock()
    map1.name = "M1"
    coord.cloud_state.maps_by_id = {0: map0, 1: map1}

    archive = MagicMock()
    archive._index = [
        _make_session(map_id=0, area_mowed_m2=100.0, duration_min=30),
        _make_session(map_id=0, area_mowed_m2=120.0, duration_min=40),
        _make_session(map_id=1, area_mowed_m2=200.0, duration_min=60),
        _make_session(map_id=-1, area_mowed_m2=50.0, duration_min=15),  # ignored
    ]
    coord.session_archive = archive
    return coord


def test_per_map_session_area_total():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionAreaTotalSensor,
    )
    coord = _make_coord_with_sessions()
    assert DreameA2MapSessionAreaTotalSensor(coord, map_id=0).native_value == 220.0
    assert DreameA2MapSessionAreaTotalSensor(coord, map_id=1).native_value == 200.0


def test_per_map_session_time_total():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionTimeTotalSensor,
    )
    coord = _make_coord_with_sessions()
    s = DreameA2MapSessionTimeTotalSensor(coord, map_id=0)
    assert s.native_value == 70


def test_per_map_session_count():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionCountSensor,
    )
    coord = _make_coord_with_sessions()
    assert DreameA2MapSessionCountSensor(coord, map_id=0).native_value == 2
    assert DreameA2MapSessionCountSensor(coord, map_id=1).native_value == 1


def test_per_map_totals_zero_when_no_sessions():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionAreaTotalSensor,
        DreameA2MapSessionCountSensor,
        DreameA2MapSessionTimeTotalSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord.cloud_state.maps_by_id = {0: MagicMock(name="M0")}
    archive = MagicMock()
    archive._index = []
    coord.session_archive = archive
    assert DreameA2MapSessionAreaTotalSensor(coord, map_id=0).native_value == 0
    assert DreameA2MapSessionTimeTotalSensor(coord, map_id=0).native_value == 0
    assert DreameA2MapSessionCountSensor(coord, map_id=0).native_value == 0


def test_per_map_session_sensors_unique_ids_differ():
    """Confirm each sensor class produces a distinct unique_id per map."""
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSessionAreaTotalSensor,
        DreameA2MapSessionTimeTotalSensor,
        DreameA2MapSessionCountSensor,
    )
    coord = _make_coord_with_sessions()
    uid_area = DreameA2MapSessionAreaTotalSensor(coord, map_id=0)._attr_unique_id
    uid_time = DreameA2MapSessionTimeTotalSensor(coord, map_id=0)._attr_unique_id
    uid_count = DreameA2MapSessionCountSensor(coord, map_id=0)._attr_unique_id
    assert uid_area != uid_time != uid_count
    assert uid_area is not None
