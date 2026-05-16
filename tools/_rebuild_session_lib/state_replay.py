"""Helpers for non-time-series state derived from probe events."""
from __future__ import annotations


def charge_at_start(reader, start_ts: int) -> int | None:
    """Return the most-recent s3p1 (battery) value at or before start_ts.

    Returns None if no s3p1 event exists at or before start_ts, or
    if the value isn't parseable as an int.
    """
    events = reader.events_for_slot(3, 1, start_ts=None, end_ts=start_ts)
    if not events:
        return None
    try:
        return int(events[-1][1])
    except (TypeError, ValueError):
        return None


# Slots whose latest at-or-before-start value defines the
# settings_snapshot. These are the settings-relevant MQTT slots
# observable via the ProbeReader; captured from probe log events so
# the archive carries an authoritative view of settings in effect at
# session start.
#
# Note: distinct from the live integration's _SETTINGS_TRIPWIRE_SLOTS
# in coordinator/_property_apply.py (which is just (6, 2) — a cloud-
# refresh trigger signal, not a settings-value snapshot).
_SETTINGS_SLOTS: list[tuple[int, int]] = [
    (5, 105),
    (5, 106),
    (5, 107),
    (6, 1),
    (2, 51),
    (1, 53),
]


def settings_snapshot_at_start(reader, start_ts: int) -> dict[str, object]:
    """For each settings tripwire slot, return its most-recent value
    at or before start_ts.

    Returns dict keyed by 's<siid>p<piid>'. Slots with no prior event
    are omitted (rather than mapped to None) so the snapshot only
    contains real captured values.
    """
    snap: dict[str, object] = {}
    for siid, piid in _SETTINGS_SLOTS:
        events = reader.events_for_slot(siid, piid, start_ts=None, end_ts=start_ts)
        if not events:
            continue
        snap[f"s{siid}p{piid}"] = events[-1][1]
    return snap
