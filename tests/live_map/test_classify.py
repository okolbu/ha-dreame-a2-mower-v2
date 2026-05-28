"""Tests for the finalize-stage track classifier (smoothing only).

Area-delta (set at append/reconstruction) is authoritative; classify_track
only smooths isolated single-point role stutters. Cloud-coverage rescue was
removed — see live_map/classify.py for why.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.classify import classify_track


def _pt(t, x, y, role):
    return {"t": t, "x_m": x, "y_m": y, "area_m2": 0.0,
            "heading_deg": None, "task_state": 0, "role": role}


def test_smoothing_collapses_single_point_stutter():
    track = [
        _pt(0, 0.0, 0.0, "mowing"),
        _pt(1, 1.0, 0.0, "traversal"),  # lone stutter between two mowing
        _pt(2, 2.0, 0.0, "mowing"),
    ]
    out = classify_track(track)
    assert [p["role"] for p in out] == ["mowing", "mowing", "mowing"]


def test_smoothing_is_order_independent_snapshot():
    # Double-stutter: snapshot semantics flip BOTH the lone mowing (idx 3) to
    # traversal AND the lone traversal (idx 4) to mowing, evaluating neighbours
    # as of pass start (not affected by a left-neighbour flipped earlier).
    track = [
        _pt(0, 0.0, 0.0, "mowing"),
        _pt(1, 1.0, 0.0, "traversal"),
        _pt(2, 2.0, 0.0, "traversal"),
        _pt(3, 3.0, 0.0, "mowing"),
        _pt(4, 4.0, 0.0, "traversal"),
        _pt(5, 5.0, 0.0, "mowing"),
    ]
    out = classify_track(track, smooth_passes=1)
    assert [p["role"] for p in out] == [
        "mowing", "traversal", "traversal", "traversal", "mowing", "mowing",
    ]


def test_area_delta_runs_preserved_through_smoothing():
    # A genuine contiguous traversal run (e.g. a cross-area move) must survive —
    # smoothing only removes 1-point stutters, never multi-point runs.
    track = [
        _pt(0, 0, 0, "mowing"),
        _pt(1, 1, 0, "traversal"),
        _pt(2, 2, 0, "traversal"),
        _pt(3, 3, 0, "traversal"),
        _pt(4, 4, 0, "mowing"),
    ]
    out = classify_track(track)
    assert [p["role"] for p in out] == [
        "mowing", "traversal", "traversal", "traversal", "mowing",
    ]


def test_empty_track_returns_empty():
    assert classify_track([]) == []
