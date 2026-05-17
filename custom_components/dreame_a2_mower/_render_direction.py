"""Infer dominant mow direction from cloud track_segments.

The direction is used to render the pre-start stripe overlay (P3 of
render-styling design). Pure function: takes mm-coord segments, returns
degrees in [0, 180) or None.
"""
from __future__ import annotations

import math

MIN_SEGMENT_M: float = 0.5  # 50cm — below this, segment is too short to be a "pass"


def infer_mow_direction(
    track_segments: list[list[tuple[float, float]]],
) -> int | None:
    """Length-weighted circular mean of segment directions (mod 180).

    Segments below MIN_SEGMENT_M are ignored. Returns degrees in [0, 180)
    or None when no qualifying segment exists.
    """
    sin_sum = 0.0
    cos_sum = 0.0
    weight_sum = 0.0
    for seg in track_segments:
        if len(seg) < 2:
            continue
        x0, y0 = seg[0]
        x1, y1 = seg[-1]
        dx = x1 - x0
        dy = y1 - y0
        length_m = math.hypot(dx, dy) / 1000.0
        if length_m < MIN_SEGMENT_M:
            continue
        # Direction mod 180 — multiply angle by 2 so 0° and 180° collapse,
        # take the circular mean, then halve at the end.
        angle = math.atan2(dy, dx)  # -pi..pi
        if angle < 0:
            angle += math.pi  # collapse to [0, pi)
        doubled = 2 * angle
        sin_sum += math.sin(doubled) * length_m
        cos_sum += math.cos(doubled) * length_m
        weight_sum += length_m
    if weight_sum == 0:
        return None
    mean_doubled = math.atan2(sin_sum, cos_sum)
    if mean_doubled < 0:
        mean_doubled += 2 * math.pi
    mean = mean_doubled / 2  # back to [0, pi)
    return int(round(math.degrees(mean))) % 180


# Mowing pattern mode values (per select.py:1624
# DreameA2PerMapMowingDirectionModeSelect._OPTIONS):
#   0 = "Striped"     → same direction as last
#   1 = "Crisscross"  → last + 45° (mod 180)
#   2 = "Chequerboard"→ last + 90° (mod 180)
MOWING_PATTERN_STRIPED = 0
MOWING_PATTERN_CRISSCROSS = 1
MOWING_PATTERN_CHEQUER = 2


def next_direction(
    *,
    last_direction_deg: int | None,
    mode: int | None,
) -> int:
    """Compute the next mow stripe direction in degrees [0, 180)."""
    if last_direction_deg is None:
        return 0
    if mode == MOWING_PATTERN_CRISSCROSS:
        return (last_direction_deg + 45) % 180
    if mode == MOWING_PATTERN_CHEQUER:
        return (last_direction_deg + 90) % 180
    # Striped (or unknown) — same as last.
    return last_direction_deg
