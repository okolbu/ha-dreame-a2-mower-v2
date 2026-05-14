"""Per-map PRE-family shadow sensors (read-only).

These sensors expose the per-map mowing_height / mowing_efficiency /
edgemaster values learnt over time from s6.2 pushes. They read from
`coord.state_machine.snapshot().pre_shadow_by_map_id`, NOT from the
MapData cache like the other per-map sensors.

Unknown (None) until the user saves settings on a given map at least
once in the Dreame app.

See docs/research/g2408-protocol.md § s6.2 and
mower/state_machine.handle_pre_shadow_update.
"""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.mower.state_machine import (
    MowerStateMachine,
)


def _make_coord_with_state_machine():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    map0.name = "Front lawn"
    map1 = MagicMock()
    map1.name = "Back lawn"
    coord._cached_maps_by_id = {0: map0, 1: map1}
    coord.state_machine = MowerStateMachine()
    return coord


def test_pre_height_sensor_unknown_until_first_push():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapPreMowingHeightSensor,
    )
    coord = _make_coord_with_state_machine()
    sensor = DreameA2MapPreMowingHeightSensor(coord, map_id=0)
    # Shadow has no entry for map_id=0 yet → Unknown.
    assert sensor.native_value is None


def test_pre_height_sensor_returns_cm_from_mm():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapPreMowingHeightSensor,
    )
    coord = _make_coord_with_state_machine()
    coord.state_machine.handle_pre_shadow_update(
        map_id=0,
        mowing_height_mm=60,
        mowing_efficiency=1,
        edgemaster=True,
        now_unix=1000,
    )
    sensor = DreameA2MapPreMowingHeightSensor(coord, map_id=0)
    # 60mm → 6cm.
    assert sensor.native_value == 6


def test_map_mowing_efficiency_select_returns_standard_label_for_zero():
    """Replaces ``DreameA2MapPreMowingEfficiencySensor`` 2026-05-15."""
    from custom_components.dreame_a2_mower.select import (
        DreameA2MapMowingEfficiencySelect,
    )
    coord = _make_coord_with_state_machine()
    coord.state_machine.handle_pre_shadow_update(
        map_id=0,
        mowing_efficiency=0,
        now_unix=1000,
    )
    select = DreameA2MapMowingEfficiencySelect(coord, map_id=0)
    assert select.current_option == "Standard"


def test_map_mowing_efficiency_select_returns_efficient_label_for_one():
    from custom_components.dreame_a2_mower.select import (
        DreameA2MapMowingEfficiencySelect,
    )
    coord = _make_coord_with_state_machine()
    coord.state_machine.handle_pre_shadow_update(
        map_id=0,
        mowing_efficiency=1,
        now_unix=1000,
    )
    select = DreameA2MapMowingEfficiencySelect(coord, map_id=0)
    assert select.current_option == "Efficient"


def test_map_mowing_efficiency_select_unavailable_until_first_push():
    from custom_components.dreame_a2_mower.select import (
        DreameA2MapMowingEfficiencySelect,
    )
    coord = _make_coord_with_state_machine()
    select = DreameA2MapMowingEfficiencySelect(coord, map_id=0)
    assert select.current_option is None
    assert select.available is False


def test_pre_edgemaster_sensor_returns_on_off_labels():
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapPreEdgemasterSensor,
    )
    coord = _make_coord_with_state_machine()
    coord.state_machine.handle_pre_shadow_update(
        map_id=0,
        edgemaster=True,
        now_unix=1000,
    )
    sensor = DreameA2MapPreEdgemasterSensor(coord, map_id=0)
    assert sensor.native_value == "On"

    coord.state_machine.handle_pre_shadow_update(
        map_id=0,
        edgemaster=False,
        now_unix=1100,
    )
    assert sensor.native_value == "Off"


def test_pre_shadow_sensors_isolate_per_map():
    """Each map's sensor reads only its own shadow entry."""
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapPreMowingHeightSensor,
        DreameA2MapPreEdgemasterSensor,
    )
    from custom_components.dreame_a2_mower.select import (
        DreameA2MapMowingEfficiencySelect,
    )
    coord = _make_coord_with_state_machine()
    coord.state_machine.handle_pre_shadow_update(
        map_id=0,
        mowing_height_mm=30,
        mowing_efficiency=0,
        edgemaster=False,
        now_unix=1000,
    )
    coord.state_machine.handle_pre_shadow_update(
        map_id=1,
        mowing_height_mm=60,
        mowing_efficiency=1,
        edgemaster=True,
        now_unix=1001,
    )
    height0 = DreameA2MapPreMowingHeightSensor(coord, map_id=0)
    height1 = DreameA2MapPreMowingHeightSensor(coord, map_id=1)
    eff0 = DreameA2MapMowingEfficiencySelect(coord, map_id=0)
    eff1 = DreameA2MapMowingEfficiencySelect(coord, map_id=1)
    em0 = DreameA2MapPreEdgemasterSensor(coord, map_id=0)
    em1 = DreameA2MapPreEdgemasterSensor(coord, map_id=1)
    assert height0.native_value == 3
    assert height1.native_value == 6
    assert eff0.current_option == "Standard"
    assert eff1.current_option == "Efficient"
    assert em0.native_value == "Off"
    assert em1.native_value == "On"


def test_pre_shadow_sensors_unknown_when_state_machine_missing():
    """Defensive: no state_machine attr → None, not exception."""
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapPreMowingHeightSensor,
    )
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    map0.name = "Front lawn"
    coord._cached_maps_by_id = {0: map0}
    coord.state_machine = None
    sensor = DreameA2MapPreMowingHeightSensor(coord, map_id=0)
    assert sensor.native_value is None


def test_pre_shadow_sensors_diagnostic_category():
    from homeassistant.helpers.entity import EntityCategory
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapPreMowingHeightSensor,
        DreameA2MapPreEdgemasterSensor,
    )
    for cls in (
        DreameA2MapPreMowingHeightSensor,
        DreameA2MapPreEdgemasterSensor,
    ):
        # Class-attribute lookup: _attr_entity_category is the HA-Entity
        # contract for fixed entity_category metadata.
        assert cls._attr_entity_category == EntityCategory.DIAGNOSTIC
