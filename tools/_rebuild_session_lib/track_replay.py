"""Reconstruct the per-point `track` from probe s1p4 (position+area+heading)
+ s2p1 (task_state) events.

Mirrors the live LiveMapState.append_point classification (area-delta) and
update_task_state tagging, so rebuilt archives are byte-compatible with
live-captured ones (before the finalize classifier runs).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .wifi_replay import _coerce_blob, _load_decoder_module

_DEDUP_SQ = 0.04   # 20 cm squared — matches live append_point

# Lazily spec-loaded, cached protocol.telemetry module. We MUST NOT do a
# plain `from custom_components.dreame_a2_mower.protocol.telemetry import …`:
# that executes the package __init__.py which imports homeassistant, raising
# ModuleNotFoundError on the dev box (no HA) and silently skipping every
# session's track. _load_decoder_module loads the pure module file directly,
# bypassing the package init — same trick wifi_replay uses for decode_s1p1.
_TELEMETRY: Any = None


def _default_decoder(blob: bytes) -> tuple[float, float, float, float] | None:
    """Decode (x_m, y_m, area_m2, heading_deg) from a full s1p4 frame.

    Returns None for non-full frames (8-byte beacons carry no area/heading;
    they are skipped — a docked/idle beacon adds no trail value)."""
    global _TELEMETRY
    if _TELEMETRY is None:
        _TELEMETRY = _load_decoder_module("telemetry")
    try:
        tm = _TELEMETRY.decode_s1p4(blob)
    except ValueError:
        # InvalidS1P4Frame subclasses ValueError; 8-byte beacons / 10-byte
        # building frames / malformed frames all land here → skip the point.
        return None
    return (tm.x_m, tm.y_m, tm.area_mowed_m2, tm.heading_deg)


def reconstruct_track(
    reader: Any,
    start_ts: int,
    end_ts: int,
    *,
    _decoder: Callable[[bytes], tuple[float, float, float, float] | None] | None = None,
) -> list[dict]:
    """Return a list of track-point dicts for the session window."""
    decode = _decoder or _default_decoder
    s1p4 = reader.events_for_slot(1, 4, start_ts=start_ts, end_ts=end_ts)
    s2p1 = reader.events_for_slot(2, 1, start_ts=start_ts, end_ts=end_ts)

    timeline: list[tuple[int, str, Any]] = []
    for ts, val in s1p4:
        timeline.append((ts, "pos", val))
    for ts, val in s2p1:
        timeline.append((ts, "task", val))
    timeline.sort(key=lambda t: t[0])

    track: list[dict] = []
    last_task = -1
    last_area = 0.0
    for ts, kind, val in timeline:
        if kind == "task":
            try:
                last_task = int(val)
            except (TypeError, ValueError):
                pass
            continue
        blob = _coerce_blob(val)
        if blob is None:
            continue
        dec = decode(blob)
        if dec is None:
            continue
        x_m, y_m, area_m2, heading = dec
        if track:
            dx = x_m - track[-1]["x_m"]
            dy = y_m - track[-1]["y_m"]
            if (dx * dx + dy * dy) < _DEDUP_SQ and (ts - track[-1]["t"]) < 0.5:
                continue
        role = "mowing" if (area_m2 - last_area) > 0.0 else "traversal"
        track.append({
            "t": float(ts), "x_m": float(x_m), "y_m": float(y_m),
            "area_m2": float(area_m2), "heading_deg": float(heading),
            "task_state": last_task, "role": role,
        })
        last_area = area_m2
    return track
