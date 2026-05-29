"""Tests for cloud_state-driven sensor entities (OTA, schedule count)."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState, ScheduleData, SchedulePlan, ScheduleSlot, SettingsRoot,
)
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker, NovelObservationRegistry,
)
from custom_components.dreame_a2_mower.sensor import (
    DreameA2OtaStatusSensor,
    DreameA2ScheduleCountSensor,
)


def _make_coord(*, ota_status=None, schedule=None):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._lifecycle_event = None
    coord._notification_event = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=schedule or ScheduleData(version=0, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=ota_status,
        task_id=0, props={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    return coord


def test_ota_status_returns_status_int():
    coord = _make_coord(ota_status=(2, 100))
    ent = DreameA2OtaStatusSensor(coord)
    assert ent.native_value == 2
    assert ent.extra_state_attributes == {"percent": 100}


def test_ota_status_returns_none_when_unset():
    coord = _make_coord(ota_status=None)
    ent = DreameA2OtaStatusSensor(coord)
    assert ent.native_value is None
    assert ent.extra_state_attributes == {}


def test_schedule_count_two_slots():
    sched = ScheduleData(
        version=657,
        slots=(
            ScheduleSlot(
                slot_id=0,
                name="Spring & Summer",
                raw_blob_b64="xxx",
                plans=(
                    # 07:58 All-area on Mon+Wed
                    SchedulePlan(
                        time_min=7 * 60 + 58,
                        weekday_mask=(1 << 0) | (1 << 2),
                        action_type=0,
                    ),
                ),
            ),
            ScheduleSlot(slot_id=1, name="", raw_blob_b64="yyy"),
        ),
    )
    coord = _make_coord(schedule=sched)
    ent = DreameA2ScheduleCountSensor(coord)
    assert ent.native_value == 2
    attrs = ent.extra_state_attributes
    assert attrs["version"] == 657
    assert len(attrs["slots"]) == 2
    assert attrs["slots"][0]["slot_id"] == 0
    assert attrs["slots"][0]["name"] == "Spring & Summer"
    assert attrs["slots"][0]["plans"] == [
        {"time": "07:58", "days": ["Mon", "Wed"], "action": "all_area", "zone_id": None},
    ]
    # Slot 1 has no plans → empty list
    assert attrs["slots"][1]["plans"] == []


def test_schedule_count_zero_when_empty():
    coord = _make_coord()  # default empty ScheduleData
    ent = DreameA2ScheduleCountSensor(coord)
    assert ent.native_value == 0
    assert ent.extra_state_attributes == {"slots": [], "version": 0}


def test_schedule_count_unknown_action_type_passes_through():
    """An action_type code we haven't catalogued shows as 'unknown_<n>'."""
    sched = ScheduleData(
        version=1,
        slots=(
            ScheduleSlot(
                slot_id=0, name="Mixed", raw_blob_b64="z",
                plans=(SchedulePlan(time_min=540, weekday_mask=1 << 0, action_type=2),),
            ),
        ),
    )
    coord = _make_coord(schedule=sched)
    ent = DreameA2ScheduleCountSensor(coord)
    assert ent.extra_state_attributes["slots"][0]["plans"][0]["action"] == "edge"


def test_schedule_count_surfaces_zone_id_and_action_label():
    """sensor.schedule_count attrs include zone_id + action label per plan."""
    sched = ScheduleData(
        version=1,
        slots=(
            ScheduleSlot(
                slot_id=0, name="A", raw_blob_b64="z",
                plans=(
                    SchedulePlan(time_min=16*60, weekday_mask=1<<2,
                                 action_type=1, zone_id=1),
                ),
            ),
        ),
    )
    coord = _make_coord(schedule=sched)
    ent = DreameA2ScheduleCountSensor(coord)
    plans = ent.extra_state_attributes["slots"][0]["plans"]
    assert plans[0]["action"] == "zone"
    assert plans[0]["zone_id"] == 1
    assert plans[0]["time"] == "16:00"
    assert plans[0]["days"] == ["Wed"]
