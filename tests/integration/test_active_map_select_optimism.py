"""Tests for the optimistic UI in select.active_map."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.select import DreameA2ActiveMapSelect


def _make_select():
    coord = MagicMock()
    coord._cached_maps_by_id = {0: MagicMock(name=None), 1: MagicMock(name=None)}
    # MagicMock instances pretend to have any attribute including 'name', but
    # we want the static fallback Map N+1 path. Easiest: set name explicitly.
    for m_id, m in coord._cached_maps_by_id.items():
        m.name = None  # forces _label_for to use "Map N+1"
    coord.cloud_state.maps_by_id = coord._cached_maps_by_id
    coord._active_map_id = 0
    coord.entry.entry_id = "test_entry"

    # Use __new__ to skip the HA-dependent __init__ (CoordinatorEntity parent
    # touches DeviceInfo + HA registries), matching the pattern used by
    # test_edge_select.py and other integration tests in this suite.
    sel = DreameA2ActiveMapSelect.__new__(DreameA2ActiveMapSelect)
    sel.coordinator = coord
    sel._optimistic_target_map_id = None
    return sel, coord


def test_current_option_returns_active_when_no_optimistic():
    sel, coord = _make_select()
    assert sel.current_option == "Map 1"  # map_id=0 → "Map 1"


def test_current_option_returns_optimistic_when_set():
    sel, coord = _make_select()
    sel._optimistic_target_map_id = 1
    assert sel.current_option == "Map 2"  # optimistic wins


def test_handle_coordinator_update_clears_optimistic_on_match():
    sel, coord = _make_select()
    sel._optimistic_target_map_id = 1
    coord._active_map_id = 1  # firmware caught up
    # Suppress the parent-class state-write; the stub CoordinatorEntity has
    # no _handle_coordinator_update of its own so super() is effectively a
    # no-op in the test environment.
    sel.async_write_ha_state = MagicMock()
    sel._handle_coordinator_update()
    assert sel._optimistic_target_map_id is None


def test_handle_coordinator_update_keeps_optimistic_when_unmatched():
    sel, coord = _make_select()
    sel._optimistic_target_map_id = 1
    coord._active_map_id = 0  # firmware not yet caught up
    sel.async_write_ha_state = MagicMock()
    sel._handle_coordinator_update()
    assert sel._optimistic_target_map_id == 1
