"""SCHEDULE.* batch decoder.

Verified shape (g2408 fw 4.3.6_0550, 2026-05-08):
    {"d": [[id, mode, name, base64_blob], ...], "v": version}

The base64 blob carries the slot's scheduled plans. Each plan emits one
7-byte record per weekday it's scheduled on, so a "Mon+Wed 07:58" plan
is two records (one for Mon, one for Wed). On decode we group records
back into plans by `(action_type, time_min)` and union the weekday bits.

Record format (verified against user's cloud dump 2026-05-08):

    +------+--------+------------+-----------+-----------+----------+------+
    | 0xAA | 0x07   | day|action |  time_lo  |  time_hi  | reserved | 0xED |
    +------+--------+------------+-----------+-----------+----------+------+
        0      1          2            3           4           5        6

    byte 0:  0xAA — start sentinel
    byte 1:  0x07 — record length (7 total bytes)
    byte 2:  high nibble = weekday (1=Mon, 2=Tue, ... 7=Sun)
             low nibble  = action type (0=All-area; Zone/Edge codes TBD)
    byte 3-4: little-endian uint16, minute-of-day (0..1439)
    byte 5:  reserved/padding (always 0x00 in observed data)
    byte 6:  0xED — end sentinel

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

_RECORD_LEN = 7
_RECORD_START = 0xAA
_RECORD_END = 0xED
_RECORD_TYPE = 0x07  # length byte


def _decode_blob(blob_b64: str) -> tuple[SchedulePlan, ...]:
    """Decode one slot's base64 blob into its tuple of SchedulePlans.

    Returns an empty tuple on any decode error (unknown sentinel, bad
    weekday byte, length mismatch). Logs the failure but never raises —
    the slot's `raw_blob_b64` is still preserved on the dataclass for
    round-trip.
    """
    if not blob_b64:
        return ()
    try:
        raw = base64.b64decode(blob_b64, validate=True)
    except (ValueError, binascii.Error) as ex:
        _LOGGER.warning("schedule: bad base64 in slot blob: %s", ex)
        return ()
    if len(raw) % _RECORD_LEN != 0:
        _LOGGER.warning(
            "schedule: blob length %d is not a multiple of %d; skipping",
            len(raw), _RECORD_LEN,
        )
        return ()
    # Parse each record into a (weekday, action, time) triplet.
    parsed: list[tuple[int, int, int]] = []
    for i in range(0, len(raw), _RECORD_LEN):
        rec = raw[i : i + _RECORD_LEN]
        if rec[0] != _RECORD_START or rec[6] != _RECORD_END:
            _LOGGER.warning(
                "schedule: record %d sentinel mismatch (0x%02x..0x%02x); skipping slot",
                i // _RECORD_LEN, rec[0], rec[6],
            )
            return ()
        if rec[1] != _RECORD_TYPE:
            _LOGGER.warning(
                "schedule: record %d unexpected type 0x%02x (want 0x%02x)",
                i // _RECORD_LEN, rec[1], _RECORD_TYPE,
            )
            return ()
        weekday = rec[2] >> 4
        action = rec[2] & 0x0F
        if not (1 <= weekday <= 7):
            _LOGGER.warning(
                "schedule: record %d weekday %d out of range (1..7)",
                i // _RECORD_LEN, weekday,
            )
            return ()
        time_min = rec[3] | (rec[4] << 8)
        if not (0 <= time_min <= 1439):
            _LOGGER.warning(
                "schedule: record %d time_min %d out of range (0..1439)",
                i // _RECORD_LEN, time_min,
            )
            return ()
        parsed.append((weekday, action, time_min))
    # Group by (action, time) → union of weekday bits → SchedulePlan.
    # Bit 0 = Mon, bit 6 = Sun (matches the firmware's weekday=1..7 numbering
    # by subtracting 1 to get the bit position).
    plans_by_key: dict[tuple[int, int], int] = {}
    plan_order: list[tuple[int, int]] = []
    for weekday, action, time_min in parsed:
        key = (action, time_min)
        if key not in plans_by_key:
            plans_by_key[key] = 0
            plan_order.append(key)
        plans_by_key[key] |= 1 << (weekday - 1)
    return tuple(
        SchedulePlan(
            time_min=time_min,
            weekday_mask=plans_by_key[(action, time_min)],
            action_type=action,
        )
        for (action, time_min) in plan_order
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
