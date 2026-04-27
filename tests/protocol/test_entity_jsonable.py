"""Guard against regressions of the MowingTelemetry JSON serialization bug.

2026-04-20 incident: during a full mowing run, HA logged 1925 occurrences of
`TypeError: Object of type MowingTelemetry is not JSON serializable` from
`mqtt_eventstream`. Root cause: the generic entity base set
`extra_state_attributes["value"] = device.get_property(...)` which for the
s1p4-backed sensors returned a `MowingTelemetry` dataclass — and HA's
default `JSONEncoder` (used by `mqtt_eventstream`, distinct from the
state-API's `ExtendedJSONEncoder`) does not know how to serialize
arbitrary dataclasses.

These tests pin the behaviour of `entity._jsonable`: every dataclass the
integration holds must round-trip through `json.dumps` after the helper
converts it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from protocol._jsonable import jsonable as _jsonable
from protocol.telemetry import (
    MowingTelemetry,
    Phase,
    PositionBeacon,
)


def _json_roundtrip(obj) -> str:
    """Plain stdlib encoder — the one mqtt_eventstream uses indirectly.

    If this raises TypeError the caller failed to coerce a dataclass.
    """
    return json.dumps(obj)


def test_mowing_telemetry_is_serialized_to_dict():
    t = MowingTelemetry(
        x_mm=47,
        y_mm=-80,
        sequence=28417,
        phase=Phase.ZONE_15,
        phase_raw=15,
        distance_m=1000.0,
        total_area_m2=327.0,
        area_mowed_m2=293.58,
        heading_deg=180.0,
        trace_start_index=1234,
        region_id=1,
        task_id=2,
        percent=50.0,
        total_uint24_m2=327.0,
        finish_uint24_m2=293.58,
    )
    serialized = _jsonable({"value": t})
    assert isinstance(serialized["value"], dict)
    assert serialized["value"]["x_mm"] == 47
    assert serialized["value"]["phase_raw"] == 15
    # Must be a plain dict json.dumps can eat.
    _json_roundtrip(serialized)


def test_position_beacon_is_serialized_to_dict():
    b = PositionBeacon(x_mm=19, y_mm=-64)
    serialized = _jsonable({"value": b})
    assert serialized == {"value": {"x_mm": 19, "y_mm": -64}}
    _json_roundtrip(serialized)


def test_nested_dataclass_inside_list_is_converted():
    t = MowingTelemetry(1, 2, 3, Phase.MOWING, 0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0)
    serialized = _jsonable({"value": [t, {"nested": t}]})
    assert serialized["value"][0]["x_mm"] == 1
    assert serialized["value"][1]["nested"]["x_mm"] == 1
    _json_roundtrip(serialized)


def test_primitives_pass_through_unchanged():
    assert _jsonable(None) is None
    assert _jsonable(42) == 42
    assert _jsonable("hello") == "hello"
    assert _jsonable([1, 2, 3]) == [1, 2, 3]
    assert _jsonable({"a": 1}) == {"a": 1}


def test_arbitrary_dataclass_is_coerced():
    @dataclass
    class Foo:
        x: int
        y: list[int] = field(default_factory=list)

    f = Foo(x=1, y=[1, 2])
    assert _jsonable(f) == {"x": 1, "y": [1, 2]}
    _json_roundtrip(_jsonable(f))


def test_none_attrs_roundtrip():
    # Entity.extra_state_attributes can return None — helper must preserve it
    # without raising.
    assert _jsonable(None) is None
