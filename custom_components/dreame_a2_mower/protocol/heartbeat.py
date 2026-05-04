"""s1p1 heartbeat decoder for Dreame A2 (g2408).

The s1p1 property is a 20-byte blob sent every ~45 s regardless of mowing
state, plus extra emissions during state transitions. Most bytes are
static; the decoded fields below have been confirmed against captured
probe traces and matching app notifications. See
docs/research/g2408-protocol.md §3.4, §4.4 for byte-by-byte rationale.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

FRAME_LENGTH = 20
FRAME_DELIMITER = 0xCE
BATTERY_TEMP_LOW_MASK = 0x08

# Error / safety flags — confirmed 2026-04-30 19:37–19:39 by deliberate
# tilt / lift / bumper-press / e-stop tests.
DROP_TILT_MASK = 0x02       # byte[1] bit 1
BUMPER_MASK = 0x01          # byte[1] bit 0 (NOT mirrored to s2p2)
LIFT_MASK = 0x02            # byte[2] bit 1
EMERGENCY_STOP_MASK = 0x80  # byte[3] bit 7
# byte[10] bit 1 = active safety-alert flag (one-shot, paired with the
# Dreame app's "Emergency stop activated" push notification + the mower's
# red LED + voice prompt). Confirmed 2026-05-04 controlled-lift test
# series:
#   - Sets ~1 s after byte[3] bit 7 sets (i.e. shortly after a safety
#     event triggers the lockout).
#   - Self-clears 30–90 s later REGARDLESS of state — clears even while
#     the lid is still open and PIN has not been entered. Variable
#     timer that's likely reset by sensor activity.
#   - Independent of PIN entry: clears whether or not the user typed
#     the PIN, and whether or not the lid is still open.
# byte[3] bit 7 (EMERGENCY_STOP_MASK) is the load-bearing "PIN-required"
# state — it persists until PIN entry. byte[10] bit 1 only tracks the
# transient alert UI window.
SAFETY_ALERT_MASK = 0x02    # byte[10] bit 1


class InvalidS1P1Frame(ValueError):
    """Raised when an s1p1 frame does not match the expected shape."""


@dataclass(frozen=True)
class Heartbeat:
    counter: int
    state_raw: int
    battery_temp_low: bool
    drop_tilt: bool
    bumper: bool
    lift: bool
    emergency_stop: bool
    safety_alert_active: bool
    wifi_rssi_dbm: int
    raw: bytes


def _signed_byte(b: int) -> int:
    """Two's-complement of a single byte read as int8."""
    return b - 256 if b >= 128 else b


def decode_s1p1(data: bytes) -> Heartbeat:
    if len(data) != FRAME_LENGTH:
        raise InvalidS1P1Frame(
            f"expected frame length {FRAME_LENGTH}, got {len(data)}"
        )
    if data[0] != FRAME_DELIMITER or data[-1] != FRAME_DELIMITER:
        raise InvalidS1P1Frame(
            f"expected 0x{FRAME_DELIMITER:02X} delimiters at [0] and [19]"
        )
    counter = struct.unpack_from("<H", data, 11)[0]
    return Heartbeat(
        counter=counter,
        state_raw=data[7],
        battery_temp_low=bool(data[6] & BATTERY_TEMP_LOW_MASK),
        drop_tilt=bool(data[1] & DROP_TILT_MASK),
        bumper=bool(data[1] & BUMPER_MASK),
        lift=bool(data[2] & LIFT_MASK),
        emergency_stop=bool(data[3] & EMERGENCY_STOP_MASK),
        safety_alert_active=bool(data[10] & SAFETY_ALERT_MASK),
        wifi_rssi_dbm=_signed_byte(data[17]),
        raw=bytes(data),
    )
