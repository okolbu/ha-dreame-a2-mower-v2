"""Compute traversal segments + chronological timeline by subtracting
cloud-mowing from live-trail.

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


def compute_legs_timeline_from_diff(
    local_legs: Sequence[Leg],
    cloud_legs: Sequence[Leg],
    *,
    tol_m: float = 0.6,
    min_segment_pts: int = 2,
) -> list[dict]:
    """Walk local_legs point-by-point and emit a chronological timeline of
    ``{"role": "mowing"|"traversal", "pts": [(x,y), ...]}`` records.

    For each local point, the cloud polyline is queried for coverage
    (point-to-segment distance ≤ tol_m). Contiguous runs of points with
    the same coverage status form one timeline record; a flip in coverage
    closes the current record and starts a new one. Each local leg starts
    a fresh run (pen-up boundaries don't bridge across legs).

    The animation can replay the trail in chronological order by walking
    this timeline: dock-out cruise (traversal grey) → spot mowing (green)
    → dock-return cruise (traversal grey), in that order.

    Runs shorter than ``min_segment_pts`` are dropped as noise.

    Args:
      local_legs:  All live-captured positions, as a sequence of legs.
      cloud_legs:  Cloud-curated mowing-only segments.
      tol_m:       Coverage tolerance in metres (point-to-polyline).
      min_segment_pts:
                   Drop runs shorter than this — sub-2-point stutters near
                   coverage edges are noise.

    Returns:
      A list of timeline records. Empty list when ``local_legs`` is
      empty. When ``cloud_legs`` is empty every record gets role="mowing"
      (no cover info, default to mowing — the legacy paint-all-green
      fallback for archives with local only).
    """
    if not local_legs:
        return []
    cell = float(tol_m)
    if cell <= 0:
        # Fallback: everything is mowing, just emit each leg as one record.
        out: list[dict] = []
        for leg in local_legs:
            pts = [
                (float(p[0]), float(p[1]))
                for p in leg
                if isinstance(p, (list, tuple)) and len(p) >= 2
            ]
            if len(pts) >= min_segment_pts:
                out.append({"role": "mowing", "pts": pts})
        return out
    if not cloud_legs:
        out2: list[dict] = []
        for leg in local_legs:
            pts = []
            for p in leg:
                try:
                    pts.append((float(p[0]), float(p[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            if len(pts) >= min_segment_pts:
                out2.append({"role": "mowing", "pts": pts})
        return out2

    tol_sq = cell * cell
    grid = _build_cloud_grid(cloud_legs, cell)
    if not grid:
        return [
            {"role": "mowing", "pts": [
                (float(p[0]), float(p[1]))
                for p in leg
                if isinstance(p, (list, tuple)) and len(p) >= 2
            ]}
            for leg in local_legs
            if leg
        ]
    is_covered = _make_coverage_check(grid, cell, tol_sq)

    timeline: list[dict] = []
    for leg in local_legs:
        current_role: str | None = None
        current_pts: list[Point] = []
        for pt in leg:
            try:
                x, y = float(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError):
                continue
            role = "mowing" if is_covered(x, y) else "traversal"
            if role != current_role:
                if current_pts and len(current_pts) >= min_segment_pts:
                    timeline.append({"role": current_role, "pts": current_pts})
                # Bridge: include the boundary point in BOTH runs so the
                # mowing and traversal polylines visually touch (no gap at
                # the role flip).
                current_pts = (
                    [current_pts[-1], (x, y)] if current_pts else [(x, y)]
                )
                current_role = role
            else:
                current_pts.append((x, y))
        if current_pts and len(current_pts) >= min_segment_pts:
            timeline.append({"role": current_role, "pts": current_pts})
    return timeline


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

    grid = _build_cloud_grid(cloud_legs, cell)
    if not grid:
        return []
    is_covered = _make_coverage_check(grid, cell, tol_sq)

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
