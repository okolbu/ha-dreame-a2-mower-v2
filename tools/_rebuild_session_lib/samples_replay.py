"""Backfill the four core sample arrays from a ProbeReader.

Mirrors the logic in the live coordinator's
_capture_telemetry_sample (in coordinator/_mqtt_handlers.py) and
LiveMapState.append_telemetry_sample (in live_map/state.py).
"""
from __future__ import annotations

# (siid, piid) -> field name on raw_dict
_SLOT_TO_FIELD: dict[tuple[int, int], str] = {
    (3, 1): "battery_samples",
    (3, 2): "charging_status_samples",
    (2, 1): "state_samples",
    (2, 2): "error_samples",
}


def backfill_samples(
    reader, start_ts: int, end_ts: int,
) -> dict[str, list[list[int]]]:
    """For each (siid, piid) sample slot, collect probe events in
    window, dedup adjacent identical values, return as
    `[[ts_unix, value_int], ...]`.

    Returns a dict with all four field names, even if empty.
    """
    out: dict[str, list[list[int]]] = {f: [] for f in _SLOT_TO_FIELD.values()}
    for slot, field in _SLOT_TO_FIELD.items():
        events = reader.events_for_slot(*slot, start_ts=start_ts, end_ts=end_ts)
        last_val: int | None = None
        for ts, val in events:
            try:
                v_int = int(val)
            except (TypeError, ValueError):
                continue
            if last_val is not None and last_val == v_int:
                continue
            out[field].append([int(ts), v_int])
            last_val = v_int
    return out
