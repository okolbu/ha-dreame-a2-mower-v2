"""Tests for protocol.session_summary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.protocol.session_summary import (
    BoundaryLayer,
    ExclusionLayer,
    InvalidSessionSummary,
    Obstacle,
    SessionSummary,
    TRACK_BREAK_MARKER,
    Trajectory,
    parse_session_summary,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "session_summary_2026-04-18.json"


@pytest.fixture
def real_json() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture
def real_summary(real_json) -> SessionSummary:
    return parse_session_summary(real_json)


# -------------------- top-level shape --------------------


def test_rejects_non_dict_input():
    with pytest.raises(InvalidSessionSummary):
        parse_session_summary([])  # type: ignore[arg-type]


def test_accepts_empty_dict():
    s = parse_session_summary({})
    assert s.start_ts == 0
    assert s.boundary is None
    assert s.obstacles == ()
    assert s.exclusions == ()
    assert s.trajectories == ()


# -------------------- scalar fields from real capture --------------------


def test_scalar_fields_match_capture(real_summary):
    assert real_summary.start_ts == 1776522523
    assert real_summary.end_ts == 1776541055
    assert real_summary.duration_min == 195
    assert real_summary.mode == 100
    assert real_summary.result == 1
    assert real_summary.stop_reason == -1
    assert real_summary.md5 == "f7335acc02f19d78345cb037f8875101"
    assert real_summary.area_mowed_m2 == pytest.approx(311.33)
    assert real_summary.map_area_m2 == 383


def test_dock_converted_to_metres(real_summary):
    # Wire: [154, 2, 42] (x_cm, y_cm, heading).
    assert real_summary.dock is not None
    x_m, y_m, heading = real_summary.dock
    assert x_m == pytest.approx(1.54)
    assert y_m == pytest.approx(0.02)
    assert heading == 42


def test_dock_none_if_missing():
    s = parse_session_summary({"dock": None})
    assert s.dock is None


def test_dock_tolerates_short_list():
    s = parse_session_summary({"dock": [1, 2]})
    assert s.dock is None


# -------------------- boundary polygon --------------------


def test_boundary_layer_decoded(real_summary):
    b = real_summary.boundary
    assert isinstance(b, BoundaryLayer)
    assert b.id == 1
    assert b.name == ""
    assert b.area_m2 == pytest.approx(383.74)
    assert len(b.boundary) == 481
    # Coordinates converted cm → m. First wire point was [-470, -1408].
    assert b.boundary[0] == (-4.70, -14.08)
    # Polygon closes: last point ~= first point.
    first, last = b.boundary[0], b.boundary[-1]
    assert abs(first[0] - last[0]) < 0.5
    assert abs(first[1] - last[1]) < 0.5


def test_lawn_polygon_convenience_property(real_summary):
    assert real_summary.lawn_polygon == real_summary.boundary.boundary


def test_lawn_polygon_empty_when_no_boundary():
    s = parse_session_summary({})
    assert s.lawn_polygon == ()


# -------------------- track splitting --------------------


def test_track_split_into_segments(real_summary):
    segments = real_summary.track_segments
    # 280 breakpoint markers in 4014 samples → ≥281 segments (may be fewer if
    # consecutive breakpoints collapse into one).
    assert 200 <= len(segments) <= 400
    # No segment contains the break marker.
    for seg in segments:
        for x, y in seg:
            assert x != TRACK_BREAK_MARKER / 100.0
    # Total non-break points equals 4014 - 280 = 3734.
    total_pts = sum(len(seg) for seg in segments)
    assert total_pts == 4014 - 280


def test_track_break_splits_correctly():
    data = {
        "map": [
            {
                "id": 1,
                "type": 0,
                "name": "",
                "area": 0.0,
                "etime": 0,
                "time": 0,
                "data": [],
                "track": [
                    [100, 200],
                    [110, 210],
                    [TRACK_BREAK_MARKER, TRACK_BREAK_MARKER],
                    [300, 400],
                    [310, 410],
                    [TRACK_BREAK_MARKER, TRACK_BREAK_MARKER],
                    [500, 600],
                ],
            }
        ]
    }
    s = parse_session_summary(data)
    segs = s.track_segments
    assert len(segs) == 3
    assert segs[0] == ((1.0, 2.0), (1.1, 2.1))
    assert segs[1] == ((3.0, 4.0), (3.1, 4.1))
    assert segs[2] == ((5.0, 6.0),)


def test_consecutive_track_breaks_dont_emit_empty_segments():
    data = {
        "map": [
            {
                "id": 1,
                "type": 0,
                "data": [],
                "track": [
                    [100, 200],
                    [TRACK_BREAK_MARKER, TRACK_BREAK_MARKER],
                    [TRACK_BREAK_MARKER, TRACK_BREAK_MARKER],
                    [300, 400],
                ],
            }
        ]
    }
    s = parse_session_summary(data)
    assert len(s.track_segments) == 2


# -------------------- exclusion zones --------------------


def test_exclusion_layer_decoded(real_summary):
    ex = real_summary.exclusions
    assert len(ex) == 1
    e = ex[0]
    assert isinstance(e, ExclusionLayer)
    assert e.id == 101
    assert len(e.points) == 4
    # Wire coords were [[1417, 1605], [438, 1022], [8, 1745], [986, 2328]].
    assert e.points[0] == (14.17, 16.05)
    assert e.points[3] == (9.86, 23.28)


# -------------------- obstacles --------------------


def test_obstacles_decoded(real_summary):
    obs = real_summary.obstacles
    assert len(obs) == 7
    o0 = obs[0]
    assert isinstance(o0, Obstacle)
    assert o0.id == 1
    assert o0.type == 0
    # Wire first point [-110, 1163] → (-1.10, 11.63) m.
    assert o0.polygon[0] == (-1.10, 11.63)
    assert len(o0.polygon) == 9


# -------------------- trajectory --------------------


def test_trajectories_decoded(real_summary):
    trj = real_summary.trajectories
    assert len(trj) == 1
    t0 = trj[0]
    assert isinstance(t0, Trajectory)
    assert t0.id == (1, 0)
    assert len(t0.points) == 94


# -------------------- robustness --------------------


def test_tolerates_missing_optional_lists():
    s = parse_session_summary({"map": None, "obstacle": None, "trajectory": None})
    assert s.boundary is None
    assert s.obstacles == ()
    assert s.trajectories == ()


def test_tolerates_non_dict_entries_in_lists():
    s = parse_session_summary(
        {
            "map": [None, "nope", 42, {"id": 1, "type": 0, "data": [], "track": []}],
            "obstacle": [None, "nope"],
        }
    )
    assert s.boundary is not None
    assert s.obstacles == ()


def test_invalid_point_raises():
    data = {
        "map": [
            {
                "id": 1,
                "type": 0,
                "data": [[1]],  # too short
                "track": [],
            }
        ]
    }
    with pytest.raises(InvalidSessionSummary):
        parse_session_summary(data)
