"""Tests for session_card trail/legs assembly from the per-point track."""
from __future__ import annotations

from custom_components.dreame_a2_mower.session_card import _summary_trail_legs


def _pt(t, x, y, role, area=0.0):
    return {"t": t, "x_m": x, "y_m": y, "area_m2": area,
            "heading_deg": None, "task_state": 0, "role": role}


def test_legs_timeline_built_from_track():
    raw = {"track": [
        _pt(0, 0, 0, "traversal"), _pt(1, 1, 0, "traversal"),
        _pt(2, 2, 0, "mowing", area=0.5), _pt(3, 3, 0, "mowing", area=1.0),
    ]}
    out = _summary_trail_legs(raw, summary=None, map_projection={"width_px": 10})
    tl = out["legs_timeline"]
    assert [leg["role"] for leg in tl] == ["traversal", "mowing"]
    assert out["track_first_ts"] == 0
    assert out["track_last_ts"] == 3
    assert out["map_projection"] == {"width_px": 10}


def test_empty_track_yields_empty_timeline():
    out = _summary_trail_legs({"track": []}, summary=None, map_projection=None)
    assert out["legs_timeline"] == []
    assert out["track_first_ts"] is None
    assert out["track_last_ts"] is None
