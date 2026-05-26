"""Compute traversal segments by subtracting cloud-mowing from live-trail.

The Dreame cloud's session-summary track (``boundary.track`` for full mows,
``spot[N].track`` for spot mows, ``trajectory[].track`` for edge mows) records
**only** the blades-down mowing path. The dock→mow-area cruise, mow-area→dock
return, and any recharge round-trips during the session are excluded — the
Dreame app shows the same.

The live MQTT s1p4 telemetry, on the other hand, records EVERY position the
mower observed during the session — both mowing and traversal. By subtracting
the cloud-mowing path from the live path with a spatial tolerance, we recover
the traversal-only segments. Renderers then draw the cloud path in green
(mowing) and the diff in grey (traversal), matching the pre-rewrite UX and
the user's mental model of the session.

Coverage check: point-to-polyline distance (not point-to-point). The cloud
decimates each segment to ~0.5–1 m between samples, so a local point lying
ON the path between two consecutive cloud points must be classified as
covered — point-to-point would falsely call it traversal and produce
phantom grey loops inside the mowed area. We compute distance from each
local point to the nearest segment of the cloud polyline and call it
covered when that distance is within ``tol_m``.

This module is pure (layer 2 — no HA imports) so it can be unit-tested in
isolation and reused by both the static PNG renderer and the JS replay card
(via the picked-session entity attributes).
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


def compute_traversal_from_diff(
    local_legs: Sequence[Leg],
    cloud_legs: Sequence[Leg],
    *,
    tol_m: float = 0.6,
    min_segment_pts: int = 2,
) -> list[list[Point]]:
    """Return live-trail segments NOT covered by the cloud-mowing polyline.

    Algorithm:
      1. For each segment (A, B) of every cloud leg, hash both endpoints into
         a coarse grid (cell size = tol_m). Segments register in every cell
         their bounding box touches so distance queries find them.
      2. For each local point, query the 3×3 neighbourhood of cells, dedup
         candidate segments, and compute point-to-segment distance to the
         closest one. Point is covered iff that distance ≤ tol_m.
      3. Group runs of consecutive uncovered local points into output
         traversal segments. Runs shorter than ``min_segment_pts`` are
         dropped as noise (sampling jitter near coverage edges).

    Args:
      local_legs:  All live-captured positions, as a sequence of legs where
                   each leg is a sequence of (x_m, y_m) points. Typically
                   from the archive's ``_local_legs`` field.
      cloud_legs:  Cloud-curated mowing-only segments (the parser's
                   ``SessionSummary.track_segments``).
      tol_m:       Coverage tolerance in metres — the maximum perpendicular
                   distance from a local point to the nearest cloud line
                   segment that still counts as "on the path". 0.6 m is the
                   empirical sweet spot: large enough that decimation gaps
                   on the cloud side don't punch false-traversal holes
                   inside the mowed area, small enough that genuine
                   traversal arcs (which run metres away from any mowing
                   point) get correctly identified.
      min_segment_pts:
                   Drop traversal runs shorter than this — single- or
                   two-point "stutters" near coverage edges are noise.

    Returns:
      A list of traversal segments. Each segment is a list of (x_m, y_m)
      tuples. Empty list if either input is empty (the diff is undefined
      without both sources) or if tol_m is non-positive.
    """
    if not local_legs or not cloud_legs:
        return []
    cell = float(tol_m)
    if cell <= 0:
        return []
    tol_sq = cell * cell

    # Index cloud SEGMENTS (not points) into a grid by every cell their
    # bounding box touches. Each segment is a tuple (ax, ay, bx, by); the
    # grid maps (cell_x, cell_y) → list of segments to test.
    grid: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
    segments_total = 0
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
            # Register the segment in every cell its inflated bounding box
            # touches (inflated by tol_m on each side so we catch any query
            # point within tol_m of the segment).
            cx_lo = int(min(ax, bx) // cell) - 1
            cx_hi = int(max(ax, bx) // cell) + 1
            cy_lo = int(min(ay, by) // cell) - 1
            cy_hi = int(max(ay, by) // cell) + 1
            for cx in range(cx_lo, cx_hi + 1):
                for cy in range(cy_lo, cy_hi + 1):
                    grid.setdefault((cx, cy), []).append(seg)
            segments_total += 1
            prev = (x, y)
        # Also register zero-length "segments" (single isolated points) so a
        # one-point cloud leg still provides coverage. Otherwise a cloud leg
        # of length 1 contributes nothing.
        if prev is not None and segments_total == 0:
            x, y = prev
            seg = (x, y, x, y)
            cx = int(x // cell)
            cy = int(y // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    grid.setdefault((cx + dx, cy + dy), []).append(seg)

    if not grid:
        return []

    def is_covered(px: float, py: float) -> bool:
        cx, cy = int(px // cell), int(py // cell)
        # Dedup candidates so a segment registered in multiple cells is
        # tested only once per query.
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

    out: list[list[Point]] = []
    for leg in local_legs:
        current: list[Point] = []
        for pt in leg:
            try:
                x, y = float(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError):
                continue
            if is_covered(x, y):
                if len(current) >= min_segment_pts:
                    out.append(current)
                current = []
            else:
                current.append((x, y))
        if len(current) >= min_segment_pts:
            out.append(current)
    return out
