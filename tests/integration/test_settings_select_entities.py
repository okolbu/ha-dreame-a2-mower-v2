"""Tests for SETTINGS-driven select entities."""
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
from custom_components.dreame_a2_mower.select import (
    DreameA2MowingDirectionSelect,
    DreameA2MowingDirectionModeSelect,
    DreameA2EdgeMowingWalkModeSelect,
)


def _make_coord(**state_kwargs):
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
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={},
        locn=None, dock={}, mapl=None, mihis={}, fetched_at_unix=0,
    )
    return coord


def test_mowing_direction_select_180():
    coord = _make_coord(settings_mowing_direction=180)
    ent = DreameA2MowingDirectionSelect(coord)
    assert ent.current_option == "180°"


def test_mowing_direction_mode_select():
    coord = _make_coord(settings_mowing_direction_mode=1)
    ent = DreameA2MowingDirectionModeSelect(coord)
    assert ent.current_option == "Crisscross"


def test_edge_walk_mode_select():
    coord = _make_coord(settings_edge_mowing_walk_mode=1)
    ent = DreameA2EdgeMowingWalkModeSelect(coord)
    assert ent.current_option == "walk_1"
