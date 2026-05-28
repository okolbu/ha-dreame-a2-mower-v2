"""Tests for session_card.derive_render_legs."""
from __future__ import annotations

from custom_components.dreame_a2_mower.session_card import derive_render_legs


def _pt(t, x, y, role):
    return {"t": t, "x_m": x, "y_m": y, "area_m2": 0.0,
            "heading_deg": None, "task_state": 0, "role": role}


def test_role_flip_breaks_legs():
    track = [_pt(0, 0, 0, "traversal"), _pt(1, 1, 0, "traversal"),
             _pt(2, 2, 0, "mowing"), _pt(3, 3, 0, "mowing")]
    legs = derive_render_legs(track)
    assert len(legs) == 2
    assert legs[0]["role"] == "traversal"
    assert legs[0]["start_ts"] == 0 and legs[0]["end_ts"] == 1
    assert legs[1]["role"] == "mowing"
    assert legs[0]["pts"][-1] == legs[1]["pts"][0]


def test_time_gap_breaks_legs():
    # 99 s gap between idx1 and idx2 → pen-up boundary. Post-gap leg has TWO
    # points so it survives the >=2 drawable-leg filter.
    track = [_pt(0, 0, 0, "mowing"), _pt(1, 1, 0, "mowing"),
             _pt(100, 2, 0, "mowing"), _pt(101, 3, 0, "mowing")]
    legs = derive_render_legs(track, pen_up_gap_s=30.0)
    assert len(legs) == 2
    # Pen-up legs do NOT share a boundary point (no connecting stroke).
    assert legs[0]["pts"][-1] != legs[1]["pts"][0]
    assert legs[0]["pts"][-1] == (1, 0)
    assert legs[1]["pts"][0] == (2, 0)


def test_single_point_tail_leg_dropped():
    # A pen-up gap leaving a lone trailing point yields an undrawable
    # 1-point leg, which is filtered out.
    track = [_pt(0, 0, 0, "mowing"), _pt(1, 1, 0, "mowing"),
             _pt(100, 2, 0, "mowing")]
    legs = derive_render_legs(track, pen_up_gap_s=30.0)
    assert len(legs) == 1
    assert legs[0]["pts"] == [(0, 0), (1, 0)]


def test_contiguous_same_role_is_one_leg():
    track = [_pt(0, 0, 0, "mowing"), _pt(1, 1, 0, "mowing"), _pt(2, 2, 0, "mowing")]
    legs = derive_render_legs(track)
    assert len(legs) == 1
    assert len(legs[0]["pts"]) == 3


def test_empty_track():
    assert derive_render_legs([]) == []
