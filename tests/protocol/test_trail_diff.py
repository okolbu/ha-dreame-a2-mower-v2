"""Tests for protocol.trail_diff — compute_traversal_from_diff."""
from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.trail_diff import (
    compute_traversal_from_diff,
)


def test_returns_empty_when_no_cloud():
    """Without cloud_legs the diff is undefined — fall back to caller's
    other source (e.g., archive _traversal_legs)."""
    local = [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]
    assert compute_traversal_from_diff(local, []) == []


def test_returns_empty_when_no_local():
    """Without local_legs there's nothing to diff against."""
    cloud = [[(0.0, 0.0), (1.0, 0.0)]]
    assert compute_traversal_from_diff([], cloud) == []


def test_fully_covered_local_produces_no_traversal():
    """When every local point is within tol of a cloud point, the diff is
    empty — the live trail was JUST the mowing."""
    cloud = [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]]
    local = [[(0.0, 0.05), (1.05, -0.02), (2.0, 0.1), (3.0, 0.0)]]
    out = compute_traversal_from_diff(local, cloud, tol_m=0.5)
    assert out == []


def test_uncovered_segment_extracted_as_traversal():
    """Local points far from any cloud point form a traversal segment."""
    cloud = [[(10.0, 10.0), (11.0, 10.0), (12.0, 10.0)]]
    # local path: starts at dock (far from cloud), enters mow area, exits
    local = [[
        (0.0, 0.0),    # dock — far from cloud
        (2.0, 2.0),    # cruising
        (5.0, 5.0),    # still cruising
        (10.0, 10.0),  # entering mow zone
        (11.0, 10.0),  # mowing (covered)
        (12.0, 10.0),  # mowing (covered)
        (8.0, 8.0),    # cruising back
        (4.0, 4.0),    # cruising back
        (0.0, 0.0),    # dock
    ]]
    out = compute_traversal_from_diff(local, cloud, tol_m=0.5)
    # Two traversal segments: dock→mow-entry and mow-exit→dock.
    # Critical UX detail: the two segments must remain SEPARATE polylines
    # in the output list — the renderer iterates segments independently
    # so no line is drawn between mow-exit (12, 10) and the start of the
    # return cruise (8, 8). Connecting them would produce a phantom grey
    # line straight through the mowing area.
    assert len(out) == 2
    assert out[0] == [(0.0, 0.0), (2.0, 2.0), (5.0, 5.0)]
    assert out[1] == [(8.0, 8.0), (4.0, 4.0), (0.0, 0.0)]


def test_single_uncovered_point_filtered_out():
    """Default min_segment_pts=2 — a single uncovered point between two
    covered runs is noise (sampling jitter near coverage edges), not a real
    traversal segment."""
    cloud = [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]]
    local = [[(0.0, 0.0), (1.0, 0.0), (1.5, 5.0), (2.0, 0.0), (3.0, 0.0)]]
    out = compute_traversal_from_diff(local, cloud, tol_m=0.5)
    assert out == []  # the (1.5, 5.0) singleton is dropped


def test_accepts_list_pairs_not_just_tuples():
    """raw_dict[_local_legs] is JSON-round-tripped → inner pairs are lists,
    not tuples. The diff must handle both."""
    cloud = [[[0.0, 0.0]]]
    local = [[[10.0, 10.0], [11.0, 11.0]]]
    out = compute_traversal_from_diff(local, cloud, tol_m=0.5)
    assert out == [[(10.0, 10.0), (11.0, 11.0)]]


def test_tolerance_controls_coverage_radius():
    """At tol=0.1 nothing is covered (points 0.2 m apart). At tol=0.3 they are."""
    cloud = [[(0.0, 0.0)]]
    local = [[(0.2, 0.0), (0.4, 0.0)]]
    assert len(compute_traversal_from_diff(local, cloud, tol_m=0.1)) == 1
    assert compute_traversal_from_diff(local, cloud, tol_m=0.5) == []


def test_multi_leg_local_preserves_leg_breaks():
    """A pen-up break in the local trail starts a new traversal segment,
    not continued with the previous."""
    cloud = [[(5.0, 5.0), (5.0, 6.0)]]
    local = [
        [(0.0, 0.0), (1.0, 0.0)],          # leg 1 — all uncovered
        [(2.0, 0.0), (3.0, 0.0), (4.0, 0.0)],  # leg 2 — all uncovered
    ]
    out = compute_traversal_from_diff(local, cloud, tol_m=0.5)
    assert len(out) == 2
    assert out[0] == [(0.0, 0.0), (1.0, 0.0)]
    assert out[1] == [(2.0, 0.0), (3.0, 0.0), (4.0, 0.0)]


def test_grid_cell_neighbours_handled_correctly():
    """Cloud point in adjacent cell (not the same cell as query) still
    counts as cover. Bug class: only checking the home cell."""
    cloud = [[(1.0, 1.0)]]  # cell (2, 2) at tol=0.5
    # Query at (0.9, 0.9) — cell (1, 1), NEIGHBOUR of (2, 2). Distance = 0.14 m.
    local = [[(0.9, 0.9), (0.85, 0.85), (0.95, 0.95)]]
    out = compute_traversal_from_diff(local, cloud, tol_m=0.5)
    assert out == []  # all 3 points within 0.5 m of (1.0, 1.0)


def test_tol_zero_returns_empty_safely():
    """Defensive: tol_m=0 would collapse the grid hash. Return empty rather
    than divide-by-zero."""
    cloud = [[(0.0, 0.0)]]
    local = [[(1.0, 1.0), (2.0, 2.0)]]
    assert compute_traversal_from_diff(local, cloud, tol_m=0.0) == []
