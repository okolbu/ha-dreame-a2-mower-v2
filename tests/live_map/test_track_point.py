"""Tests for TrackPoint + track-based LiveMapState lifecycle."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.state import (
    LiveMapState,
    TrackPoint,
)


def test_trackpoint_fields():
    p = TrackPoint(
        t=1000.5, x_m=1.0, y_m=2.0, area_m2=3.0,
        heading_deg=90.0, task_state=0, role="mowing",
    )
    assert p.t == 1000.5
    assert p.x_m == 1.0
    assert p.y_m == 2.0
    assert p.area_m2 == 3.0
    assert p.heading_deg == 90.0
    assert p.task_state == 0
    assert p.role == "mowing"


def test_default_state_is_inactive():
    s = LiveMapState()
    assert not s.is_active()
    assert s.track == []


def test_begin_session_clears_track():
    s = LiveMapState()
    s.track = [TrackPoint(t=1.0, x_m=1.0, y_m=2.0, area_m2=0.0, heading_deg=None, task_state=-1, role="traversal")]
    s.begin_session(started_unix=1000)
    assert s.is_active()
    assert s.track == []
    assert s.started_unix == 1000


def test_end_session_clears_track():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.track = [TrackPoint(t=1.0, x_m=1.0, y_m=2.0, area_m2=0.0, heading_deg=None, task_state=-1, role="traversal")]
    s.settings_snapshot = {"x": 1}
    s.end_session()
    assert not s.is_active()
    assert s.track == []
    assert s.settings_snapshot is None


def test_trackpoint_is_frozen():
    import dataclasses
    import pytest
    p = TrackPoint(t=1.0, x_m=1.0, y_m=2.0, area_m2=0.0,
                   heading_deg=None, task_state=-1, role="mowing")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.role = "traversal"
