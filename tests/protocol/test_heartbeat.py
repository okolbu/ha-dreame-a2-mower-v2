"""Tests for custom_components.dreame_a2_mower.protocol.heartbeat."""

from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.protocol.heartbeat import (
    Heartbeat,
    decode_s1p1,
    InvalidS1P1Frame,
)


# From probe_log_20260417_095500.jsonl at 2026-04-17 09:55:56.
HEARTBEAT_FRAME_A = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0xDA, 0x85, 0x24, 0x00, 0x01, 0x80, 0xC1, 0xBA, 0xCE,
])

# From same session, ~68s later — counter advanced at bytes [11,12].
HEARTBEAT_FRAME_B = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0xDB, 0xB5, 0x24, 0x00, 0x01, 0x80, 0xC1, 0xBA, 0xCE,
])


def test_decode_s1p1_returns_heartbeat_dataclass():
    assert isinstance(decode_s1p1(HEARTBEAT_FRAME_A), Heartbeat)


def test_decode_s1p1_rejects_wrong_length():
    with pytest.raises(InvalidS1P1Frame, match="length"):
        decode_s1p1(b"\xce\x00\xce")


def test_decode_s1p1_rejects_wrong_delimiters():
    bad = bytes([0x00]) + HEARTBEAT_FRAME_A[1:]
    with pytest.raises(InvalidS1P1Frame, match="delimiter"):
        decode_s1p1(bad)


def test_decode_s1p1_exposes_counter_bytes_11_12():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.counter == (0xDA | (0x85 << 8))  # little-endian u16 at [11,12]


def test_decode_s1p1_counter_advances_between_frames():
    a = decode_s1p1(HEARTBEAT_FRAME_A)
    b = decode_s1p1(HEARTBEAT_FRAME_B)
    assert b.counter > a.counter


def test_decode_s1p1_exposes_state_byte_7():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.state_raw == 0


def test_decode_s1p1_exposes_raw_bytes():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.raw == HEARTBEAT_FRAME_A


# From probe_log_20260419_130434.jsonl at 2026-04-20 06:25:42 — the moment
# the Dreame app raised "Battery temperature is low. Charging stopped."
# Byte[6]=0x08 asserts the transient low-temp charging-pause flag;
# byte[10]=0x80 latches for the remainder of the session (see §3.4, §4.4 of
# docs/research/g2408-protocol.md).
HEARTBEAT_FRAME_LOW_TEMP = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00,
    0x80, 0x64, 0x91, 0xFF, 0x00, 0x00, 0x80, 0xC6, 0xBA, 0xCE,
])


def test_decode_s1p1_battery_temp_low_flag_default_false():
    assert decode_s1p1(HEARTBEAT_FRAME_A).battery_temp_low is False


def test_decode_s1p1_battery_temp_low_flag_set_on_06_25_event():
    assert decode_s1p1(HEARTBEAT_FRAME_LOW_TEMP).battery_temp_low is True


def test_decode_s1p1_battery_temp_low_ignores_unrelated_byte6_bits():
    # byte[6]=0x10 is not the low-temp bit — only 0x08 is.
    frame = bytearray(HEARTBEAT_FRAME_A)
    frame[6] = 0x10
    assert decode_s1p1(bytes(frame)).battery_temp_low is False


# --- Error / safety bit-mask tests ---------------------------------------
#
# Five frames captured 2026-04-30 19:37–19:39 during deliberate maintenance
# work that produced the corresponding app notifications:
#   - byte[1] bit 1 (0x02) → drop / Robot tilted
#   - byte[1] bit 0 (0x01) → bumper (NOT mirrored into s2p2)
#   - byte[2] bit 1 (0x02) → lift / Robot lifted
#   - byte[3] bit 7 (0x80) → immediate lift sensor (cloud-side flag, but
#     NOT what the app's "Emergency stop activated" notification fires on)
#   - byte[10] bit 1 (added to base 0x80 → 0x82) → PIN-required latch /
#     "Emergency stop activated" app notification trigger

HEARTBEAT_FRAME_TILTED = bytes([
    0xCE, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0x5D, 0xB3, 0xFF, 0x04, 0x00, 0x80, 0xBF, 0xBA, 0xCE,
])
HEARTBEAT_FRAME_BUMPER_AND_TILTED = bytes([
    0xCE, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0x5D, 0xC3, 0xFF, 0x04, 0x00, 0x80, 0xBF, 0xBA, 0xCE,
])
HEARTBEAT_FRAME_LIFTED = bytes([
    0xCE, 0x03, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0x5C, 0x13, 0xFF, 0x24, 0x00, 0x80, 0xBF, 0xBA, 0xCE,
])
HEARTBEAT_FRAME_EMERGENCY = bytes([
    0xCE, 0x03, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x80, 0x5C, 0xD3, 0xFF, 0x24, 0x00, 0x80, 0xBC, 0xC4, 0xCE,
])


def test_decode_s1p1_drop_flag_default_false():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.drop_tilt is False


def test_decode_s1p1_drop_flag_set_when_byte1_bit_1():
    hb = decode_s1p1(HEARTBEAT_FRAME_TILTED)
    assert hb.drop_tilt is True


def test_decode_s1p1_bumper_default_false():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    assert hb.bumper is False


def test_decode_s1p1_bumper_set_when_byte1_bit_0():
    # In this frame both the tilt bit (0x02) and bumper bit (0x01) are set.
    hb = decode_s1p1(HEARTBEAT_FRAME_BUMPER_AND_TILTED)
    assert hb.bumper is True
    assert hb.drop_tilt is True


def test_decode_s1p1_lift_default_false():
    assert decode_s1p1(HEARTBEAT_FRAME_A).lift is False


def test_decode_s1p1_lift_set_when_byte2_bit_1():
    assert decode_s1p1(HEARTBEAT_FRAME_LIFTED).lift is True


def test_decode_s1p1_emergency_stop_default_false():
    assert decode_s1p1(HEARTBEAT_FRAME_A).emergency_stop is False


def test_decode_s1p1_emergency_stop_set_when_byte3_bit_7():
    assert decode_s1p1(HEARTBEAT_FRAME_EMERGENCY).emergency_stop is True


# byte[10] bit 1 — PIN-required latch. Confirmed 2026-05-04 controlled-lift
# test: sets ~1s after a lift triggers the safety lockout, persists past
# set-down, clears only on PIN entry. The Dreame app's "Emergency stop
# activated" push notification fires when this bit sets.
HEARTBEAT_FRAME_PIN_REQUIRED = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x82, 0x5C, 0xD3, 0xFF, 0x00, 0x00, 0x80, 0xBC, 0xC4, 0xCE,
])


def test_decode_s1p1_pin_required_default_false():
    assert decode_s1p1(HEARTBEAT_FRAME_A).pin_required is False


def test_decode_s1p1_pin_required_set_when_byte10_bit_1():
    assert decode_s1p1(HEARTBEAT_FRAME_PIN_REQUIRED).pin_required is True


# --- WiFi RSSI tests -----------------------------------------------------
#
# byte[17] is the live WiFi RSSI to the currently associated AP, reported
# in dBm as a signed byte (0..127 unused; 128..255 represent −128..−1 dBm).
# Confirmed 2026-04-30 20:09–20:16 by toggling APs and watching the app's
# 5-stage line track in lockstep:
#   0xBD (189) → −67 dBm   "Strong" (3 bars)
#   0xA8 (168) → −88 dBm   "Weak"   (1 bar after killing closest AP)
#   0xC0 (192) → −64 dBm   "Strong" (snapped onto closer AP)
#   0x9F (159) → −97 dBm   floor of usable WiFi during dropout

HEARTBEAT_FRAME_RSSI_WEAK = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x80, 0x64, 0xB1, 0xFF, 0x00, 0x00, 0x80, 0xA8, 0xBA, 0xCE,
])
HEARTBEAT_FRAME_RSSI_STRONG = bytes([
    0xCE, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x80, 0x64, 0xD1, 0xFF, 0x00, 0x00, 0x80, 0xC0, 0xBA, 0xCE,
])


def test_decode_s1p1_wifi_rssi_baseline_dbm():
    hb = decode_s1p1(HEARTBEAT_FRAME_A)
    # byte[17] = 0xC1 = 193 → 193 − 256 = −63 dBm
    assert hb.wifi_rssi_dbm == -63


def test_decode_s1p1_wifi_rssi_weak_signal():
    hb = decode_s1p1(HEARTBEAT_FRAME_RSSI_WEAK)
    assert hb.wifi_rssi_dbm == -88


def test_decode_s1p1_wifi_rssi_strong_signal():
    hb = decode_s1p1(HEARTBEAT_FRAME_RSSI_STRONG)
    assert hb.wifi_rssi_dbm == -64
