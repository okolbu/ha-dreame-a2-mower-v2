"""Tests for custom_components.dreame_a2_mower.protocol.telemetry."""

from __future__ import annotations

import pytest

from protocol.telemetry import (
    MowingTelemetry,
    PositionBeacon,
    decode_s1p4,
    decode_s1p4_position,
    InvalidS1P4Frame,
    Phase,
)


# Fixture frame: 20-bit-packed pose (bytes [1-5]) decodes to
# x=-15620mm (-15.62m), y=1770mm (1.77m), phase=2,
# area_mowed=12.50m², total_area=321.00m², distance=45.4m, seq=1094.
ACTIVE_MOW_FRAME = bytes([
    0xCE,                                     # [0] delimiter
    0xE6, 0xF9,                               # [1-2] x low bytes
    0x1F, 0x0B,                               # [3-4] x-high-nibble + y low bytes
    0x00,                                     # [5] y high byte
    0x46, 0x04,                               # [6-7] seq = 1094
    0x02,                                     # [8] phase = mowing
    0x00,                                     # [9] static
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,       # [10-15] motion (zeros)
    0x00, 0x00,                               # [16-17] motion
    0xFF, 0x7F, 0x00, 0x80,                   # [18-21] sentinel vectors
    0x01, 0x02,                               # [22-23] flags
    0xC6, 0x01,                               # [24-25] distance = 454 (÷10 = 45.4m)
    0x64, 0x7D,                               # [26-27] total area = 32100 (÷100 = 321.00m²)
    0x00,                                     # [28] static
    0xE2, 0x04,                               # [29-30] area mowed = 1250 (÷100 = 12.50m²)
    0x00,                                     # [31] static
    0xCE,                                     # [32] delimiter
])


def test_decode_s1p4_valid_frame_returns_telemetry_dataclass():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert isinstance(t, MowingTelemetry)


def test_decode_s1p4_position_is_in_map_scale_millimetres():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.x_mm == -15620
    assert t.y_mm == 1770


def test_decode_s1p4_position_exposed_in_metres():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # Both axes in mm, both divided by 1000 for metres.
    assert t.x_m == pytest.approx(-15.62)
    assert t.y_m == pytest.approx(1.77)


def test_decode_s1p4_rejects_wrong_length():
    with pytest.raises(InvalidS1P4Frame, match="length"):
        decode_s1p4(b"\xce\x00\xce")


def test_decode_s1p4_rejects_missing_start_delimiter():
    bad = bytes([0x00]) + ACTIVE_MOW_FRAME[1:]
    with pytest.raises(InvalidS1P4Frame, match="delimiter"):
        decode_s1p4(bad)


def test_decode_s1p4_rejects_missing_end_delimiter():
    bad = ACTIVE_MOW_FRAME[:-1] + bytes([0x00])
    with pytest.raises(InvalidS1P4Frame, match="delimiter"):
        decode_s1p4(bad)


def test_decode_s1p4_exposes_sequence_counter():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.sequence == 1094


def test_decode_s1p4_exposes_phase_enum_for_active_mow():
    # ACTIVE_MOW_FRAME has phase byte = 2 (PHASE_2 per current labelling).
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    assert t.phase is Phase.PHASE_2


@pytest.mark.parametrize(
    ("phase_byte", "expected"),
    [
        (0, Phase.MOWING),
        (1, Phase.TRANSIT),
        (2, Phase.PHASE_2),
        (3, Phase.RETURNING),
    ],
)
def test_decode_s1p4_phase_byte_mapping(phase_byte, expected):
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[8] = phase_byte
    assert decode_s1p4(bytes(frame)).phase is expected


def test_decode_s1p4_unknown_phase_byte_is_preserved_raw():
    # Use a value well beyond the enumerated range (which covers 0..15 for
    # observed task-phase indices on a multi-zone lawn). The decoder must
    # still preserve the raw integer on the dataclass and fall back to
    # Phase.UNKNOWN for values outside the enum.
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[8] = 99
    t = decode_s1p4(bytes(frame))
    assert t.phase is Phase.UNKNOWN
    assert t.phase_raw == 99


def test_decode_s1p4_distance_meters_from_deci_units():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 454 → 45.4m
    assert t.distance_m == pytest.approx(45.4)


def test_decode_s1p4_total_area_from_centiares():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 32100 → 321.00m²
    assert t.total_area_m2 == pytest.approx(321.00)


def test_decode_s1p4_mowed_area_from_centiares():
    t = decode_s1p4(ACTIVE_MOW_FRAME)
    # raw = 1250 → 12.50m²
    assert t.area_mowed_m2 == pytest.approx(12.50)


# --- heading angle tests ----------------------------------------------
# Per apk parseRobotPose, the byte immediately after the pose bytes encodes
# a heading angle (uint8 → 0..360°). On g2408, the pose is int16_le at
# [1-4], so the heading byte is at [6] (byte [5] is constantly 0xFF in all
# captured frames, which would decode to a useless constant 360°). See
# decode_s1p4 for full rationale. A rotating-mower capture is still needed
# to fully verify the byte position; these tests just pin the contract.


def test_decode_s1p4_extracts_heading_angle():
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[6] = 128
    t = decode_s1p4(bytes(frame))
    # (128 / 255) * 360 = 180.7058...
    assert 180.0 < t.heading_deg < 181.5


def test_decode_s1p4_heading_zero_for_zero_byte():
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[6] = 0
    t = decode_s1p4(bytes(frame))
    assert t.heading_deg == 0.0


def test_decode_s1p4_heading_full_circle_just_under_360():
    frame = bytearray(ACTIVE_MOW_FRAME)
    frame[6] = 255
    t = decode_s1p4(bytes(frame))
    assert t.heading_deg == 360.0


# --- 8-byte idle/beacon frame tests -----------------------------------

# Captured live: docked mower emitting minimal beacon
# (decoded as X=7370mm, Y=-3150mm).
BEACON_DOCKED = bytes([0xCE, 0xE1, 0x02, 0x50, 0xEC, 0xFF, 0x06, 0xCE])

# Captured live during user remote-drive (decoded as X=19860mm, Y=1550mm).
BEACON_DRIVE = bytes([0xCE, 0xC2, 0x07, 0xB0, 0x09, 0x00, 0xE9, 0xCE])

# Captured live, near dock (decoded as X=250mm, Y=-70mm).
BEACON_NEAR_DOCK = bytes([0xCE, 0x19, 0x00, 0x90, 0xFF, 0xFF, 0xFD, 0xCE])


def test_decode_s1p4_position_from_beacon_returns_position():
    p = decode_s1p4_position(BEACON_DOCKED)
    assert isinstance(p, PositionBeacon)
    assert p.x_mm == 7370
    assert p.y_mm == -3150


def test_decode_s1p4_position_handles_positive_y():
    p = decode_s1p4_position(BEACON_DRIVE)
    assert p.x_mm == 19860
    assert p.y_mm == 1550


def test_decode_s1p4_position_handles_small_negative_y():
    p = decode_s1p4_position(BEACON_NEAR_DOCK)
    assert p.x_mm == 250
    assert p.y_mm == -70


def test_decode_s1p4_position_accepts_full_frame_too():
    # The convenience decoder should work on 33-byte frames, returning
    # a PositionBeacon with just X/Y (callers who want full telemetry
    # should call decode_s1p4 directly).
    p = decode_s1p4_position(ACTIVE_MOW_FRAME)
    assert p.x_mm == -15620
    assert p.y_mm == 1770


def test_decode_s1p4_position_rejects_unexpected_length():
    with pytest.raises(InvalidS1P4Frame):
        decode_s1p4_position(bytes([0xCE, 0x00, 0x00, 0xCE]))  # 4 bytes


def test_decode_s1p4_position_rejects_missing_delimiters():
    with pytest.raises(InvalidS1P4Frame):
        decode_s1p4_position(bytes([0x00, 0xE1, 0x02, 0x50, 0xEC, 0xFF, 0x06, 0x00]))


def test_position_beacon_x_m_and_y_m_helpers():
    p = decode_s1p4_position(BEACON_DRIVE)
    assert p.x_m == pytest.approx(19.86)
    assert p.y_m == pytest.approx(1.55)


# --- 10-byte BUILDING frame tests --------------------------------------

# Captured live during user's map-build zone-expansion (s2p1=11)
# — decoded as X=19150mm (19.15m), Y=2130mm (2.13m).
BUILD_FRAME_1 = bytes([0xCE, 0x7B, 0x07, 0x50, 0x0D, 0x00, 0x0B, 0x08, 0x00, 0xCE])

# Second build-frame capture (decoded as X=11580mm, Y=-3040mm).
BUILD_FRAME_2 = bytes([0xCE, 0x86, 0x04, 0x00, 0xED, 0xFF, 0x4B, 0x1B, 0x00, 0xCE])


def test_decode_s1p4_position_accepts_10_byte_building_frame():
    p = decode_s1p4_position(BUILD_FRAME_1)
    assert p.x_mm == 19150
    assert p.y_mm == 2130


def test_decode_s1p4_position_10_byte_handles_negative_y():
    p = decode_s1p4_position(BUILD_FRAME_2)
    assert p.x_mm == 11580
    assert p.y_mm == -3040


def test_decode_s1p4_position_rejects_9_byte_frame():
    # Defensive: 9 bytes is not a recognized variant.
    with pytest.raises(InvalidS1P4Frame):
        decode_s1p4_position(bytes([0xCE] + [0] * 7 + [0xCE]))


# --- task struct (bytes [22-31]) tests --------------------------------
# Per apk parseRobotTask, frame bytes [22-31] hold regionId / taskId /
# percent / total_uint24_m² / finish_uint24_m². The uint24 area reads
# overlap the low 16 bits of the legacy uint16 reads (which truncate
# above 655.35 m²).


def test_decode_s1p4_task_struct_zero_frame():
    """All-zero frame: every task field is 0."""
    frame = bytes([0xCE] + [0] * 31 + [0xCE])
    telem = decode_s1p4(frame)
    assert telem.region_id == 0
    assert telem.task_id == 0
    assert telem.percent == 0.0
    assert telem.total_uint24_m2 == 0.0
    assert telem.finish_uint24_m2 == 0.0


def test_decode_s1p4_task_struct_uint24_overflows_uint16():
    """If total_uint24 > 65535 cm² (655.35 m²), the legacy uint16
    read truncates; the new uint24 read survives. Pin the behavior."""
    frame = bytearray([0xCE] + [0] * 31 + [0xCE])
    # Set bytes [26-28] to 0x000100 little-endian → 65536 cent
    # → 655.36 m². Just above uint16 max.
    frame[26] = 0x00
    frame[27] = 0x00
    frame[28] = 0x01
    telem = decode_s1p4(bytes(frame))
    assert telem.total_uint24_m2 == 655.36
    # Legacy field would read bytes [26-27] = 0 → reports 0.
    assert telem.total_area_m2 == 0.0


def test_decode_s1p4_task_percent_division():
    """percent = bytes[24-25] / 100. Test 5000 raw → 50.00 %."""
    frame = bytearray([0xCE] + [0] * 31 + [0xCE])
    frame[24] = 0x88
    frame[25] = 0x13
    telem = decode_s1p4(bytes(frame))
    assert telem.percent == 50.0
