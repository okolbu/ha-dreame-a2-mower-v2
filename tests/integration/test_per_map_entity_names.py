"""Tests for per-map entity name disambiguation.

Each per-map entity class must produce a unique entity in HA for each
map_id without slug collision. The disambiguation comes from TWO sources
together:

1. ``_attr_unique_id`` — set per-map via ``map_unique_id(coord, map_id,
   key)``. This is the registry-side deduplicator; even if friendly names
   collide, two different unique_ids produce two different registry
   entries.
2. ``device_info.name`` — set to the map's name (or fallback "Map N+1").
   HA's ``has_entity_name=True`` prepends the device name to the entity
   name when composing friendly_name and the auto-generated entity_id
   slug.

The entity itself sets ``_attr_name`` to the *entity* name only (e.g.,
"Automatic Edge Mowing"), NOT prefixed with the map name. Manually
prefixing the map name on top of ``has_entity_name=True`` produced
doubled slugs (``select.map_1_map_1_edge_walk_mode``), which is what
the 2026-05-14 cleanup fixed.
"""
from __future__ import annotations

import pytest


def _unique_ids_and_device_names(cls, coord):
    """Helper: instantiate the class for map_id 0 and 1, return tuples."""
    e0 = cls(coord, map_id=0)
    e1 = cls(coord, map_id=1)
    return (
        (e0._attr_unique_id, e1._attr_unique_id),
        (e0._attr_device_info["name"], e1._attr_device_info["name"]),
        (e0._attr_name, e1._attr_name),
    )


# ---------------------------------------------------------------------------
# Camera entity names
# ---------------------------------------------------------------------------

def test_lidar_top_down_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps  # m0.name="Front", m1.name="Back"
    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownCamera

    (uid0, uid1), (dn0, dn1), (an0, an1) = _unique_ids_and_device_names(
        DreameA2LidarTopDownCamera, coord
    )

    assert uid0 != uid1, "unique_id must differ across maps"
    assert dn0 != dn1, "device name must differ across maps"
    assert an0 == an1 == "LiDAR (top-down)", (
        "_attr_name must be the entity name only, no map prefix "
        "(HA prefixes the device name via has_entity_name=True)"
    )


def test_lidar_top_down_full_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownFullCamera

    (uid0, uid1), (dn0, dn1), (an0, an1) = _unique_ids_and_device_names(
        DreameA2LidarTopDownFullCamera, coord
    )

    assert uid0 != uid1
    assert dn0 != dn1
    assert an0 == an1 == "LiDAR (full resolution)"


def test_lidar_top_down_fallback_device_name(coordinator_with_two_maps):
    """When the cached MapData has no name, device_info falls back to
    "Dreame A2 Mower Map N+1" — the integration-namespace prefix keeps
    per-map entity_ids out of the bare-``map_N_*`` slug space (which
    can collide with other integrations).
    """
    coord = coordinator_with_two_maps
    coord.cloud_state.maps_by_id[0].name = None
    coord.cloud_state.maps_by_id[1].name = None

    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownCamera

    cam0 = DreameA2LidarTopDownCamera(coord, map_id=0)
    cam1 = DreameA2LidarTopDownCamera(coord, map_id=1)

    assert cam0._attr_device_info["name"] == "Dreame A2 Mower Map 1"
    assert cam1._attr_device_info["name"] == "Dreame A2 Mower Map 2"
    assert cam0._attr_unique_id != cam1._attr_unique_id

    coord.cloud_state.maps_by_id[0].name = "Front"
    coord.cloud_state.maps_by_id[1].name = "Back"


def test_per_map_device_name_namespaced(coordinator_with_two_maps):
    """Even when MapData has a name (e.g., user named the map in the
    Dreame app), the device name is prefixed with the integration's
    display name. This is the load-bearing rule that keeps per-map
    entity_ids namespaced into ``dreame_a2_mower_map_N_*``.
    """
    coord = coordinator_with_two_maps  # m0.name="Front", m1.name="Back"
    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownCamera

    cam0 = DreameA2LidarTopDownCamera(coord, map_id=0)
    cam1 = DreameA2LidarTopDownCamera(coord, map_id=1)

    assert cam0._attr_device_info["name"] == "Dreame A2 Mower Front"
    assert cam1._attr_device_info["name"] == "Dreame A2 Mower Back"


# ---------------------------------------------------------------------------
# Select entity names
# ---------------------------------------------------------------------------

def test_zone_select_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ZoneSelect

    (uid0, uid1), (dn0, dn1), (an0, an1) = _unique_ids_and_device_names(
        DreameA2ZoneSelect, coord
    )

    assert uid0 != uid1
    assert dn0 != dn1
    assert an0 == an1 == "Zone"


def test_spot_select_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2SpotSelect

    (uid0, uid1), (dn0, dn1), (an0, an1) = _unique_ids_and_device_names(
        DreameA2SpotSelect, coord
    )

    assert uid0 != uid1
    assert dn0 != dn1
    assert an0 == an1 == "Spot"


def test_edge_select_per_map_name(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2EdgeSelect

    (uid0, uid1), (dn0, dn1), (an0, an1) = _unique_ids_and_device_names(
        DreameA2EdgeSelect, coord
    )

    assert uid0 != uid1
    assert dn0 != dn1
    assert an0 == an1 == "Edge"


# ---------------------------------------------------------------------------
# Switch entity names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls_name,expected_name", [
    ("DreameA2EdgeMowingAutoSwitch", "Automatic Edge Mowing"),
    ("DreameA2EdgeMowingSafeSwitch", "Safe Edge Mowing"),
    ("DreameA2EdgeMowingObstacleAvoidanceSwitch", "Obstacle Avoidance on Edges"),
    ("DreameA2ObstacleAvoidanceEnabledSwitch", "LiDAR Obstacle Recognition"),
    ("DreameA2AiRecognitionHumansSwitch", "AI Obstacle Recognition: Humans"),
    ("DreameA2AiRecognitionAnimalsSwitch", "AI Obstacle Recognition: Animals"),
    ("DreameA2AiRecognitionObjectsSwitch", "AI Obstacle Recognition: Objects"),
    ("DreameA2MapEdgemasterSwitch", "EdgeMaster"),
])
def test_per_map_switch_names(coordinator_with_two_maps, cls_name, expected_name):
    coord = coordinator_with_two_maps
    import custom_components.dreame_a2_mower.switch as switch_mod
    cls = getattr(switch_mod, cls_name)

    (uid0, uid1), (dn0, dn1), (an0, an1) = _unique_ids_and_device_names(cls, coord)

    assert uid0 != uid1, f"{cls_name}: unique_id must differ across maps"
    assert dn0 != dn1, f"{cls_name}: device name must differ across maps"
    assert an0 == an1 == expected_name, (
        f"{cls_name}: _attr_name must be the entity name only "
        f"(got map_0={an0!r}, map_1={an1!r}, expected {expected_name!r})"
    )


def test_edge_mowing_auto_switch_per_map_name(coordinator_with_two_maps):
    """Focused test matching the spec's pseudo-test pattern."""
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.switch import DreameA2EdgeMowingAutoSwitch

    sw0 = DreameA2EdgeMowingAutoSwitch(coord, map_id=0)
    sw1 = DreameA2EdgeMowingAutoSwitch(coord, map_id=1)

    assert sw0._attr_unique_id != sw1._attr_unique_id
    assert sw0._attr_device_info["name"] != sw1._attr_device_info["name"]
    assert sw0._attr_name == sw1._attr_name == "Automatic Edge Mowing"
