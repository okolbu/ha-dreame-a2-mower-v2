"""Tests for per-point track reconstruction from probe events."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools._rebuild_session_lib.track_replay import reconstruct_track

_REPO_ROOT = Path(__file__).resolve().parents[2]
# A real 33-byte s1p4 full frame (from a probe log): decodes to a valid
# MowingTelemetry (x≈0.21, area=113.37, hdg=120°).
_REAL_S1P4 = [
    206, 21, 0, 0, 0, 0, 85, 218, 1, 0, 134, 0, 85, 4, 118, 254, 86, 4,
    255, 127, 0, 128, 1, 1, 204, 13, 100, 125, 0, 73, 44, 0, 206,
]


def test_default_decoder_works_without_homeassistant():
    """The REAL _default_decoder must decode in the tool's true runtime —
    a fresh interpreter with NO homeassistant and NO test conftest stubs.

    Regression for the Task-17 bug where _default_decoder did a plain
    `from custom_components.dreame_a2_mower.protocol.telemetry import …`,
    which runs the package __init__ → `import homeassistant` →
    ModuleNotFoundError → every session's track silently skipped. The
    in-process suite can't catch it (conftest stubs homeassistant); only a
    clean subprocess reproduces the tool's real environment.
    """
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from tools._rebuild_session_lib.track_replay import _default_decoder\n"
        "r = _default_decoder(bytes(%r))\n"
        "assert r is not None and len(r) == 4, r\n"
        "print('OK', r)\n"
    ) % (str(_REPO_ROOT), _REAL_S1P4)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
    )
    assert "No module named 'homeassistant'" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.startswith("OK ("), proc.stdout


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
