"""Tests for per-point track reconstruction from probe events."""
from __future__ import annotations

from tools._rebuild_session_lib.track_replay import reconstruct_track


class _FakeReader:
    """Minimal stand-in exposing events_for_slot like ProbeReader."""
    def __init__(self, s1p4, s2p1):
        self._s1p4 = s1p4
        self._s2p1 = s2p1

    def events_for_slot(self, siid, piid, *, start_ts, end_ts):
        if (siid, piid) == (1, 4):
            return [(t, v) for (t, v) in self._s1p4 if start_ts <= t <= end_ts]
        if (siid, piid) == (2, 1):
            return [(t, v) for (t, v) in self._s2p1 if start_ts <= t <= end_ts]
        return []


def test_reconstruct_track_classifies_by_area():
    decoded = {
        b"\x01": (0.0, 0.0, 0.0, 0.0),    # x, y, area, heading
        b"\x02": (1.0, 0.0, 0.5, 10.0),
    }
    reader = _FakeReader(s1p4=[(1001, b"\x01"), (1002, b"\x02")], s2p1=[(1000, 0)])
    track = reconstruct_track(
        reader, start_ts=1000, end_ts=2000,
        _decoder=lambda blob: decoded[blob],
    )
    assert [p["role"] for p in track] == ["traversal", "mowing"]
    assert track[0]["task_state"] == 0
    assert track[1]["heading_deg"] == 10.0
