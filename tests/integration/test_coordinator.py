"""Coordinator tests — state update flow.

These use pytest-homeassistant-custom-component (added in F1.4.3).
F1.4.2 starts with a non-HA test that just verifies the
update-state-from-payload logic.
"""
from __future__ import annotations

import base64
import struct

from custom_components.dreame_a2_mower.mower.state import (
    ChargingStatus,
    MowerState,
    State,
)
from custom_components.dreame_a2_mower.coordinator import (
    apply_property_to_state,
)


def test_apply_battery_level_property():
    """A (3, 1) property push updates MowerState.battery_level."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=1, value=72)
    assert new_state.battery_level == 72
    # Other fields unchanged
    assert new_state.state is None
    assert new_state.charging_status is None


def test_apply_state_property():
    """A (2, 1) property push updates MowerState.state."""
    state = MowerState()
    new_state = apply_property_to_state(state, siid=2, piid=1, value=1)
    assert new_state.state == State.WORKING


def test_apply_charging_status_property():
    state = MowerState()
    new_state = apply_property_to_state(state, siid=3, piid=2, value=1)
    assert new_state.charging_status == ChargingStatus.CHARGING


def test_apply_unknown_property_returns_unchanged_state():
    """Unknown (siid, piid) is logged elsewhere; the state is unchanged."""
    state = MowerState(battery_level=50)
    new_state = apply_property_to_state(state, siid=99, piid=99, value="weird")
    assert new_state == state


def test_apply_property_with_invalid_state_value_keeps_field_none():
    """Invalid enum values are dropped (the integration logs NOVEL elsewhere)."""
    state = MowerState()
    # 999 is not a valid State enum
    new_state = apply_property_to_state(state, siid=2, piid=1, value=999)
    assert new_state.state is None


# ---------------------------------------------------------------------------
# F2.3.1 — s1.4 telemetry blob dispatch tests
# ---------------------------------------------------------------------------

def _pack_pose(x20: int, y20: int) -> bytes:
    """Pack (x20, y20) into 5 bytes using the apk's 20-bit signed format.

    The decoder uses _decode_pose which reverses this operation:
      x: 20-bit signed stored in b0[7:0], b1[7:0], b2[3:0]
      y: 20-bit signed stored in b2[7:4], b3[7:0], b4[7:0]
    Raw values are in map-scale millimetres (= actual_mm / 10 × 10).
    """
    if x20 < 0:
        x20 += 0x100000
    if y20 < 0:
        y20 += 0x100000
    b0 = x20 & 0xFF
    b1 = (x20 >> 8) & 0xFF
    b2 = ((y20 & 0x0F) << 4) | ((x20 >> 16) & 0x0F)
    b3 = (y20 >> 4) & 0xFF
    b4 = (y20 >> 12) & 0xFF
    return bytes([b0, b1, b2, b3, b4])


def _make_s1p4_frame_33b(
    x_m: float = 1.23,
    y_m: float = -4.56,
    phase: int = 2,
    distance_dm: int = 3450,
    area_mowed_cm2: int = 1250,
) -> bytes:
    """Construct a valid 33-byte s1.4 telemetry frame.

    Uses the apk's 20-bit signed packed pose encoding at bytes [1-5].
    Position arguments are in metres; the encoder converts to raw units
    (x20 = round(x_m * 1000 / 10), y20 = round(y_m * 1000 / 10)).

    distance_dm:    distance in decimetres (distance_m = distance_dm / 10)
    area_mowed_cm2: area in cm² (area_mowed_m2 = area_mowed_cm2 / 100)
    """
    # x20 and y20 are in map-scale millimetres divided by 10 (× 10 factor)
    x20 = round(x_m * 1000 / 10)   # x_mm / 10
    y20 = round(y_m * 1000 / 10)   # y_mm / 10
    pose = _pack_pose(x20, y20)

    frame = bytearray(33)
    frame[0] = 0xCE                                   # delimiter
    frame[1:6] = pose                                 # bytes 1-5: pose
    frame[6] = 0                                      # heading byte
    frame[7] = 0                                      # trace_start_index[0]
    frame[8] = phase                                  # phase byte
    # bytes 9-21: zeros (motion vectors, trace_start, etc.)
    frame[22] = 0                                     # region_id
    frame[23] = 0                                     # task_id
    struct.pack_into("<H", frame, 24, distance_dm)    # bytes 24-25: distance
    struct.pack_into("<H", frame, 26, 50000)          # bytes 26-27: total_area (filler)
    frame[28] = 0
    struct.pack_into("<H", frame, 29, area_mowed_cm2) # bytes 29-30: area_mowed
    frame[31] = 0
    frame[32] = 0xCE                                  # delimiter
    return bytes(frame)


def test_s1p4_blob_updates_position_area_distance_phase():
    """A (1, 4) push (telemetry blob) decodes and updates multiple state fields."""
    state = MowerState()
    blob = _make_s1p4_frame_33b(
        x_m=1.23, y_m=-4.56, phase=2, distance_dm=3450, area_mowed_cm2=1250
    )
    # MQTT delivers the blob base64-encoded in the value field
    value = base64.b64encode(blob).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=4, value=value)
    assert abs(new_state.position_x_m - 1.23) < 0.001
    assert abs(new_state.position_y_m - (-4.56)) < 0.001
    assert new_state.mowing_phase == 2
    assert abs(new_state.area_mowed_m2 - 12.50) < 0.001
    assert abs(new_state.total_distance_m - 345.0) < 0.001


def test_s1p4_short_frame_updates_position_only():
    """8-byte BEACON short frames update only position_x_m and position_y_m."""
    state = MowerState(mowing_phase=5, area_mowed_m2=7.0)
    # Build an 8-byte beacon with the same pose as the 33-byte test
    x20 = round(1.23 * 1000 / 10)
    y20 = round(-4.56 * 1000 / 10)
    pose = _pack_pose(x20, y20)
    frame8 = bytearray(8)
    frame8[0] = 0xCE
    frame8[1:6] = pose
    frame8[7] = 0xCE
    value = base64.b64encode(bytes(frame8)).decode("ascii")
    new_state = apply_property_to_state(state, siid=1, piid=4, value=value)
    assert abs(new_state.position_x_m - 1.23) < 0.001
    assert abs(new_state.position_y_m - (-4.56)) < 0.001
    # Non-position fields are unchanged (still the original values)
    assert new_state.mowing_phase == 5
    assert new_state.area_mowed_m2 == 7.0


def test_s1p4_invalid_blob_returns_unchanged_state():
    """A malformed s1.4 blob is dropped (logged) without crashing."""
    state = MowerState(position_x_m=1.0)
    new_state = apply_property_to_state(state, siid=1, piid=4, value="not-base64-padded!!")
    # State is unchanged
    assert new_state == state
