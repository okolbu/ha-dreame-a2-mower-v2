"""Tests for _active_map_id derivation from cfg_individual.MAPL."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)


def _make_coord():
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    coord._cached_maps_by_id = {}
    coord._cached_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = None
    coord._render_map_id = None
    coord._lifecycle_event = None
    coord._alert_event = None
    return coord


def test_apply_mapl_single_active_row():
    coord = _make_coord()
    # MAPL with map_id=0 active.
    coord._apply_mapl([[0, 1, 1, 1, 0]])
    assert coord._active_map_id == 0


def test_apply_mapl_two_rows_second_active():
    coord = _make_coord()
    coord._apply_mapl([[0, 0, 1, 1, 0], [1, 1, 1, 1, 0]])
    assert coord._active_map_id == 1


def test_apply_mapl_no_active_row_keeps_previous():
    coord = _make_coord()
    coord._active_map_id = 0
    # No row with col 1 == 1 (transient state).
    coord._apply_mapl([[0, 0, 1, 1, 0], [1, 0, 1, 1, 0]])
    assert coord._active_map_id == 0


def test_apply_mapl_invalid_payload_no_change():
    coord = _make_coord()
    coord._active_map_id = 0
    coord._apply_mapl("not-a-list")
    assert coord._active_map_id == 0
