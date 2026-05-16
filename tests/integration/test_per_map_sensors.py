"""Tests for per-map sensor compute_value field accessors.

Catches MapData field-name drift: when MapData renamed `total_area` →
`total_area_m2` and used `mowing_zones` (not `mowing_areas`), the
per-map sensors silently kept returning None/0.
"""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.map_decoder import parse_cloud_maps


FIXTURE = (
    Path(__file__).parent.parent / "protocol" / "fixtures" / "multi_map_response.json"
)


def _parsed_map_zero():
    raw = json.loads(FIXTURE.read_text())
    by_id = {int(k): v for k, v in raw["by_id"].items()}
    return parse_cloud_maps(by_id)[0]


def test_map_area_sensor_reads_total_area_m2():
    """Reads MapData.total_area_m2, not total_area (which doesn't exist)."""
    from custom_components.dreame_a2_mower.sensor import DreameA2MapAreaSensor
    m = _parsed_map_zero()
    assert m.total_area_m2 == 100.0  # from fixture totalArea
    sensor = DreameA2MapAreaSensor.__new__(DreameA2MapAreaSensor)
    assert sensor._compute_value(m) == 100.0


def test_map_segment_count_sensor_reads_mowing_zones():
    """Reads MapData.mowing_zones, not mowing_areas (which doesn't exist)."""
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapSegmentCountSensor,
    )
    from custom_components.dreame_a2_mower.map_decoder import MowingZone
    import dataclasses
    m = _parsed_map_zero()
    # Synthesize three zones so the assertion can distinguish a working
    # accessor (returns 3) from a broken one (falls back to () → 0).
    fake_zones = tuple(
        MowingZone(zone_id=i, name=f"Z{i}", path=((0, 0),), area_m2=10.0)
        for i in range(3)
    )
    m = dataclasses.replace(m, mowing_zones=fake_zones)
    sensor = DreameA2MapSegmentCountSensor.__new__(DreameA2MapSegmentCountSensor)
    assert sensor._compute_value(m) == 3


def test_map_name_sensor_falls_back_to_map_n_when_cloud_returns_empty():
    """Cloud often returns empty `name` — surface a friendly 'Map N' instead
    of an empty string so the dashboard isn't blank."""
    from custom_components.dreame_a2_mower.sensor import DreameA2MapNameSensor
    from custom_components.dreame_a2_mower.map_decoder import MapData
    import dataclasses
    m = _parsed_map_zero()
    m_empty = dataclasses.replace(m, name="")
    sensor = DreameA2MapNameSensor.__new__(DreameA2MapNameSensor)
    sensor._map_id = 0
    assert sensor._compute_value(m_empty) == "Map 1"  # map_id 0 → "Map 1" (1-based)

    m_none = dataclasses.replace(m, name=None)
    assert sensor._compute_value(m_none) == "Map 1"

    # Real name passes through unchanged.
    m_named = dataclasses.replace(m, name="Back lawn")
    assert sensor._compute_value(m_named) == "Back lawn"


def test_map_pre_mowing_height_sensor_preserves_half_cm():
    """45 mm wire → 4.5 cm, not 4 cm (regression for 2026-05-17 fix).

    The Dreame app supports half-cm mowing-height saves. The s6p2 wire
    encoding is integer mm in 5 mm steps (inventory.yaml id=s6p2), so
    45 mm is the wire representation of a 4.5 cm app save. An earlier
    `_compute_shadow_value` did `int(mm) // 10` which floor-divided
    half-cm values to the nearest integer cm, silently dropping the
    half. User confirmed 2026-05-17 that mower_tail.py decoded the
    wire correctly as 45 mm while sensor.pre_mowing_height showed 4.
    """
    from custom_components.dreame_a2_mower.sensor import (
        DreameA2MapPreMowingHeightSensor,
    )
    sensor = DreameA2MapPreMowingHeightSensor.__new__(
        DreameA2MapPreMowingHeightSensor
    )
    # Half-cm wire values should survive.
    assert sensor._compute_shadow_value({"mowing_height_mm": 45}) == 4.5
    assert sensor._compute_shadow_value({"mowing_height_mm": 35}) == 3.5
    # Integer-cm wire values stay as float .0 (HA renders correctly).
    assert sensor._compute_shadow_value({"mowing_height_mm": 40}) == 4.0
    assert sensor._compute_shadow_value({"mowing_height_mm": 70}) == 7.0
    # Missing or malformed entries return None.
    assert sensor._compute_shadow_value({}) is None
    assert sensor._compute_shadow_value({"mowing_height_mm": None}) is None
    assert sensor._compute_shadow_value({"mowing_height_mm": "bad"}) is None
