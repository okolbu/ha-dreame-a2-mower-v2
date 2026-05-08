"""Tests for SETTINGS-driven number entities (active-follower pattern)."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_state import (
    CloudState, ScheduleData, SettingsRoot,
)
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import (
    DreameA2MowingHeightNumber,
)
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker, NovelObservationRegistry,
)


def _make_coord_with_cloud_state(*, active_map_id: int = 0):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(settings_mowing_height=5)
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._cached_maps_by_id = {}
    coord._cached_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = active_map_id
    coord._render_map_id = None
    coord._lifecycle_event = None
    coord._alert_event = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.cloud_state = CloudState(
        cfg={}, maps_by_id={}, mow_paths_by_map_id={},
        settings=SettingsRoot(
            raw=[{"mode": 0, "settings": {"0": {"mowingHeight": 5}, "1": {"mowingHeight": 7}}}],
            by_map_id_canonical={
                0: {"mowingHeight": 5},
                1: {"mowingHeight": 7},
            },
        ),
        schedule=ScheduleData(version=0, slots=()),
        ai_human_enabled=None, forbidden_node_types_by_map={},
        ota_status=None, task_id=0, props={},
        locn=None, dock={}, mapl=None, mihis={}, fetched_at_unix=0,
    )
    return coord


def test_mowing_height_reads_from_active_map_state():
    coord = _make_coord_with_cloud_state(active_map_id=0)
    ent = DreameA2MowingHeightNumber(coord)
    assert ent.native_value == 5


def test_mowing_height_changes_when_active_map_changes():
    coord = _make_coord_with_cloud_state(active_map_id=0)
    ent = DreameA2MowingHeightNumber(coord)
    coord._active_map_id = 1
    coord.data = MowerState(settings_mowing_height=7)
    assert ent.native_value == 7


def test_mowing_height_returns_none_when_no_cloud_state():
    coord = _make_coord_with_cloud_state(active_map_id=0)
    coord.data = MowerState()  # field unset
    ent = DreameA2MowingHeightNumber(coord)
    assert ent.native_value is None
