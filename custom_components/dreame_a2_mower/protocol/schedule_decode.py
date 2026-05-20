"""SCHEDULE wire-format decoder.

Decode functions split from protocol/schedule.py (audit-B2a).
Encodes lives in schedule_encode.py.
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
        try:
            mode = int(entry[1]) if entry[1] is not None else 0
        except (TypeError, ValueError):
            mode = 0
        name = html.unescape(str(entry[2]) if entry[2] is not None else "")
        blob = str(entry[3]) if entry[3] is not None else ""
        plans = _decode_blob(blob)
        slots.append(
            ScheduleSlot(
                slot_id=slot_id,
                name=name,
                raw_blob_b64=blob,
                plans=plans,
                mode=mode,
            )
        )
    return ScheduleData(version=version_int, slots=tuple(slots))
