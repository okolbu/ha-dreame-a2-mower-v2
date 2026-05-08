"""Integration test: active-map switch rebinds all SETTINGS entities."""
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


# Map 0: distinct values for all 15 SETTINGS fields.
MAP_0_SETTINGS = {
    "mowingHeight": 5,
    "mowingDirection": 0,
    "mowingDirectionMode": 0,
    "cutterPosition": 1,
    "cutterPositionHeight": 3,
    "edgeMowingNum": 2,
    "edgeMowingAuto": 1,
    "edgeMowingSafe": 1,
    "edgeMowingObstacleAvoidance": 1,
    "edgeMowingWalkMode": 0,
    "obstacleAvoidanceEnabled": 1,
    "obstacleAvoidanceHeight": 20,
    "obstacleAvoidanceDistance": 15,
    "obstacleAvoidanceSensitivity": 2,
    "obstacleAvoidanceAi": 7,
}

# Map 1: every value DIFFERENT from Map 0 to verify rebind.
MAP_1_SETTINGS = {
    "mowingHeight": 7,
    "mowingDirection": 180,
    "mowingDirectionMode": 1,
    "cutterPosition": 2,
    "cutterPositionHeight": 5,
    "edgeMowingNum": 1,
    "edgeMowingAuto": 0,
    "edgeMowingSafe": 0,
    "edgeMowingObstacleAvoidance": 0,
    "edgeMowingWalkMode": 1,
    "obstacleAvoidanceEnabled": 0,
    "obstacleAvoidanceHeight": 30,
    "obstacleAvoidanceDistance": 25,
    "obstacleAvoidanceSensitivity": 3,
    "obstacleAvoidanceAi": 15,
}


# Maps cloud field name → MowerState field name (used by both
# _apply_cloud_state_to_mower_state and this test).
FIELD_MAP = {
    "mowingHeight": ("settings_mowing_height", int),
    "mowingDirection": ("settings_mowing_direction", int),
    "mowingDirectionMode": ("settings_mowing_direction_mode", int),
    "cutterPosition": ("settings_cutter_position", int),
    "cutterPositionHeight": ("settings_cutter_position_height", int),
    "edgeMowingNum": ("settings_edge_mowing_num", int),
    "edgeMowingWalkMode": ("settings_edge_mowing_walk_mode", int),
    "obstacleAvoidanceHeight": ("settings_obstacle_avoidance_height", int),
    "obstacleAvoidanceDistance": ("settings_obstacle_avoidance_distance", int),
    "obstacleAvoidanceSensitivity": ("settings_obstacle_avoidance_sensitivity", int),
    "obstacleAvoidanceAi": ("settings_obstacle_avoidance_ai", int),
    "edgeMowingAuto": ("settings_edge_mowing_auto", bool),
    "edgeMowingSafe": ("settings_edge_mowing_safe", bool),
    "edgeMowingObstacleAvoidance": ("settings_edge_mowing_obstacle_avoidance", bool),
    "obstacleAvoidanceEnabled": ("settings_obstacle_avoidance_enabled", bool),
}


def _expected(cloud_settings: dict[str, int]) -> dict[str, int | bool]:
    """Convert a cloud-side settings dict into expected MowerState field values."""
    out: dict[str, int | bool] = {}
    for cloud_key, (state_field, conv) in FIELD_MAP.items():
        out[state_field] = conv(cloud_settings[cloud_key])
    return out


def _make_coord_with_two_maps(active_map_id: int = 0) -> DreameA2MowerCoordinator:
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._cached_maps_by_id = {}
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = active_map_id
    coord._lifecycle_event = None
    coord._alert_event = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={},
        maps_by_id={},
        mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=[
                {
                    "mode": 0,
                    "settings": {
                        "0": MAP_0_SETTINGS,
                        "1": MAP_1_SETTINGS,
                    },
                }
            ],
            by_map_id_canonical={
                0: MAP_0_SETTINGS,
                1: MAP_1_SETTINGS,
            },
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None,
        forbidden_node_types_by_map={},
        ota_status=None,
        task_id=0,
        props={},
        locn=None,
        dock={},
        mapl=None,
        mihis={},
        fetched_at_unix=0,
    )

    # _apply_cloud_state_to_mower_state calls async_set_updated_data, which
    # depends on HA-runtime listener machinery we don't have in unit tests.
    # Replace it with a simple data-replacer.
    def _set(new_state):
        coord.data = new_state

    coord.async_set_updated_data = _set
    return coord


def test_apply_settings_for_active_map_0():
    coord = _make_coord_with_two_maps(active_map_id=0)
    coord._apply_cloud_state_to_mower_state()
    expected = _expected(MAP_0_SETTINGS)
    for field, value in expected.items():
        actual = getattr(coord.data, field)
        assert actual == value, f"Map 0: {field} = {actual!r}, expected {value!r}"


def test_apply_settings_for_active_map_1():
    coord = _make_coord_with_two_maps(active_map_id=1)
    coord._apply_cloud_state_to_mower_state()
    expected = _expected(MAP_1_SETTINGS)
    for field, value in expected.items():
        actual = getattr(coord.data, field)
        assert actual == value, f"Map 1: {field} = {actual!r}, expected {value!r}"


def test_active_map_switch_rebinds_all_settings():
    """Switch active_map_id mid-flight; verify all 15 fields rebind."""
    coord = _make_coord_with_two_maps(active_map_id=0)
    coord._apply_cloud_state_to_mower_state()
    # Capture map 0 state to confirm rebind actually changes things.
    before = {f: getattr(coord.data, f) for f, _ in FIELD_MAP.values()}
    expected_before = _expected(MAP_0_SETTINGS)
    assert before == expected_before

    # Now switch.
    coord._active_map_id = 1
    coord._apply_cloud_state_to_mower_state()

    expected_after = _expected(MAP_1_SETTINGS)
    after = {f: getattr(coord.data, f) for f, _ in FIELD_MAP.values()}
    assert after == expected_after
    # Sanity: at least one field actually differs between maps.
    assert before != after
