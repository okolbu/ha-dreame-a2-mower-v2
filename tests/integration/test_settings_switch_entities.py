"""Tests for SETTINGS-driven switch entities + AI human detection switch."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState, ScheduleData, SettingsRoot,
)
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker, NovelObservationRegistry,
)
from custom_components.dreame_a2_mower.switch import (
    DreameA2EdgeMowingAutoSwitch,
    DreameA2EdgeMowingSafeSwitch,
    DreameA2EdgeMowingObstacleAvoidanceSwitch,
    DreameA2ObstacleAvoidanceEnabledSwitch,
    DreameA2AiHumanDetectionSwitch,
)


def _make_coord(*, ai_human=None, **state_kwargs):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(**state_kwargs)
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._cached_maps_by_id = {}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._lifecycle_event = None
    coord._alert_event = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(raw=[], by_map_id_canonical={}),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=ai_human,
        forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={},
        locn=None, dock={}, mapl=None, mihis={}, fetched_at_unix=0,
    )
    return coord


def test_edge_mowing_auto_is_on():
    coord = _make_coord(settings_edge_mowing_auto=True)
    ent = DreameA2EdgeMowingAutoSwitch(coord)
    assert ent.is_on is True


def test_edge_mowing_safe_is_off():
    coord = _make_coord(settings_edge_mowing_safe=False)
    ent = DreameA2EdgeMowingSafeSwitch(coord)
    assert ent.is_on is False


def test_edge_mowing_obstacle_avoidance_is_on():
    coord = _make_coord(settings_edge_mowing_obstacle_avoidance=True)
    ent = DreameA2EdgeMowingObstacleAvoidanceSwitch(coord)
    assert ent.is_on is True


def test_obstacle_avoidance_enabled_is_on():
    coord = _make_coord(settings_obstacle_avoidance_enabled=True)
    ent = DreameA2ObstacleAvoidanceEnabledSwitch(coord)
    assert ent.is_on is True


def test_ai_human_detection_reads_from_cloud_state():
    coord = _make_coord(ai_human=True)
    ent = DreameA2AiHumanDetectionSwitch(coord)
    assert ent.is_on is True


def test_ai_human_detection_returns_none_without_cloud_state():
    coord = _make_coord(ai_human=None)
    coord.cloud_state = None
    ent = DreameA2AiHumanDetectionSwitch(coord)
    assert ent.is_on is None
