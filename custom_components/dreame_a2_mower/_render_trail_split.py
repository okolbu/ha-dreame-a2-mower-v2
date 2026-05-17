"""Pure splitter: local trail legs ∪ cloud mowing segments → (mowing, traversal).

The integration captures TWO views of motion:
- ``_local_legs``: full per-tick s1p4 trail samples; includes dock-return,
  cross-map traversal, AND mowing strokes.
- cloud ``track_segments``: cloud-curated, mowing-only fragments.

The render layers want to draw mowing strokes in light green and
traversal in grey-on-top. This module classifies each local-leg point
as mowing (overlaps the cloud) or traversal (doesn't), preserving
visual continuity at the boundary.
"""
from __future__ import annotations

from typing import Iterable


class _CloudIndex:
    """Two-tier spatial index for cloud points.

    Tier 1 — exact set: O(1) lookup for points that appear verbatim in the
    cloud (the common case — local trail points are decoded from the same
    s1p4 binary stream as cloud segment endpoints, so many will match
    exactly).

    Tier 2 — grid hash with distance verification: for points that miss
    the exact set, quantise to a grid of cell-size ``tol_mm`` and probe the
    cell plus its eight neighbours.  Each candidate bucket holds the actual
    cloud coordinates so the final check is a true Euclidean distance
    comparison (≤ tol_mm).  This prevents the naive bucket-only approach from
    false-positiving on sub-tolerance coordinates that all hash to the same
    coarse cell.
    """

    def __init__(
        self,
        cloud_segments: Iterable[Iterable[tuple[float, float]]],
        tol_mm: float,
    ) -> None:
        self._exact: set[tuple[float, float]] = set()
        # grid: bucket → list of (x, y) cloud points in that cell
        self._grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
        self._tol = tol_mm
        self._tol_sq = tol_mm * tol_mm
        self._q = max(1.0, tol_mm)
        for seg in cloud_segments:
            for pt in seg:
                self._exact.add(pt)
                bkt = self._bucket(pt)
                if bkt not in self._grid:
                    self._grid[bkt] = []
                self._grid[bkt].append(pt)

    def _bucket(self, pt: tuple[float, float]) -> tuple[int, int]:
        q = self._q
        return (int(pt[0] / q), int(pt[1] / q))

    def __bool__(self) -> bool:
        return bool(self._exact)

    def contains(self, pt: tuple[float, float]) -> bool:
        """Return True if *pt* is an exact cloud point or within ``tol_mm``."""
        if pt in self._exact:
            return True
        if self._tol <= 0.0:
            return False
        px, py = pt
        bx, by = self._bucket(pt)
        tol_sq = self._tol_sq
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                bucket = (bx + dx, by + dy)
                if bucket not in self._grid:
                    continue
                for cx, cy in self._grid[bucket]:
                    if (px - cx) ** 2 + (py - cy) ** 2 <= tol_sq:
                        return True
        return False


def split_trail(
    *,
    local_legs: list[list[tuple[float, float]]],
    cloud_segments: list[list[tuple[float, float]]],
    tol_mm: float = 0.0,
) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
    """Return (mowing_segments, traversal_segments).

    Decision rules:
    - No local legs → every cloud segment is mowing.
    - No cloud segments → every local leg is traversal (cloud is the
      authoritative "this was a cut" signal; without it we can't tell).
    - Otherwise: walk each local leg, mark each point as cloud-or-not,
      split into contiguous mowing runs and contiguous non-cloud runs.
      Non-cloud runs prepend the last mowing point as their start so the
      visual line stays continuous at the boundary.
    """
    if not local_legs:
        return ([list(s) for s in cloud_segments], [])
    if not cloud_segments:
        return ([], [list(leg) for leg in local_legs])

    cloud_idx = _CloudIndex(cloud_segments, tol_mm)
    mowing: list[list[tuple[float, float]]] = []
    traversal: list[list[tuple[float, float]]] = []

    for leg in local_legs:
        if not leg:
            continue
        cur_mode: bool | None = None  # True=mowing, False=traversal
        cur_run: list[tuple[float, float]] = []
        last_mowing_pt: tuple[float, float] | None = None

        for pt in leg:
            is_mow = cloud_idx.contains(pt)
            if cur_mode is None:
                cur_mode = is_mow
                cur_run = [pt]
                if is_mow:
                    last_mowing_pt = pt
                continue
            if is_mow == cur_mode:
                cur_run.append(pt)
                if is_mow:
                    last_mowing_pt = pt
                continue
            # Mode flip — flush current run, start new one.
            if cur_mode:
                mowing.append(cur_run)
            else:
                traversal.append(cur_run)
            # Bridge: traversal runs always start from the previous
            # mowing point (visual continuity); mowing runs start fresh.
            if is_mow:
                cur_run = [pt]
                last_mowing_pt = pt
            else:
                cur_run = [last_mowing_pt, pt] if last_mowing_pt else [pt]
            cur_mode = is_mow
        # Flush the final run.
        if cur_mode is True:
            mowing.append(cur_run)
        elif cur_mode is False:
            traversal.append(cur_run)

    return mowing, traversal
