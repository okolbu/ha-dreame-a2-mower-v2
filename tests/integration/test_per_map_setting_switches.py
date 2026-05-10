"""Per-map setting switches: one entity per map, on map sub-device."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.const import DOMAIN


@pytest.mark.parametrize("cls_name,key", [
    ("DreameA2EdgeMowingAutoSwitch", "settings_edge_mowing_auto"),
    ("DreameA2EdgeMowingSafeSwitch", "settings_edge_mowing_safe"),
    ("DreameA2EdgeMowingObstacleAvoidanceSwitch", "settings_edge_mowing_obstacle_avoidance"),
    ("DreameA2ObstacleAvoidanceEnabledSwitch", "settings_obstacle_avoidance_enabled"),
    ("DreameA2AiRecognitionHumansSwitch", "ai_recognition_humans"),
    ("DreameA2AiRecognitionAnimalsSwitch", "ai_recognition_animals"),
    ("DreameA2AiRecognitionObjectsSwitch", "ai_recognition_objects"),
])
def test_setting_switches_per_map(coordinator_with_two_maps, cls_name, key):
    coord = coordinator_with_two_maps
    import custom_components.dreame_a2_mower.switch as switch_mod
    cls = getattr(switch_mod, cls_name)

    e0 = cls(coord, map_id=0)
    e1 = cls(coord, map_id=1)

    assert e0._attr_unique_id == f"G2408053AEE0006232_map_0_{key}"
    assert e1._attr_unique_id == f"G2408053AEE0006232_map_1_{key}"
    assert e0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_setting_switch_reads_from_its_maps_settings(coordinator_with_two_maps):
    """Per-map switches read from cloud_state.settings.by_map_id_canonical[map_id]."""
    coord = coordinator_with_two_maps

    # Build a mock cloud_state with distinct values for each map.
    cloud_state = MagicMock()
    cloud_state.settings.by_map_id_canonical = {
        0: {
            "edgeMowingAuto": 1,
            "edgeMowingSafe": 1,
            "edgeMowingObstacleAvoidance": 1,
            "obstacleAvoidanceEnabled": 1,
            "obstacleAvoidanceAi": 0b111,  # all bits on
        },
        1: {
            "edgeMowingAuto": 0,
            "edgeMowingSafe": 0,
            "edgeMowingObstacleAvoidance": 0,
            "obstacleAvoidanceEnabled": 0,
            "obstacleAvoidanceAi": 0,  # all bits off
        },
    }
    coord.cloud_state = cloud_state

    import custom_components.dreame_a2_mower.switch as switch_mod

    for cls_name, expected_on, expected_off in [
        ("DreameA2EdgeMowingAutoSwitch", True, False),
        ("DreameA2EdgeMowingSafeSwitch", True, False),
        ("DreameA2EdgeMowingObstacleAvoidanceSwitch", True, False),
        ("DreameA2ObstacleAvoidanceEnabledSwitch", True, False),
        ("DreameA2AiRecognitionHumansSwitch", True, False),
        ("DreameA2AiRecognitionAnimalsSwitch", True, False),
        ("DreameA2AiRecognitionObjectsSwitch", True, False),
    ]:
        cls = getattr(switch_mod, cls_name)
        e0 = cls(coord, map_id=0)
        e1 = cls(coord, map_id=1)
        assert e0.is_on == expected_on, f"{cls_name}/map_0: expected {expected_on}, got {e0.is_on}"
        assert e1.is_on == expected_off, f"{cls_name}/map_1: expected {expected_off}, got {e1.is_on}"
