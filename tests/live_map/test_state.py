"""Tests for live_map/state.py."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_default_state_is_inactive():
    s = LiveMapState()
    assert not s.is_active()
    assert s.total_points() == 0


def test_begin_session_clears_state():
    s = LiveMapState()
    s.legs = [[(1.0, 2.0)]]  # residue
    s.begin_session(started_unix=1000)
    assert s.is_active()
    assert s.legs == [[]]


def test_append_point_records_first_point():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 2.0, ts_unix=1010)
    assert s.legs == [[(1.0, 2.0)]]
    assert s.total_points() == 1
    assert s.last_telemetry_unix == 1010


def test_append_point_dedupes_close():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 2.0, ts_unix=1010)
    s.append_point(1.05, 2.05, ts_unix=1015)  # within 20cm
    assert s.total_points() == 1


def test_append_point_pen_up_jump_creates_new_leg():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(10.0, 0.0, ts_unix=1015)  # 10m jump > 5m
    assert len(s.legs) == 2
    assert s.total_points() == 2


def test_begin_leg_after_recharge_pause():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 1.0, ts_unix=1010)
    s.begin_leg()
    s.append_point(1.5, 1.5, ts_unix=2000)
    assert len(s.legs) == 2
    assert s.legs[0] == [(1.0, 1.0)]
    assert s.legs[1] == [(1.5, 1.5)]


def test_end_session_clears():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 1.0, ts_unix=1010)
    s.end_session()
    assert not s.is_active()
    assert s.legs == []


def test_total_distance_m_empty():
    s = LiveMapState()
    assert s.total_distance_m() == 0.0
    s.begin_session(started_unix=1000)
    assert s.total_distance_m() == 0.0


def test_total_distance_m_single_leg():
    """Three colinear points 1 m apart sum to 2 m total."""
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(1.0, 0.0, ts_unix=1011)
    s.append_point(2.0, 0.0, ts_unix=1012)
    assert abs(s.total_distance_m() - 2.0) < 1e-9


def test_total_distance_m_excludes_pen_up_gap():
    """A >5 m jump starts a fresh leg — the gap itself must NOT count
    toward session distance, otherwise recharge round-trips would
    inflate the number every cycle."""
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(1.0, 0.0, ts_unix=1011)   # leg 0: 1.0 m
    s.append_point(50.0, 0.0, ts_unix=1012)  # >5 m jump → new leg
    s.append_point(53.0, 0.0, ts_unix=1013)  # leg 1: 3.0 m
    assert len(s.legs) == 2
    assert abs(s.total_distance_m() - 4.0) < 1e-9


def test_total_distance_m_pythagorean():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(3.0, 4.0, ts_unix=1011)   # 5 m segment
    assert abs(s.total_distance_m() - 5.0) < 1e-9
