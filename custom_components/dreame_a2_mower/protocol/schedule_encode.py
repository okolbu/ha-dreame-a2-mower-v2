"""SCHEDULE wire-format encoder.

Encode functions split from protocol/schedule.py (audit-B2a).
Decode lives in schedule_decode.py.
"""
from __future__ import annotations

import base64

from ..cloud_state import SchedulePlan, ScheduleSlot
from .schedule_decode import _ACTION_LEN, _RECORD_END, _RECORD_START


def encode_schedule_blob(plans: tuple[SchedulePlan, ...]) -> str:
    """Encode a tuple of SchedulePlans back into the base64 wire blob.

    Each plan emits one variable-length record per weekday in its mask
    (7 bytes for All-area, 8 for Zone, 9 for Edge). Records are sorted
    by (weekday_asc, time_asc) to match the cloud's emit order.
    """
    if not plans:
        return ""
    # Validate all plans before emitting any bytes.
    for plan in plans:
        if not (0 <= plan.time_min <= 1439):
            raise ValueError(f"time_min {plan.time_min} out of range 0..1439")
        if plan.action_type not in _ACTION_LEN:
            raise ValueError(f"action_type {plan.action_type} not in {{0,1,2}}")
        if plan.action_type in (1, 2) and plan.zone_id is None:
            raise ValueError(
                f"action_type {plan.action_type} requires zone_id (got None)"
            )
        if not (0 < plan.weekday_mask <= 0x7F):
            raise ValueError(
                f"weekday_mask 0x{plan.weekday_mask:x} must have bits 0..6"
            )
        if plan.action_type == 2 and len(plan.extra_bytes) != 1:
            raise ValueError(
                f"Edge plan needs exactly 1 extra byte (got {len(plan.extra_bytes)})"
            )
    # Expand → (weekday_idx, time_min, action_type, zone_id, extra_bytes).
    triples: list[tuple[int, int, int, int | None, bytes]] = []
    for plan in plans:
        for weekday_idx in range(7):
            if plan.weekday_mask & (1 << weekday_idx):
                triples.append((
                    weekday_idx, plan.time_min, plan.action_type,
                    plan.zone_id, plan.extra_bytes,
                ))
    triples.sort(key=lambda t: (t[0], t[1]))
    out = bytearray()
    for weekday_idx, time_min, action, zone_id, extra in triples:
        rec_len = _ACTION_LEN[action]
        day_byte = ((weekday_idx + 1) << 4) | (action & 0x0F)
        time_lo = time_min & 0xFF
        time_hi = (time_min >> 8) & 0x0F
        # Byte 4 high nibble carries action again (redundant, format
        # discriminator — matches cloud's emit byte-exact).
        byte4 = (action << 4) | time_hi
        rec = [_RECORD_START, rec_len, day_byte, time_lo, byte4, 0x00]
        if action == 1:
            rec.append(zone_id & 0xFF)  # type: ignore[operator]
        elif action == 2:
            rec.append(zone_id & 0xFF)  # type: ignore[operator]
            rec.append(extra[0])
        rec.append(_RECORD_END)
        assert len(rec) == rec_len, f"emit len {len(rec)} != expected {rec_len}"
        out.extend(rec)
    return base64.b64encode(bytes(out)).decode("ascii")


def build_schedule_set_value(
    slots: tuple[ScheduleSlot, ...],
    version: int,
) -> str:
    """Build the JSON-string value for the SCHEDULE.0 cloud-batch write.

    Mirrors the read shape: `{"d": [[id, mode, name, blob_b64], ...], "v": v}`.

    `mode` (entry index 1) is the slot's active/empty flag — live
    g2408 cloud emits 1 for the user's primary slot and 0 for the
    empty/secondary one. Hardcoding 0 here previously turned an
    active slot off on every save; we now round-trip it from the
    parsed slot.
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
        d_list.append([slot.slot_id, int(slot.mode), wire_name, blob])
    return _json.dumps({"d": d_list, "v": version}, separators=(",", ":"))
