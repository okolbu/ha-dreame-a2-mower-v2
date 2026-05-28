"""Spatial grid helpers for cloud-coverage classification.

The Dreame cloud's session-summary track records **only** the blades-down
mowing path.  The live MQTT s1p4 telemetry records EVERY position — both
mowing and traversal.  To classify which live points were traversal (not
covered by the cloud path) we need a fast point-to-polyline distance check.

Coverage check: point-to-polyline distance (not point-to-point). The cloud
decimates each segment to ~0.5–1 m between samples, so a local point lying
ON the path between two consecutive cloud points must be classified as
covered — point-to-point would falsely call it traversal and produce
phantom grey loops inside the mowed area. We compute distance from each
local point to the nearest segment of the cloud polyline and call it
covered when that distance is within ``tol_m``.

Public helpers (used by ``live_map/classify.py``):
  ``_build_cloud_grid`` — hash cloud segments into a coarse spatial grid.
  ``_make_coverage_check`` — return an ``is_covered(x, y) → bool`` closure.
  ``_dist_sq_point_segment`` — squared point-to-segment distance (internal).

This module is pure (layer 2 — no HA imports).
"""
from __future__ import annotations

from typing import Sequence

Point = tuple[float, float]
Leg = Sequence[Sequence[float]]  # iterable of (x, y) pairs (tuple OR list)


def _dist_sq_point_segment(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Squared distance from point P to line segment AB.

    Closed-form: project (P-A) onto (B-A), clamp the parameter to [0, 1],
    return |P - projected|².  When A == B the segment degenerates to a
    point and we return |P - A|².
    """
    abx = bx - ax
    aby = by - ay
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq <= 0.0:
        dx, dy = px - ax, py - ay
        return dx * dx + dy * dy
    apx = px - ax
    apy = py - ay
    t = (apx * abx + apy * aby) / ab_len_sq
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    cx = ax + t * abx
    cy = ay + t * aby
    dx, dy = px - cx, py - cy
    return dx * dx + dy * dy


def _build_cloud_grid(
    cloud_legs: Sequence[Leg], cell: float
) -> dict[tuple[int, int], list[tuple[float, float, float, float]]]:
    """Build a grid-hash index of every cloud SEGMENT (not point).

    Each segment registers in every cell its inflated bounding box touches
    (inflated by ``cell`` so we catch any query point within ``cell`` of
    the segment). Returns mapping cell → list of (ax, ay, bx, by) tuples.
    Single-point cloud legs register a degenerate segment at that point.
    """
    grid: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
    seg_emitted = False
    for leg in cloud_legs:
        prev: Point | None = None
        for pt in leg:
            try:
                x, y = float(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError):
                prev = None
                continue
            if prev is None:
                prev = (x, y)
                continue
            ax, ay = prev
            bx, by = x, y
            seg = (ax, ay, bx, by)
            cx_lo = int(min(ax, bx) // cell) - 1
            cx_hi = int(max(ax, bx) // cell) + 1
            cy_lo = int(min(ay, by) // cell) - 1
            cy_hi = int(max(ay, by) // cell) + 1
            for cx in range(cx_lo, cx_hi + 1):
                for cy in range(cy_lo, cy_hi + 1):
                    grid.setdefault((cx, cy), []).append(seg)
            seg_emitted = True
            prev = (x, y)
        # Single-point leg: register a degenerate self-segment.
        if prev is not None and not seg_emitted:
            x, y = prev
            seg = (x, y, x, y)
            cx = int(x // cell)
            cy = int(y // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    grid.setdefault((cx + dx, cy + dy), []).append(seg)
    return grid


def _make_coverage_check(
    grid: dict[tuple[int, int], list[tuple[float, float, float, float]]],
    cell: float,
    tol_sq: float,
):
    """Return a closure ``is_covered(x, y) -> bool`` that uses the grid."""
    def is_covered(px: float, py: float) -> bool:
        cx, cy = int(px // cell), int(py // cell)
        seen: set[tuple[float, float, float, float]] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                bucket = grid.get((cx + dx, cy + dy))
                if not bucket:
                    continue
                for seg in bucket:
                    if seg in seen:
                        continue
                    seen.add(seg)
                    if _dist_sq_point_segment(
                        px, py, seg[0], seg[1], seg[2], seg[3]
                    ) <= tol_sq:
                        return True
        return False
    return is_covered


