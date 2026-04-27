"""Geometry helpers for cloud-map JSON (MAP.*) parsing.

The Dreame cloud stores some zones as axis-aligned polygons plus a
separate ``angle`` field (degrees) describing rotation around the
polygon centroid. Rendering without applying the rotation yields the
canonical "axis-aligned rectangle that's supposed to be at 30°" bug.

These helpers are pure — no imports from the HA runtime — so they're
straightforward to cover with unit tests.
"""

from __future__ import annotations

import math
from typing import Iterable, List


def _rotate_path_around_centroid(
    path: Iterable[dict], angle_deg: float | None
) -> List[dict]:
    """Return a new list of ``{"x", "y"}`` dicts rotated around the
    polygon centroid by ``angle_deg``.

    Pass-throughs:
    - ``angle_deg`` is ``None`` or ``0`` → returns the points unchanged
      (avoids float drift from a pointless rotate).
    - Empty or malformed path → returns it as-is.

    Rotation sense is the same as the Dreame app's rendering: positive
    angle is counter-clockwise in the cloud's X/Y frame.
    """
    pts = [p for p in path if isinstance(p, dict) and "x" in p and "y" in p]
    if not pts:
        return list(path)
    if not angle_deg:
        # Return a clean copy so callers can mutate freely.
        return [{"x": p["x"], "y": p["y"]} for p in pts]

    xs = [float(p["x"]) for p in pts]
    ys = [float(p["y"]) for p in pts]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    theta = math.radians(float(angle_deg))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    out: List[dict] = []
    for x, y in zip(xs, ys):
        dx = x - cx
        dy = y - cy
        # Standard rotation about centroid.
        rx = cx + dx * cos_t - dy * sin_t
        ry = cy + dx * sin_t + dy * cos_t
        out.append({"x": rx, "y": ry})
    return out
