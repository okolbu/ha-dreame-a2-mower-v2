"""Two pose decoders for s1p4 frames — used to validate which one
matches g2408 firmware behavior.

Background: the existing telemetry decoder (telemetry.py) reads pose
as int16_le from bytes [1-2] (x_cm) and [3-4] (y_mm). The
ioBroker.dreame APK decompilation (apk.md) shows a different layout
on g2568a: bytes [1-6] hold three packed values (x24, y24, angle8)
where x and y share byte [3] (the original numbering — adjust by 1
since our 0xCE delimiter at byte 0 means the apk's "byte 0" is our
byte 1).

This module exposes both decoders so a test suite can run them
side by side against captured frames. The integration code can
later switch to whichever proves correct on g2408 — or keep both
behind a feature flag if the answer is firmware-dependent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PoseInt16LE:
    """Result of the original int16_le decoder."""
    x_cm: int
    y_mm: int


@dataclass(frozen=True)
class PosePacked12:
    """Result of the apk's 12-bit-packed decoder."""
    x_raw: int       # signed 24-bit (sign-extended from 12 bits packed)
    y_raw: int       # signed 24-bit
    angle_deg: float # 0..360


def decode_pose_int16le(payload: Sequence[int]) -> PoseInt16LE:
    """Original decoder — reads bytes [1-2] as int16_le x_cm and [3-4]
    as int16_le y_mm. Assumes the leading 0xCE delimiter at byte 0."""
    if len(payload) < 5:
        raise ValueError(f"need >=5 bytes for int16_le decode, got {len(payload)}")
    x_lo, x_hi = payload[1], payload[2]
    y_lo, y_hi = payload[3], payload[4]
    x = x_lo | (x_hi << 8)
    if x & 0x8000:
        x -= 0x10000
    y = y_lo | (y_hi << 8)
    if y & 0x8000:
        y -= 0x10000
    return PoseInt16LE(x_cm=x, y_mm=y)


def decode_pose_packed12(payload: Sequence[int]) -> PosePacked12:
    """APK's decoder — bytes [1-6] hold (x24, y24, angle8) packed.
    Per apk.md parseRobotPose, the in-payload offsets are 0..5 (the
    apk passes bytes after the 0xCE delimiter is stripped), so we
    read our payload[1..6] as the apk's payload[0..5].

    Scheme: x and y are each 24-bit signed, packed into bytes [0-2]
    and [2-4] with byte [2] shared (its low nibble is x's high, its
    high nibble is y's low). Angle is byte [5] scaled 0..255 -> 0..360 deg.

    NOTE: Verdict C (see fixture `captured_s1p4_frames.json`) rejected
    this decoder for g2408 — it produces million-scale nonsense. Kept
    as a reference implementation only; no production caller."""
    if len(payload) < 7:
        raise ValueError(f"need >=7 bytes for packed12 decode, got {len(payload)}")
    p = payload[1:]  # apk's "payload[0..5]"
    # x: bits 0..23 = (p[0] << 0) | (p[1] << 8) | (p[2] << 16), masked to 24
    # bits, then sign-extend from bit 23.
    x = p[0] | (p[1] << 8) | (p[2] << 16)
    if x & 0x800000:
        x -= 0x1000000
    # y shares byte [2] — apk treats it as the low byte of y per the
    # docstring.
    y = p[2] | (p[3] << 8) | (p[4] << 16)
    if y & 0x800000:
        y -= 0x1000000
    angle = (p[5] / 255.0) * 360.0
    return PosePacked12(x_raw=x, y_raw=y, angle_deg=angle)
