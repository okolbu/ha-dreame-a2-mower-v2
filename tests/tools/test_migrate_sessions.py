"""Tests for the old→new session-format converter."""
from __future__ import annotations

from tools.migrate_sessions_to_track import (
    classify,
    convert_archive,
    is_new_format,
)

# A real 33-byte s1p4 full frame (decodes to a valid MowingTelemetry).
_REAL_S1P4 = [
    206, 21, 0, 0, 0, 0, 85, 218, 1, 0, 134, 0, 85, 4, 118, 254, 86, 4,
    255, 127, 0, 128, 1, 1, 204, 13, 100, 125, 0, 73, 44, 0, 206,
]


class _FakeReader:
    def __init__(self, s1p4, s2p1):
        self._s1p4 = s1p4
        self._s2p1 = s2p1

    def events_for_slot(self, siid, piid, *, start_ts, end_ts):
        if (siid, piid) == (1, 4):
            return [(t, v) for (t, v) in self._s1p4 if start_ts <= t <= end_ts]
        if (siid, piid) == (2, 1):
            return [(t, v) for (t, v) in self._s2p1 if start_ts <= t <= end_ts]
        return []


def _pt(t, x, y, role):
    return {"t": t, "x_m": x, "y_m": y, "area_m2": 0.0,
            "heading_deg": None, "task_state": 0, "role": role}


def test_convert_strips_legs_and_adds_track_cloud():
    archive = {
        "start": 1000, "end": 2000,
        "md5": "abc",
        # legacy leg keys that MUST be removed:
        "legs": [[[0, 0]]],
        "_local_legs": [[[0, 0]]],
        "_legs_meta": [{"role": "mowing"}],
        "_mowing_legs": [],
        "_traversal_legs": [],
        # cloud nested mowing track (parse_session_summary reads map[].track):
        "map": [{"type": 0, "id": 1, "track": [[100, 0], [200, 0]]}],
    }
    reader = _FakeReader(
        s1p4=[(1001, list(_REAL_S1P4)), (1002, list(_REAL_S1P4))],
        s2p1=[(1000, 0)],
    )
    new, stats = convert_archive(archive, reader)

    # leg keys gone
    for k in ("legs", "_local_legs", "_legs_meta", "_mowing_legs", "_traversal_legs"):
        assert k not in new, k
    # track present as 7-element ROWS
    assert isinstance(new["track"], list)
    assert stats["track_points"] >= 1
    for row in new["track"]:
        assert len(row) == 7
        assert row[6] in ("mowing", "traversal")
    # cloud_track present (list of segments)
    assert isinstance(new["cloud_track"], list)
    # untouched metadata preserved
    assert new["md5"] == "abc"
    assert stats["had_legs"] is True


def test_convert_empty_window_yields_empty_track_but_clean_format():
    archive = {"start": 0, "end": 0, "_local_legs": [[[1, 1]]]}
    new, stats = convert_archive(archive, _FakeReader(s1p4=[], s2p1=[]))
    assert new["track"] == []
    assert new["cloud_track"] == []
    assert "_local_legs" not in new
    assert stats["track_points"] == 0


def test_classify_smoothing_only_no_cloud_rescue():
    # area-delta is authoritative: traversal points are NOT upgraded by any
    # cloud-proximity rescue (rescue was removed). A genuine traversal run
    # stays grey.
    track = [_pt(0, 0.0, 0.0, "traversal"), _pt(1, 1.0, 0.0, "traversal")]
    classify(track)
    assert [p["role"] for p in track] == ["traversal", "traversal"]

    # Lone stutter between two mowing → smoothed.
    track2 = [_pt(0, 0, 0, "mowing"), _pt(1, 9, 9, "traversal"), _pt(2, 0, 0, "mowing")]
    classify(track2)
    assert [p["role"] for p in track2] == ["mowing", "mowing", "mowing"]


def test_is_new_format():
    assert is_new_format({"track": [], "cloud_track": []}) is True
    assert is_new_format({"track": [], "cloud_track": [], "legs": []}) is False
    assert is_new_format({"track": []}) is False
    assert is_new_format({"_local_legs": []}) is False
