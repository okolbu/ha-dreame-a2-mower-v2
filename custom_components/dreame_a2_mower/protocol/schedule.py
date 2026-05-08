"""SCHEDULE.* batch decoder (header-only).

Verified shape (g2408 fw 4.3.6_0550, 2026-05-08):
    {"d": [[id, mode, name, base64_blob], ...], "v": version}

Each slot has an opaque base64 blob whose format is unknown.
This decoder extracts the metadata (id, name, version) so the
Schedule dashboard view can list slots; blob decode is deferred
to a follow-up TODO.
"""
from __future__ import annotations

import html
from typing import Any

from ..cloud_state import ScheduleData, ScheduleSlot


def parse_schedule_batch(raw: Any) -> ScheduleData:
    """Parse a SCHEDULE.* JSON-decoded payload into ScheduleData.

    Returns ScheduleData(version=0, slots=()) on any malformed input.
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
        slots.append(ScheduleSlot(slot_id=slot_id, name=name, raw_blob_b64=blob))
    return ScheduleData(version=version_int, slots=tuple(slots))
