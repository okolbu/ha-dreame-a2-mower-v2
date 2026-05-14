"""Tests for per-map SETTINGS-driven select entities (v1.0.10a7).

Replaces the prior mower-scoped active-map-follower tests — the 3 SETTINGS
selects (mowingDirection, mowingDirectionMode, edgeMowingWalkMode) now live
on map sub-devices, one entity per map, reading from
``cloud_state.settings.by_map_id_canonical``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.const import DOMAIN


@pytest.mark.parametrize("cls_name,key", [
    ("DreameA2PerMapMowingDirectionSelect", "settings_mowing_direction"),
    ("DreameA2PerMapMowingDirectionModeSelect", "settings_mowing_direction_mode"),
    ("DreameA2PerMapEdgeMowingWalkModeSelect", "settings_edge_mowing_walk_mode"),
])
def test_per_map_settings_select_unique_id_and_device(
    coordinator_with_two_maps, cls_name, key
):
    coord = coordinator_with_two_maps
    import custom_components.dreame_a2_mower.select as select_mod
    cls = getattr(select_mod, cls_name)

    e0 = cls(coord, map_id=0)
    e1 = cls(coord, map_id=1)

    assert e0._attr_unique_id == f"G2408053AEE0006232_map_0_{key}"
    assert e1._attr_unique_id == f"G2408053AEE0006232_map_1_{key}"
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_per_map_mowing_direction_reads_correct_map(coordinator_with_two_maps):
    """Per-map MowingDirection picks the option corresponding to its map_id."""
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {"mowingDirection": 0},
        1: {"mowingDirection": 180},
    }
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    e0 = select_mod.DreameA2PerMapMowingDirectionSelect(coord, map_id=0)
    e1 = select_mod.DreameA2PerMapMowingDirectionSelect(coord, map_id=1)
    assert e0.current_option == "0°"
    assert e1.current_option == "180°"


def test_per_map_mowing_pattern_reads_correct_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {"mowingDirectionMode": 0},
        1: {"mowingDirectionMode": 2},
    }
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    e0 = select_mod.DreameA2PerMapMowingDirectionModeSelect(coord, map_id=0)
    e1 = select_mod.DreameA2PerMapMowingDirectionModeSelect(coord, map_id=1)
    assert e0.current_option == "Striped"
    assert e1.current_option == "Chequerboard"


def test_per_map_edge_walk_mode_reads_correct_map(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {"edgeMowingWalkMode": 0},
        1: {"edgeMowingWalkMode": 1},
    }
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.select as select_mod
    e0 = select_mod.DreameA2PerMapEdgeMowingWalkModeSelect(coord, map_id=0)
    e1 = select_mod.DreameA2PerMapEdgeMowingWalkModeSelect(coord, map_id=1)
    assert e0.current_option == "walk_0"
    assert e1.current_option == "walk_1"
