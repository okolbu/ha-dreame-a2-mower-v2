"""Tests for per-map SETTINGS-driven number entities (v1.0.10a7).

Replaces the prior mower-scoped active-map-follower tests — the 7 SETTINGS
numbers (mowingHeight, cutterPosition, cutterPositionHeight, edgeMowingNum,
obstacleAvoidance{Height,Distance,Sensitivity}) now live on map sub-devices,
one entity per map, reading from cloud_state.settings.by_map_id_canonical.
"""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.const import DOMAIN


@pytest.mark.parametrize("cls_name,key,setting_field", [
    ("DreameA2PerMapMowingHeightNumber", "settings_mowing_height", "mowingHeight"),
    ("DreameA2PerMapCutterPositionNumber", "settings_cutter_position", "cutterPosition"),
    ("DreameA2PerMapCutterPositionHeightNumber", "settings_cutter_position_height", "cutterPositionHeight"),
    ("DreameA2PerMapEdgeMowingNumNumber", "settings_edge_mowing_num", "edgeMowingNum"),
    ("DreameA2PerMapObstacleAvoidanceHeightNumber", "settings_obstacle_avoidance_height", "obstacleAvoidanceHeight"),
    ("DreameA2PerMapObstacleAvoidanceDistanceNumber", "settings_obstacle_avoidance_distance", "obstacleAvoidanceDistance"),
    ("DreameA2PerMapObstacleAvoidanceSensitivityNumber", "settings_obstacle_avoidance_sensitivity", "obstacleAvoidanceSensitivity"),
])
def test_per_map_settings_number_unique_id_and_device(
    coordinator_with_two_maps, cls_name, key, setting_field
):
    """Per-map number gets map-scoped unique_id and map sub-device."""
    coord = coordinator_with_two_maps
    import custom_components.dreame_a2_mower.number as number_mod
    cls = getattr(number_mod, cls_name)

    e0 = cls(coord, map_id=0)
    e1 = cls(coord, map_id=1)

    assert e0._attr_unique_id == f"G2408053AEE0006232_map_0_{key}"
    assert e1._attr_unique_id == f"G2408053AEE0006232_map_1_{key}"
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }
    assert e1._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_1")
    }


def test_per_map_numbers_read_from_their_maps_settings(coordinator_with_two_maps):
    """Each per-map number reads from cloud_state.settings.by_map_id_canonical[map_id]."""
    coord = coordinator_with_two_maps
    from unittest.mock import MagicMock

    cs = MagicMock()
    cs.settings.by_map_id_canonical = {
        0: {
            "mowingHeight": 3,
            "cutterPosition": 1,
            "cutterPositionHeight": 2,
            "edgeMowingNum": 2,
            "obstacleAvoidanceHeight": 10,
            "obstacleAvoidanceDistance": 15,
            "obstacleAvoidanceSensitivity": 1,
        },
        1: {
            "mowingHeight": 6,
            "cutterPosition": 2,
            "cutterPositionHeight": 4,
            "edgeMowingNum": 3,
            "obstacleAvoidanceHeight": 20,
            "obstacleAvoidanceDistance": 25,
            "obstacleAvoidanceSensitivity": 3,
        },
    }
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.number as number_mod
    cases = [
        ("DreameA2PerMapMowingHeightNumber", 3.0, 6.0),
        ("DreameA2PerMapCutterPositionNumber", 1.0, 2.0),
        ("DreameA2PerMapCutterPositionHeightNumber", 2.0, 4.0),
        ("DreameA2PerMapEdgeMowingNumNumber", 2.0, 3.0),
        ("DreameA2PerMapObstacleAvoidanceHeightNumber", 10.0, 20.0),
        ("DreameA2PerMapObstacleAvoidanceDistanceNumber", 15.0, 25.0),
        ("DreameA2PerMapObstacleAvoidanceSensitivityNumber", 1.0, 3.0),
    ]
    for cls_name, v0, v1 in cases:
        cls = getattr(number_mod, cls_name)
        e0 = cls(coord, map_id=0)
        e1 = cls(coord, map_id=1)
        assert e0.native_value == v0, f"{cls_name}/map_0: expected {v0}, got {e0.native_value}"
        assert e1.native_value == v1, f"{cls_name}/map_1: expected {v1}, got {e1.native_value}"


def test_per_map_number_native_value_none_when_missing(coordinator_with_two_maps):
    """Returns None when the setting field isn't present for this map."""
    coord = coordinator_with_two_maps
    from unittest.mock import MagicMock
    cs = MagicMock()
    cs.settings.by_map_id_canonical = {0: {}}
    coord.cloud_state = cs

    import custom_components.dreame_a2_mower.number as number_mod
    e = number_mod.DreameA2PerMapMowingHeightNumber(coord, map_id=0)
    assert e.native_value is None
