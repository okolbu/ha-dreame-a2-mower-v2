"""s1p4 mowing telemetry decoder for Dreame A2 (g2408)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

FRAME_LENGTH = 33
FRAME_LENGTH_BEACON = 8
FRAME_LENGTH_BUILDING = 10
FRAME_DELIMITER = 0xCE


class InvalidS1P4Frame(ValueError):
    """Raised when an s1p4 frame does not match the expected shape."""


class Phase(IntEnum):
    # Byte [8] of the s1p4 frame is the mower firmware's **task-phase index**:
    # the current position in the pre-planned sub-task list for this mowing
    # job. Values advance monotonically (never revisited) and carry meaning
    # bound to the task plan itself (per-zone area-fills, then edges, …).
    # The labels below are historical placeholders from earlier incorrect
    # interpretations; keep them around only so existing references compile.
    # New code should read `phase_raw` directly. See
    # docs/research/g2408-protocol.md §"Phase byte semantics".
    #
    # Observed maximum so far: 15 (lawn with four zones + multi-pass edges).
    # Lawns with more zones or more-segmented plans will hit higher values;
    # extend this range if needed. `phase_raw` is always preserved on the
    # MowingTelemetry dataclass even when the value is outside this range.
    MOWING = 0
    TRANSIT = 1
    PHASE_2 = 2
    RETURNING = 3
    ZONE_4 = 4
    ZONE_5 = 5
    ZONE_6 = 6
    ZONE_7 = 7
    ZONE_8 = 8
    ZONE_9 = 9
    ZONE_10 = 10
    ZONE_11 = 11
    ZONE_12 = 12
    ZONE_13 = 13
    ZONE_14 = 14
    ZONE_15 = 15
    UNKNOWN = -1


@dataclass(frozen=True)
class MowingTelemetry:
    """Decoded s1p4 frame.

    Position is charger-relative, in map-scale millimetres. Both X and
    Y are produced by the apk's 20-bit-packed pose decode at frame bytes
    [1-5] (see `_decode_pose`) then multiplied by 10 per the apk's "map
    coordinate" convention, so units are uniform. Distance and area
    counters reset at the start of each mowing session.

    Historical note: versions prior to alpha.98 published `x_cm` and
    `y_mm` where Y was actually `true_mm × 16` — downstream consumers
    compensated via scattered `* 0.625` / `* 0.000625` magic factors.
    alpha.98 fixes the decode; the compensating factors are gone.
    """

    x_mm: int
    y_mm: int
    sequence: int
    phase: Phase
    phase_raw: int
    distance_m: float
    total_area_m2: float
    area_mowed_m2: float
    heading_deg: float
    # Path-point sequence counter from bytes [7-9] (uint24 LE). Ticks
    # up once per internal path-point sample — much finer granularity
    # than the s1p4 frame cadence (1 per ~1s average vs s1p4 every 3-5s).
    # Bounded well below 2^24; never resets within a session. Useful
    # for detecting dropped frames and aligning against cloud-exported
    # path data.
    trace_start_index: int
    # Task struct from frame bytes [22-31] per apk parseRobotTask.
    # On g2408 these fields may overlap with our current
    # distance_deci / total_area_cent / area_mowed_cent reads —
    # both interpretations are computed in decode_s1p4 and the
    # caller can pick whichever the field-validation effort
    # (Task 4) blesses.
    region_id: int
    task_id: int
    percent: float       # 0..100 mowing progress
    total_uint24_m2: float
    finish_uint24_m2: float

    @property
    def x_m(self) -> float:
        """X position in metres (charger-relative)."""
        return self.x_mm / 1000.0

    @property
    def y_m(self) -> float:
        """Y position in metres (charger-relative)."""
        return self.y_mm / 1000.0


@dataclass(frozen=True)
class PositionBeacon:
    """Minimal 8-byte s1p4 beacon emitted while the mower is idle/docked
    or under remote control. Only X/Y are included — phase, session counters,
    and area/distance are not transmitted in this variant.
    """

    x_mm: int
    y_mm: int

    @property
    def x_m(self) -> float:
        return self.x_mm / 1000.0

    @property
    def y_m(self) -> float:
        return self.y_mm / 1000.0


def _read_uint24_le(buf: bytes, offset: int) -> int:
    """Read a little-endian unsigned 24-bit integer from `buf` at `offset`."""
    return buf[offset] | (buf[offset + 1] << 8) | (buf[offset + 2] << 16)


def _decode_pose(data: bytes, offset: int = 1) -> tuple[int, int]:
    """Decode (x_mm, y_mm) from the 5 pose bytes at `data[offset..offset+4]`.

    Uses the apk's 20-bit signed packed representation where X and Y
    share the middle byte (different nibbles) — see
    docs/research/g2408-protocol.md §"Bytes [1-6] — position decode".

    Equivalent to the JS reference (rewritten for clarity; Python's
    arbitrary-precision << would otherwise leak the high nibble of the
    last byte past bit 31):
        x_raw = (b[o+2] << 28 | b[o+1] << 20 | b[o+0] << 12) >> 12   # 20-bit signed
        y_raw = (b[o+4] << 24 | b[o+3] << 16 | b[o+2] << 8) >> 12    # 20-bit signed

    Raw values are ×10 per the apk's "×10 for map coordinates" rule,
    producing map-scale millimetres.
    """
    b0 = data[offset + 0]
    b1 = data[offset + 1]
    b2 = data[offset + 2]
    b3 = data[offset + 3]
    b4 = data[offset + 4]
    # X: 20-bit signed — bits 0-7 = b0, 8-15 = b1, 16-19 = low nibble of b2.
    x20 = ((b2 & 0x0F) << 16) | (b1 << 8) | b0
    if x20 & 0x80000:
        x20 -= 0x100000
    # Y: 20-bit signed — bits 0-3 = high nibble of b2, 4-11 = b3, 12-19 = b4.
    y20 = (b4 << 12) | (b3 << 4) | ((b2 & 0xF0) >> 4)
    if y20 & 0x80000:
        y20 -= 0x100000
    return x20 * 10, y20 * 10


def decode_s1p4_position(data: bytes) -> PositionBeacon:
    """Extract X/Y from an 8-byte beacon, a 10-byte BUILDING variant,
    or a 33-byte full frame.

    Use this when the caller only needs the current position (e.g. live
    map overlay). For phase, session, area, or distance, call decode_s1p4
    instead — it only accepts the 33-byte form.

    10-byte variants appear while the mower is in BUILDING state (map-learn /
    zone-expand). They carry the same X/Y at the same offsets as the beacon
    plus two additional bytes at offsets [6-7] (purpose not yet decoded).
    """
    if len(data) not in (FRAME_LENGTH_BEACON, FRAME_LENGTH_BUILDING, FRAME_LENGTH):
        raise InvalidS1P4Frame(
            f"expected frame length {FRAME_LENGTH_BEACON}, "
            f"{FRAME_LENGTH_BUILDING}, or {FRAME_LENGTH}, "
            f"got {len(data)}"
        )
    if data[0] != FRAME_DELIMITER or data[-1] != FRAME_DELIMITER:
        raise InvalidS1P4Frame(
            f"expected 0x{FRAME_DELIMITER:02X} delimiters at first and last byte"
        )
    x_mm, y_mm = _decode_pose(data, offset=1)
    return PositionBeacon(x_mm=x_mm, y_mm=y_mm)


def decode_s1p4(data: bytes) -> MowingTelemetry:
    if len(data) != FRAME_LENGTH:
        raise InvalidS1P4Frame(
            f"expected frame length {FRAME_LENGTH}, got {len(data)}"
        )
    if data[0] != FRAME_DELIMITER or data[-1] != FRAME_DELIMITER:
        raise InvalidS1P4Frame(
            f"expected 0x{FRAME_DELIMITER:02X} delimiters at [0] and [32]"
        )
    x_mm, y_mm = _decode_pose(data, offset=1)
    seq = struct.unpack_from("<H", data, 6)[0]
    # Path-point sequence counter (apk startIndex, validated on g2408:
    # 14,684 consecutive-frame transitions show 5,796 increments vs 10
    # decrements, no large jumps, no INT24 saturation).
    trace_start_index = _read_uint24_le(data, 7)
    # Heading angle (0..255 → 0..360°), dock-relative frame. Confirmed
    # 2026-04-24 by cross-correlating 5586 consecutive-frame samples from
    # probe_log_20260419_130434.jsonl: motion direction derived from
    # (dx, dy) between frames agrees with byte[6]/255*360 at median error
    # 13°, 54% under 15°, 67% under 30° — linear decode holds. Outliers
    # cluster on pivot turns where motion vector is unreliable. See
    # /data/claude/homeassistant/heading_correlate.py for the validator.
    #
    # Bytes [6-7] overlap with the `sequence` little-endian uint16 read
    # above; both interpretations are exposed so downstream code can pick.
    # The motion-correlation result above is strong enough that byte[6] is
    # definitely NOT part of a u16 sequence counter as-is.
    heading_byte = data[6]
    heading_deg = (heading_byte / 255.0) * 360.0
    phase_raw = data[8]
    phase = Phase(phase_raw) if phase_raw in Phase._value2member_map_ else Phase.UNKNOWN
    distance_deci = struct.unpack_from("<H", data, 24)[0]
    total_area_cent = struct.unpack_from("<H", data, 26)[0]
    area_mowed_cent = struct.unpack_from("<H", data, 29)[0]
    # apk parseRobotTask: payload bytes [22-31] of the frame.
    # Interpreted as a 10-byte sub-struct starting at frame[22]:
    #   [22] regionId (uint8)
    #   [23] taskId (uint8)
    #   [24-25] percent ÷ 100 → %
    #   [26-28] total m² × 100 (uint24_le)
    #   [29-31] finish m² × 100 (uint24_le)
    # NOTE: bytes [24-25] overlap with `distance_deci` above, and bytes
    # [26-27] / [29-30] overlap with `total_area_cent` / `area_mowed_cent`.
    # The legacy reads are LEFT IN PLACE; both interpretations are exposed
    # so downstream code can pick whichever the field-validation effort
    # (Task 4) blesses. Lawns > 655 m² truncate under the uint16 reads but
    # survive under the uint24 reads.
    region_id = data[22]
    task_id = data[23]
    percent_raw = struct.unpack_from("<H", data, 24)[0]
    percent = percent_raw / 100.0
    total_u24_cent = _read_uint24_le(data, 26)
    finish_u24_cent = _read_uint24_le(data, 29)
    return MowingTelemetry(
        x_mm=x_mm,
        y_mm=y_mm,
        sequence=seq,
        phase=phase,
        phase_raw=phase_raw,
        distance_m=distance_deci / 10.0,
        total_area_m2=total_area_cent / 100.0,
        area_mowed_m2=area_mowed_cent / 100.0,
        heading_deg=heading_deg,
        trace_start_index=trace_start_index,
        region_id=region_id,
        task_id=task_id,
        percent=percent,
        total_uint24_m2=total_u24_cent / 100.0,
        finish_uint24_m2=finish_u24_cent / 100.0,
    )
