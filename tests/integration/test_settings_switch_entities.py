"""Tests for SETTINGS-driven switch entities + AI human detection switch.

T8: All 4 settings switches and 3 AI recognition bit-switches are now per-map.
They accept map_id= and read from cloud_state.settings.by_map_id_canonical.
"""
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

_MAP_ID = 0  # use map 0 for all legacy single-map tests


def _make_coord(*, ai_human=None, settings_by_map=None, **state_kwargs):
    """Create a minimal coordinator for testing.

    `settings_by_map` accepts a dict keyed by map_id with cloud-field-name dicts
    (e.g. {0: {"edgeMowingAuto": 1}}). When omitted, by_map_id_canonical is empty.
    """
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(**state_kwargs)
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = _MAP_ID
    coord._lifecycle_event = None
    coord._alert_event = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=[],
            by_map_id_canonical=settings_by_map or {},
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=ai_human,
        forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={},
        mapl=None, mihis={}, fetched_at_unix=0,
    )
    return coord


def test_edge_mowing_auto_is_on():
    coord = _make_coord(settings_by_map={_MAP_ID: {"edgeMowingAuto": 1}})
    ent = DreameA2EdgeMowingAutoSwitch(coord, map_id=_MAP_ID)
    assert ent.is_on is True


def test_edge_mowing_safe_is_off():
    coord = _make_coord(settings_by_map={_MAP_ID: {"edgeMowingSafe": 0}})
    ent = DreameA2EdgeMowingSafeSwitch(coord, map_id=_MAP_ID)
    assert ent.is_on is False


def test_edge_mowing_obstacle_avoidance_is_on():
    coord = _make_coord(settings_by_map={_MAP_ID: {"edgeMowingObstacleAvoidance": 1}})
    ent = DreameA2EdgeMowingObstacleAvoidanceSwitch(coord, map_id=_MAP_ID)
    assert ent.is_on is True


def test_obstacle_avoidance_enabled_is_on():
    coord = _make_coord(settings_by_map={_MAP_ID: {"obstacleAvoidanceEnabled": 1}})
    ent = DreameA2ObstacleAvoidanceEnabledSwitch(coord, map_id=_MAP_ID)
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


def test_ai_recognition_humans_switch_reads_bit0():
    """obstacleAvoidanceAi & 0x01 → switch.ai_recognition_humans is_on."""
    from custom_components.dreame_a2_mower.switch import (
        DreameA2AiRecognitionHumansSwitch,
    )
    coord = _make_coord(settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b001}})
    ent = DreameA2AiRecognitionHumansSwitch(coord, map_id=_MAP_ID)
    assert ent.is_on is True


def test_ai_recognition_animals_switch_reads_bit1():
    from custom_components.dreame_a2_mower.switch import (
        DreameA2AiRecognitionAnimalsSwitch,
    )
    coord = _make_coord(settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b010}})
    ent = DreameA2AiRecognitionAnimalsSwitch(coord, map_id=_MAP_ID)
    assert ent.is_on is True


def test_ai_recognition_objects_switch_reads_bit2():
    from custom_components.dreame_a2_mower.switch import (
        DreameA2AiRecognitionObjectsSwitch,
    )
    coord = _make_coord(settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b100}})
    ent = DreameA2AiRecognitionObjectsSwitch(coord, map_id=_MAP_ID)
    assert ent.is_on is True


def test_ai_recognition_humans_off_when_bit_clear():
    from custom_components.dreame_a2_mower.switch import (
        DreameA2AiRecognitionHumansSwitch,
    )
    coord = _make_coord(settings_by_map={_MAP_ID: {"obstacleAvoidanceAi": 0b110}})
    ent = DreameA2AiRecognitionHumansSwitch(coord, map_id=_MAP_ID)
    assert ent.is_on is False
