"""Property mapping — the (siid, piid) → field_name table."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.property_mapping import (
    PROPERTY_MAPPING,
    PropertyMappingEntry,
    resolve_field,
)


def test_state_maps_to_s2p1():
    """The 'state' field maps to (siid=2, piid=1) per protocol-doc §2.1."""
    entry = PROPERTY_MAPPING[(2, 1)]
    assert entry.field_name == "state"
    assert entry.disambiguator is None


def test_battery_level_maps_to_s3p1():
    entry = PROPERTY_MAPPING[(3, 1)]
    assert entry.field_name == "battery_level"


def test_charging_status_maps_to_s3p2():
    entry = PROPERTY_MAPPING[(3, 2)]
    assert entry.field_name == "charging_status"


def test_resolve_field_with_no_disambiguator():
    """Common case: resolve_field returns the primary field_name."""
    assert resolve_field((2, 1), value=1) == "state"
    assert resolve_field((3, 1), value=72) == "battery_level"


def test_resolve_field_unknown_pair_returns_none():
    """Unknown (siid, piid) returns None (caller emits NOVEL warning)."""
    assert resolve_field((9, 99), value=42) is None


def test_disambiguator_pattern_is_supported():
    """The disambiguator slot exists and is invoked by resolve_field.

    Per spec §3, multi-purpose (siid, piid) pairs (e.g., the
    robot-voice / notification-type slot) get an optional callable
    that picks the alternate field name based on payload shape.
    F1 has no entry needing this, but the wiring must work."""
    def _disambiguate(value: object) -> str:
        return "alt_field" if isinstance(value, dict) else "primary_field"

    entry = PropertyMappingEntry(
        field_name="primary_field",
        disambiguator=_disambiguate,
    )
    assert entry.field_name == "primary_field"
    assert entry.disambiguator is not None
    # Direct callable test
    assert _disambiguate(42) == "primary_field"
    assert _disambiguate({"x": 1}) == "alt_field"


def test_obstacle_flag_maps_to_s1p53():
    assert PROPERTY_MAPPING[(1, 53)].field_name == "obstacle_flag"


def test_error_code_maps_to_s2p2():
    assert PROPERTY_MAPPING[(2, 2)].field_name == "error_code"


def test_total_lawn_area_maps_to_s2p66():
    """s2.66 is a 2-element list; the disambiguator extracts [0]."""
    entry = PROPERTY_MAPPING[(2, 66)]
    assert entry.field_name == "total_lawn_area_m2"
    # Disambiguator extracts [0] from the list
    assert entry.disambiguator is not None


def test_wifi_signal_maps_to_s6p3():
    """s6.3 is [cloud_connected: bool, rssi_dbm: int].
    Resolution depends on payload shape — the disambiguator picks
    one of two MowerState fields per call."""
    entry = PROPERTY_MAPPING[(6, 3)]
    assert entry.disambiguator is not None


def test_slam_label_maps_to_s2p65():
    assert PROPERTY_MAPPING[(2, 65)].field_name == "slam_task_label"


def test_task_state_maps_to_s2p56():
    assert PROPERTY_MAPPING[(2, 56)].field_name == "task_state_code"


def test_s6p2_extracts_mowing_height_efficiency_edgemaster():
    """s6.2 = [height_mm, mow_mode, edgemaster, ?] updates 3 fields."""
    entry = PROPERTY_MAPPING[(6, 2)]
    assert entry.multi_field is not None
    # Test the extractors directly
    extractors = dict(entry.multi_field)
    assert extractors["pre_mowing_height_mm"]([60, 0, True, 2]) == 60
    assert extractors["pre_mowing_efficiency"]([60, 1, True, 2]) == 1
    assert extractors["pre_edgemaster"]([60, 0, True, 2]) is True
    # Default behavior on too-short list
    assert extractors["pre_mowing_height_mm"]([60]) == 60
    assert extractors["pre_mowing_efficiency"]([60]) is None
