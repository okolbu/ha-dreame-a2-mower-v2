"""Tests for per-map entity name disambiguation.

Each per-map entity class must set a distinct `_attr_name` that includes
the map's name (or fallback "Map N") as a prefix so HA's entity_id slug
generation produces unique slugs across different map_ids. Without this
fix, map_1's entities shadow map_0's (slug collision) and silently fail
to register.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Camera entity names
# ---------------------------------------------------------------------------

def test_lidar_top_down_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps  # m0.name="Front", m1.name="Back"
    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownCamera

    cam0 = DreameA2LidarTopDownCamera(coord, map_id=0)
    cam1 = DreameA2LidarTopDownCamera(coord, map_id=1)

    assert "Front" in cam0._attr_name
    assert "LiDAR" in cam0._attr_name
    assert "Back" in cam1._attr_name
    assert "LiDAR" in cam1._attr_name
    assert cam0._attr_name != cam1._attr_name


def test_lidar_top_down_full_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownFullCamera

    cam0 = DreameA2LidarTopDownFullCamera(coord, map_id=0)
    cam1 = DreameA2LidarTopDownFullCamera(coord, map_id=1)

    assert "Front" in cam0._attr_name
    assert "LiDAR" in cam0._attr_name
    assert "Back" in cam1._attr_name
    assert "LiDAR" in cam1._attr_name
    assert cam0._attr_name != cam1._attr_name


def test_lidar_top_down_fallback_name(coordinator_with_two_maps):
    """When map has no name attribute, fall back to 'Map N'."""
    coord = coordinator_with_two_maps
    # Temporarily remove names
    coord._cached_maps_by_id[0].name = None
    coord._cached_maps_by_id[1].name = None

    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownCamera

    cam0 = DreameA2LidarTopDownCamera(coord, map_id=0)
    cam1 = DreameA2LidarTopDownCamera(coord, map_id=1)

    assert "Map 1" in cam0._attr_name
    assert "Map 2" in cam1._attr_name
    assert cam0._attr_name != cam1._attr_name

    # Restore
    coord._cached_maps_by_id[0].name = "Front"
    coord._cached_maps_by_id[1].name = "Back"


# ---------------------------------------------------------------------------
# Select entity names
# ---------------------------------------------------------------------------

def test_zone_select_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ZoneSelect

    sel0 = DreameA2ZoneSelect(coord, map_id=0)
    sel1 = DreameA2ZoneSelect(coord, map_id=1)

    assert "Front" in sel0._attr_name
    assert "Zone" in sel0._attr_name
    assert "Back" in sel1._attr_name
    assert "Zone" in sel1._attr_name
    assert sel0._attr_name != sel1._attr_name


def test_spot_select_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2SpotSelect

    sel0 = DreameA2SpotSelect(coord, map_id=0)
    sel1 = DreameA2SpotSelect(coord, map_id=1)

    assert "Front" in sel0._attr_name
    assert "Spot" in sel0._attr_name
    assert "Back" in sel1._attr_name
    assert sel0._attr_name != sel1._attr_name


def test_edge_select_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2EdgeSelect

    sel0 = DreameA2EdgeSelect(coord, map_id=0)
    sel1 = DreameA2EdgeSelect(coord, map_id=1)

    assert "Front" in sel0._attr_name
    assert "Edge" in sel0._attr_name
    assert "Back" in sel1._attr_name
    assert sel0._attr_name != sel1._attr_name


# ---------------------------------------------------------------------------
# Switch entity names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls_name,expected_suffix_fragment", [
    ("DreameA2EdgeMowingAutoSwitch", "Automatic Edge Mowing"),
    ("DreameA2EdgeMowingSafeSwitch", "Safe Edge Mowing"),
    ("DreameA2EdgeMowingObstacleAvoidanceSwitch", "Obstacle Avoidance on Edges"),
    ("DreameA2ObstacleAvoidanceEnabledSwitch", "LiDAR Obstacle Recognition"),
    ("DreameA2AiRecognitionHumansSwitch", "Humans"),
    ("DreameA2AiRecognitionAnimalsSwitch", "Animals"),
    ("DreameA2AiRecognitionObjectsSwitch", "Objects"),
])
def test_per_map_switch_names(coordinator_with_two_maps, cls_name, expected_suffix_fragment):
    coord = coordinator_with_two_maps
    import custom_components.dreame_a2_mower.switch as switch_mod
    cls = getattr(switch_mod, cls_name)

    sw0 = cls(coord, map_id=0)
    sw1 = cls(coord, map_id=1)

    assert "Front" in sw0._attr_name, f"{cls_name} map_0: expected 'Front' in {sw0._attr_name!r}"
    assert expected_suffix_fragment in sw0._attr_name, (
        f"{cls_name} map_0: expected {expected_suffix_fragment!r} in {sw0._attr_name!r}"
    )
    assert "Back" in sw1._attr_name, f"{cls_name} map_1: expected 'Back' in {sw1._attr_name!r}"
    assert sw0._attr_name != sw1._attr_name, f"{cls_name}: map_0 and map_1 names must differ"


def test_edge_mowing_auto_switch_per_map_name(coordinator_with_two_maps):
    """Focused test matching the spec's pseudo-test pattern."""
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.switch import DreameA2EdgeMowingAutoSwitch

    sw0 = DreameA2EdgeMowingAutoSwitch(coord, map_id=0)
    sw1 = DreameA2EdgeMowingAutoSwitch(coord, map_id=1)

    assert "Front" in sw0._attr_name and "Automatic Edge Mowing" in sw0._attr_name
    assert "Back" in sw1._attr_name and "Automatic Edge Mowing" in sw1._attr_name
    assert sw0._attr_name != sw1._attr_name
