"""SCHEDULE.* batch decoder.

Verified shape (g2408 fw 4.3.6_0550, 2026-05-08):
    {"d": [[id, mode, name, base64_blob], ...], "v": version}

The base64 blob carries the slot's scheduled plans. Each plan emits one
record per weekday it's scheduled on, so a "Mon+Wed 07:58" plan is two
records. Records are variable-length: 7 bytes for All-area, 8 for Zone,
9 for Edge. On decode we group records back into plans by
`(action_type, time_min, zone_id, extra_bytes)` and union weekday bits.

Record format (verified against live cloud data 2026-05-08):

    All-area (len=7, action=0):
    +------+------+------------+----------+----------+----------+------+
    | 0xAA | 0x07 | day|action | time_lo  | act|thi  | reserved | 0xED |
    +------+------+------------+----------+----------+----------+------+
        0      1        2           3          4           5        6

    Zone (len=8, action=1):
    +------+------+------------+----------+----------+----------+---------+------+
    | 0xAA | 0x08 | day|action | time_lo  | act|thi  | reserved | zone_id | 0xED |
    +------+------+------------+----------+----------+----------+---------+------+
        0      1        2           3          4           5          6        7

    Edge (len=9, action=2):
    +------+------+------------+----------+----------+----------+---------+----------+------+
    | 0xAA | 0x09 | day|action | time_lo  | act|thi  | reserved | zone_id | reserved | 0xED |
    +------+------+------------+----------+----------+----------+---------+----------+------+
        0      1        2           3          4           5          6         7        8

    byte 0:  0xAA — start sentinel
    byte 1:  total record length (7/8/9)
    byte 2:  high nibble = weekday (1=Mon, 2=Tue, ... 7=Sun)
             low nibble  = action type (0=All-area, 1=Zone, 2=Edge)
    byte 3:  time_lo (bits 7..0 of minute-of-day)
    byte 4:  high nibble = action (redundant discriminator)
             low nibble  = time_hi (bits 11..8 of minute-of-day)
    byte 5:  reserved (0x00 in observed data)
    byte 6:  0xED (All-area) or zone_id (Zone/Edge)
    byte 7:  0xED (Zone) or reserved2 / 0x00 (Edge)
    byte 8:  0xED (Edge only)

Whether a slot is currently ENABLED lives elsewhere — the blob is byte-
identical between toggled and untoggled states (verified by capturing
SCHEDULE both before and after the user flipped slots on/off in the app).

References:
    docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json
    docs/research/cloud-discovery/2026-05-08-post-schedule-toggle-batch.json
    /data/claude/homeassistant/schedule-doc.txt (user-authored ground truth)
"""
from __future__ import annotations

import base64
import binascii
import html
import logging
from typing import Any

from ..cloud_state import ScheduleData, SchedulePlan, ScheduleSlot

_LOGGER = logging.getLogger(__name__)

_RECORD_START = 0xAA
_RECORD_END = 0xED
_RECORD_TYPE = 0x07  # legacy constant; still used by encoder for All-area records

_VALID_LEN = (7, 8, 9)
_ACTION_LEN = {0: 7, 1: 8, 2: 9}


def _decode_one_record(rec: bytes) -> tuple[int, int, int, int | None, bytes] | None:
    """Decode one variable-length record into (time_min, weekday, action, zone_id, extra_bytes).

    Returns None if the record is malformed (caller drops the whole slot).
    """
    if len(rec) not in _VALID_LEN:
        return None
    rec_len = rec[1]
    if rec_len != len(rec):
        return None
    if rec[0] != _RECORD_START or rec[-1] != _RECORD_END:
        return None
    weekday = rec[2] >> 4
    action = rec[2] & 0x0F
    if not (1 <= weekday <= 7):
        return None
    if action not in _ACTION_LEN or _ACTION_LEN[action] != rec_len:
        return None
    time_min = rec[3] | ((rec[4] & 0x0F) << 8)
    if not (0 <= time_min <= 1439):
        return None
    zone_id: int | None = None
    extra_bytes = b""
    if action == 0:
        # All-area: 7 bytes total. Byte 5 is reserved; no zone_id.
        pass
    elif action == 1:
        # Zone: 8 bytes. Byte 5 reserved, byte 6 is zone_id.
        zone_id = rec[6]
    elif action == 2:
        # Edge: 9 bytes. Byte 5 reserved, byte 6 is zone_id, byte 7 reserved2.
        zone_id = rec[6]
        extra_bytes = bytes([rec[7]])
    return (time_min, weekday, action, zone_id, extra_bytes)


def _decode_blob(blob_b64: str) -> tuple[SchedulePlan, ...]:
    """Decode one slot's base64 blob into a tuple of SchedulePlans.

    Variable-length records (7/8/9 bytes by action_type). All-area=0,
    Zone=1, Edge=2. Returns () on any malformed input (logs once).
    """
    if not blob_b64:
        return ()
    try:
        raw = base64.b64decode(blob_b64, validate=True)
    except (ValueError, binascii.Error) as ex:
        _LOGGER.warning("schedule: bad base64 in slot blob: %s", ex)
        return ()
    parsed: list[tuple[int, int, int, int | None, bytes]] = []
    i = 0
    while i < len(raw):
        if raw[i] != _RECORD_START:
            _LOGGER.warning("schedule: byte %d is 0x%02x, expected 0xAA",
                            i, raw[i])
            return ()
        rec_len = raw[i + 1] if i + 1 < len(raw) else 0
        if rec_len not in _VALID_LEN or i + rec_len > len(raw):
            _LOGGER.warning("schedule: bad record len 0x%02x at offset %d",
                            rec_len, i)
            return ()
        rec = raw[i:i + rec_len]
        decoded = _decode_one_record(rec)
        if decoded is None:
            _LOGGER.warning("schedule: malformed record at offset %d: %s",
                            i, rec.hex())
            return ()
        parsed.append(decoded)
        i += rec_len
    # Group records by (action, time, zone_id, extra_bytes); union weekday bits.
    # Bit 0 = Mon, bit 6 = Sun (matches the firmware's weekday=1..7 numbering
    # by subtracting 1 to get the bit position).
    plans_by_key: dict[tuple, int] = {}
    plan_order: list[tuple] = []
    for time_min, weekday, action, zone_id, extra_bytes in parsed:
        key = (action, time_min, zone_id, extra_bytes)
        if key not in plans_by_key:
            plans_by_key[key] = 0
            plan_order.append(key)
        plans_by_key[key] |= 1 << (weekday - 1)
    return tuple(
        SchedulePlan(
            time_min=key[1],
            weekday_mask=plans_by_key[key],
            action_type=key[0],
            zone_id=key[2],
            extra_bytes=key[3],
        )
        for key in plan_order
    )


def encode_schedule_blob(plans: tuple[SchedulePlan, ...]) -> str:
    """Encode a tuple of SchedulePlans back into the base64 wire blob.

    Reverse of `_decode_blob`. Each plan emits one 7-byte record per
    weekday in its mask; the records are sorted by (weekday_asc, time_asc)
    to match the cloud's observed write convention exactly (verified
    byte-identical against the user's real slot 0 + slot 1 blobs
    2026-05-08), then concatenated and base64-encoded.

    Empty plans tuple → empty string (clears the slot).
    """
    if not plans:
        return ""
    # Validate everything BEFORE emitting any bytes.
    for plan in plans:
        if not (0 <= plan.time_min <= 1439):
            raise ValueError(f"time_min {plan.time_min} out of range 0..1439")
        if not (0 <= plan.action_type <= 0x0F):
            raise ValueError(f"action_type {plan.action_type} out of range 0..15")
        if not (0 < plan.weekday_mask <= 0x7F):
            raise ValueError(
                f"weekday_mask 0x{plan.weekday_mask:x} must have at least one of bits 0..6 set"
            )
    # Expand plans → (weekday_idx, time_min, action_type) record triples,
    # then sort by (weekday, time) to match cloud emit order.
    triples: list[tuple[int, int, int]] = []
    for plan in plans:
        for weekday_idx in range(7):
            if plan.weekday_mask & (1 << weekday_idx):
                triples.append((weekday_idx, plan.time_min, plan.action_type))
    triples.sort(key=lambda t: (t[0], t[1]))
    out = bytearray()
    for weekday_idx, time_min, action_type in triples:
        day_byte = ((weekday_idx + 1) << 4) | (action_type & 0x0F)
        time_lo = time_min & 0xFF
        time_hi = (time_min >> 8) & 0xFF
        out.extend([_RECORD_START, _RECORD_TYPE, day_byte, time_lo, time_hi, 0x00, _RECORD_END])
    return base64.b64encode(bytes(out)).decode("ascii")


def build_schedule_set_value(
    slots: tuple[ScheduleSlot, ...],
    version: int,
) -> str:
    """Build the JSON-string value for `set_property(8, 2, ...)`.

    Mirrors the read shape: `{"d": [[id, mode, name, blob_b64], ...], "v": v}`.
    The cloud stores SCHEDULE as a JSON STRING (verified by the read path —
    `SCHEDULE.0` is `"{\\"d\\":...}"`), so the returned value is a string
    suitable for direct passing to set_property.

    `mode` field has only been observed as `0`; preserved as-is.
    `name` is HTML-escape-encoded on the wire (the `&` in "Spr & Sum"
    appears as `&amp;`); we round-trip-escape here for parity.
    """
    import json as _json
    d_list = []
    for slot in slots:
        # Re-escape `&` to match the wire convention. Other HTML entities
        # (`<`, `>`, `"`) appear unescaped in the read shape, so only `&`.
        wire_name = (slot.name or "").replace("&", "&amp;")
        blob = encode_schedule_blob(slot.plans)
        d_list.append([slot.slot_id, 0, wire_name, blob])
    return _json.dumps({"d": d_list, "v": version}, separators=(",", ":"))


def parse_schedule_batch(raw: Any) -> ScheduleData:
    """Parse a SCHEDULE.* JSON-decoded payload into ScheduleData.

    Returns ScheduleData(version=0, slots=()) on any malformed input.
    Each slot's `raw_blob_b64` is preserved verbatim; `plans` carries
    the decoded mow plans.
    """
    if not isinstance(raw, dict):
        return ScheduleData(version=0, slots=())
    version = raw.get("v")
    try:
        version_int = int(version) if version is not None else 0
    except (TypeError, ValueError):
        version_int = 0
    d_list = raw.get("d")
    if not isinstance(d_list, list):
        return ScheduleData(version=version_int, slots=())
    slots: list[ScheduleSlot] = []
    for entry in d_list:
        if not isinstance(entry, list) or len(entry) < 4:
            continue
        try:
            slot_id = int(entry[0])
        except (TypeError, ValueError):
            continue
        name = html.unescape(str(entry[2]) if entry[2] is not None else "")
        blob = str(entry[3]) if entry[3] is not None else ""
        plans = _decode_blob(blob)
        slots.append(
            ScheduleSlot(
                slot_id=slot_id,
                name=name,
                raw_blob_b64=blob,
                plans=plans,
            )
        )
    return ScheduleData(version=version_int, slots=tuple(slots))
