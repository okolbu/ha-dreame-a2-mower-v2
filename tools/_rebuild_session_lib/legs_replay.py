"""Reconstruct legs from probe s1p4 (position) + s2p56 (task_state)
events.

Mirrors the live integration:
  - Each s2p56 transition ``4 → 0`` (paused → running) triggers
    begin_leg in LiveMapState.
  - Each s1p4 position is appended via append_point, with:
      * Pen-up filter: jump > 5m starts a new leg
      * Dedup: skip if very close to last (20cm squared = 0.04 m²,
        matching the live ``append_point`` threshold)
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .wifi_replay import _coerce_blob, _default_position_decoder

_PEN_UP_SQ = 25.0  # 5 m squared
_DEDUP_SQ = 0.04   # 20 cm squared — matches live append_point


def _extract_sub_state(value: Any) -> int | None:
    """Extract sub_state from s2p56 value.

    s2p56 value format: ``{"status": [[task_type, sub_state]]}``
    or ``{"status": []}`` when idle.
    """
    if not isinstance(value, dict):
        return None
    status = value.get("status") or []
    if not status:
        return None
    first = status[0]
    if not isinstance(first, list) or len(first) < 2:
        return None
    try:
        return int(first[1])
    except (TypeError, ValueError):
        return None


def reconstruct_legs(
    reader: Any,
    start_ts: int,
    end_ts: int,
    *,
    _position_decoder: Callable[[bytes], tuple[float, float] | None] | None = None,
) -> list[list[list[float]]]:
    """Reconstruct legs for a session window.

    Replays s1p4 (position) and s2p56 (task_state) probe events and
    applies the same pen-up and dedup logic as the live
    ``LiveMapState.append_point`` / ``begin_leg`` pair.

    Returns a list of legs, where each leg is a list of ``[x_m, y_m]``
    points.
    """
    pos_dec = _position_decoder or _default_position_decoder

    s1p4 = reader.events_for_slot(1, 4, start_ts=start_ts, end_ts=end_ts)
    s2p56 = reader.events_for_slot(2, 56, start_ts=start_ts, end_ts=end_ts)

    # Merge into a single timeline sorted by timestamp.
    timeline: list[tuple[int, str, Any]] = []
    for ts, val in s1p4:
        timeline.append((ts, "pos", val))
    for ts, val in s2p56:
        timeline.append((ts, "task", val))
    timeline.sort(key=lambda t: t[0])

    legs: list[list[list[float]]] = [[]]
    prev_sub: int | None = None

    for _ts, kind, val in timeline:
        if kind == "task":
            sub = _extract_sub_state(val)
            if sub is None:
                continue
            # 4 → 0: recharge round-trip just completed — start new leg.
            if prev_sub == 4 and sub == 0 and legs[-1]:
                legs.append([])
            prev_sub = sub
            continue

        # Position event.
        blob = _coerce_blob(val)
        if blob is None:
            continue
        decoded = pos_dec(blob)
        if decoded is None:
            continue
        x, y = float(decoded[0]), float(decoded[1])
        cur = legs[-1]
        if cur:
            lx, ly = cur[-1]
            dx = x - lx
            dy = y - ly
            sq = dx * dx + dy * dy
            if sq > _PEN_UP_SQ:
                # Pen-up jump → new leg starting with this point.
                legs.append([[x, y]])
                continue
            if sq < _DEDUP_SQ:
                # Too close to last point — skip.
                continue
        cur.append([x, y])

    # Drop trailing empty leg (no points appended after last begin_leg).
    if legs and not legs[-1]:
        legs.pop()
    # Drop leading empty leg if no points were ever appended.
    if legs and not legs[0]:
        legs.pop(0)

    return legs
