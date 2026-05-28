"""Tests for the finalize-stage track classifier."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.classify import classify_track


def _pt(t, x, y, role):
    return {"t": t, "x_m": x, "y_m": y, "area_m2": 0.0,
            "heading_deg": None, "task_state": 0, "role": role}


def test_cloud_rescue_upgrades_traversal_on_path():
    track = [_pt(0, 0.0, 0.0, "traversal"), _pt(1, 1.0, 0.0, "traversal")]
    cloud = [[(0.0, 0.0), (1.0, 0.0)]]
    out = classify_track(track, cloud_track=cloud, tol_m=0.6)
    assert [p["role"] for p in out] == ["mowing", "mowing"]


def test_cloud_rescue_leaves_far_traversal_grey():
    track = [_pt(0, 0.0, 5.0, "traversal"), _pt(1, 1.0, 5.0, "traversal")]
    cloud = [[(0.0, 0.0), (1.0, 0.0)]]
    out = classify_track(track, cloud_track=cloud, tol_m=0.6)
    assert [p["role"] for p in out] == ["traversal", "traversal"]


def test_smoothing_collapses_single_point_stutter():
    track = [
        _pt(0, 0.0, 0.0, "mowing"),
        _pt(1, 1.0, 0.0, "traversal"),
        _pt(2, 2.0, 0.0, "mowing"),
    ]
    out = classify_track(track, cloud_track=None)
    assert [p["role"] for p in out] == ["mowing", "mowing", "mowing"]


def test_no_cloud_keeps_area_delta_roles_then_smooths():
    track = [_pt(0, 0.0, 0.0, "traversal"), _pt(1, 1.0, 0.0, "traversal")]
    out = classify_track(track, cloud_track=None)
    assert [p["role"] for p in out] == ["traversal", "traversal"]


def test_empty_track_returns_empty():
    assert classify_track([], cloud_track=[[(0.0, 0.0)]]) == []


def test_smoothing_is_order_independent_snapshot():
    # Double-stutter region: snapshot semantics flip BOTH the lone mowing
    # (idx 3) to traversal AND the lone traversal (idx 4) to mowing, because
    # each point's neighbours are evaluated as of pass start — not affected
    # by a left-neighbour that flipped earlier in the same pass.
    track = [
        _pt(0, 0.0, 0.0, "mowing"),
        _pt(1, 1.0, 0.0, "traversal"),
        _pt(2, 2.0, 0.0, "traversal"),
        _pt(3, 3.0, 0.0, "mowing"),
        _pt(4, 4.0, 0.0, "traversal"),
        _pt(5, 5.0, 0.0, "mowing"),
    ]
    out = classify_track(track, cloud_track=None, smooth_passes=1)
    assert [p["role"] for p in out] == [
        "mowing", "traversal", "traversal", "traversal", "mowing", "mowing",
    ]
