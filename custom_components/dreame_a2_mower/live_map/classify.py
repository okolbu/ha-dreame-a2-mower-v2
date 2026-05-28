"""Finalize-stage track classifier.

Stage 1 (area-delta) runs inline in LiveMapState.append_point. This module
is stage 2: cloud-coverage rescue + smoothing, applied once at finalize when
the full track and the cloud session-summary path are both available.

Pure (layer 2 — no HA imports) so it is unit-testable and reusable by the
probe-log rebuild tool.
"""
from __future__ import annotations

from typing import Any, Sequence

from ..protocol.trail_diff import _build_cloud_grid, _make_coverage_check


def classify_track(
    track: list[dict[str, Any]],
    cloud_track: Sequence[Sequence[Sequence[float]]] | None,
    *,
    tol_m: float = 0.6,
    smooth_passes: int = 3,
) -> list[dict[str, Any]]:
    """Refine per-point ``role`` (returns the same list, mutated in place).

    1. Cloud rescue: any point flagged "traversal" that lies within tol_m of
       a cloud mowing segment is upgraded to "mowing".
    2. Smoothing: any point whose role differs from BOTH neighbours flips to
       the neighbour role. Run smooth_passes times.

    track points are plain dicts with at least keys x_m, y_m, role.
    """
    if not track:
        return track

    if cloud_track:
        cell = float(tol_m)
        grid = _build_cloud_grid(cloud_track, cell)
        if grid:
            is_covered = _make_coverage_check(grid, cell, cell * cell)
            for p in track:
                if p["role"] == "traversal" and is_covered(p["x_m"], p["y_m"]):
                    p["role"] = "mowing"

    for _ in range(max(0, smooth_passes)):
        roles = [p["role"] for p in track]  # snapshot — order-independent pass
        changed = False
        for i in range(1, len(track) - 1):
            if roles[i - 1] == roles[i + 1] and track[i]["role"] != roles[i - 1]:
                track[i]["role"] = roles[i - 1]
                changed = True
        if not changed:
            break
    return track
