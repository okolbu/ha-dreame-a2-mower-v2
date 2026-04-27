"""g2408 capability constants — locks the snapshot from P1.4."""
from __future__ import annotations

import dataclasses

import pytest

from custom_components.dreame_a2_mower.mower.capabilities import (
    CAPABILITIES,
    Capabilities,
)


def test_capabilities_is_frozen():
    """Capabilities is a frozen dataclass — values cannot be mutated."""
    assert dataclasses.is_dataclass(CAPABILITIES)
    with pytest.raises(dataclasses.FrozenInstanceError):
        CAPABILITIES.lidar_navigation = False  # type: ignore[misc]


def test_capabilities_g2408_snapshot():
    """The CAPABILITIES singleton matches the P1.4 snapshot for g2408."""
    c = CAPABILITIES
    # Confirmed True on g2408
    assert c.lidar_navigation is True

    # Confirmed False on g2408 (snapshot — every flag below is False)
    assert c.ai_detection is False
    assert c.auto_charging is False
    assert c.auto_rename_segment is False
    assert c.auto_switch_settings is False
    assert c.backup_map is False
    assert c.camera_streaming is False
    assert c.cleangenius is False
    assert c.cleangenius_auto is False
    assert c.cleaning_route is False
    assert c.customized_cleaning is False
    assert c.dnd is False
    assert c.dnd_task is False
    assert c.extended_furnitures is False
    assert c.fill_light is False
    assert c.floor_direction_cleaning is False
    assert c.floor_material is False
    assert c.fluid_detection is False
    assert c.gen5 is False
    assert c.large_particles_boost is False
    assert c.lensbrush is False
    assert c.map_object_offset is False
    assert c.max_suction_power is False
    assert c.multi_floor_map is False
    assert c.new_furnitures is False
    assert c.new_state is False
    assert c.obstacle_image_crop is False
    assert c.obstacles is False
    assert c.off_peak_charging is False
    assert c.pet_detective is False
    assert c.pet_furniture is False
    assert c.pet_furnitures is False
    assert c.saved_furnitures is False
    assert c.segment_slow_clean_route is False
    assert c.segment_visibility is False
    assert c.shortcuts is False
    assert c.task_type is False
    assert c.voice_assistant is False
    assert c.wifi_map is False


def test_capabilities_singleton():
    """Capabilities() always returns the same instance — frozen, no per-config differences."""
    from custom_components.dreame_a2_mower.mower.capabilities import CAPABILITIES as c1
    from custom_components.dreame_a2_mower.mower.capabilities import CAPABILITIES as c2
    assert c1 is c2
