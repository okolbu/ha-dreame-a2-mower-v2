"""M_PATH.* regex decoder.

Format (verified 2026-05-08 against g2408 fw 4.3.6_0550):
  - Joined string is a sequence of `[x,y]` pairs separated by commas
  - The pair `[32767,-32768]` is the firmware's pen-up / segment-break sentinel
  - Coordinates are 1/10th-scale (decimeters); multiply by 10 for cloud-frame mm
  - The `M_PATH.info` byte offset (when > 0) marks the start of map 1's data;
    bytes [0:info] belong to map 0 (legacy upstream's pattern, see
    `alternatives/dreame-mower/.../map_data_parser.py:256-313`)

Use `parse_m_path_batch(raw, split_pos)` from the joined chunks +
`int(M_PATH.info)`.
"""
from __future__ import annotations

import re

from ..cloud_state import MowPathData

_PAIR_RE = re.compile(r"\[(-?\d+),(-?\d+)\]")
_SENTINEL = (32767, -32768)


def _decode_one(raw: str) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Decode one map's M_PATH region into a tuple of segments.

    Each segment is a tuple of (x_mm, y_mm) pairs in cloud-frame mm.
    """
    if not raw or not raw.strip() or raw.strip() == "[]":
        return ()
    raw_pairs = [
        (int(m.group(1)), int(m.group(2)))
        for m in _PAIR_RE.finditer(raw)
    ]
    if not raw_pairs:
        return ()
    segments: list[tuple[tuple[int, int], ...]] = []
    current: list[tuple[int, int]] = []
    for p in raw_pairs:
        if p == _SENTINEL:
            if current:
                segments.append(tuple(current))
                current = []
        else:
            # cm → mm scaling
            current.append((p[0] * 10, p[1] * 10))
    if current:
        segments.append(tuple(current))
    return tuple(segments)


def parse_m_path_batch(raw: str, split_pos: int) -> dict[int, MowPathData]:
    """Parse the joined M_PATH.* string into per-map mow trajectories.

    `raw` is the result of joining `M_PATH.0..N` in order.
    `split_pos` is `int(M_PATH.info)` (0 for single-map devices).

    Returns a dict keyed by map_id (0 and 1 when split_pos > 0).
    """
    if not raw:
        return {}
    if split_pos < 0 or split_pos >= len(raw):
        # Defensive: treat as single-map.
        return {0: MowPathData(map_id=0, segments=_decode_one(raw))}
    if split_pos == 0:
        # Single map.
        return {0: MowPathData(map_id=0, segments=_decode_one(raw))}
    # Two maps: bytes [0:split_pos] are map 0, remainder is map 1.
    return {
        0: MowPathData(map_id=0, segments=_decode_one(raw[:split_pos])),
        1: MowPathData(map_id=1, segments=_decode_one(raw[split_pos:])),
    }
