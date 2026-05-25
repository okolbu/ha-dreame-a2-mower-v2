"""Smoke tests for CloudState + sub-dataclass instantiation."""
from __future__ import annotations

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState,
    MowPathData,
    ScheduleData,
    ScheduleSlot,
    SettingsRoot,
)


def test_cloud_state_constructs_with_minimal_args():
    cs = CloudState(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )
    assert cs.fetched_at_unix == 0
    assert cs.task_id == 0


def test_cloud_state_is_frozen():
    cs = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    import dataclasses
    try:
        cs.task_id = 42  # should raise
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("CloudState should be frozen")


def test_mow_path_data_segments_is_tuple_of_tuples():
    mp = MowPathData(map_id=1, segments=(((100, 200), (300, 400)),))
    assert mp.map_id == 1
    assert mp.segments == (((100, 200), (300, 400)),)


def test_schedule_slot_fields():
    s = ScheduleSlot(slot_id=0, name="Spring", raw_blob_b64="qgcQ3gEA")
    assert s.slot_id == 0
    assert s.name == "Spring"
    assert s.raw_blob_b64 == "qgcQ3gEA"
