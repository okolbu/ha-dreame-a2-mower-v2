"""Tests for tools._rebuild_session_lib.samples_replay."""
from __future__ import annotations

from tools._rebuild_session_lib.samples_replay import backfill_samples


class _StubReader:
    """Tiny ProbeReader stand-in."""
    def __init__(self, store: dict):
        self._store = store
    def events_for_slot(self, siid, piid, start_ts=None, end_ts=None):
        evs = self._store.get((siid, piid), [])
        return [(t, v) for t, v in evs
                if (start_ts is None or t >= start_ts)
                and (end_ts is None or t <= end_ts)]


def test_backfill_samples_extracts_four_streams():
    reader = _StubReader({
        (3, 1): [(1000, 80), (1100, 79), (1200, 78)],     # battery
        (3, 2): [(1050, 1), (1500, 0)],                    # charging
        (2, 1): [(1000, 1), (1500, 6)],                    # state
        (2, 2): [(1100, 70), (1500, 28)],                  # error
    })
    out = backfill_samples(reader, start_ts=900, end_ts=2000)
    assert out["battery_samples"] == [[1000, 80], [1100, 79], [1200, 78]]
    assert out["charging_status_samples"] == [[1050, 1], [1500, 0]]
    assert out["state_samples"] == [[1000, 1], [1500, 6]]
    assert out["error_samples"] == [[1100, 70], [1500, 28]]


def test_backfill_samples_dedups_consecutive_identical_values():
    """Mirrors live LiveMapState.append_telemetry_sample debounce."""
    reader = _StubReader({
        (3, 1): [(1000, 80), (1050, 80), (1100, 80), (1200, 79)],
    })
    out = backfill_samples(reader, start_ts=900, end_ts=2000)
    # 80 → 80 → 80 dedups to one entry; then 79
    assert out["battery_samples"] == [[1000, 80], [1200, 79]]


def test_backfill_samples_filters_window():
    reader = _StubReader({
        (3, 1): [(500, 90), (1000, 80), (1500, 70), (2500, 60)],
    })
    out = backfill_samples(reader, start_ts=1000, end_ts=2000)
    assert out["battery_samples"] == [[1000, 80], [1500, 70]]


def test_backfill_samples_empty_streams():
    reader = _StubReader({})
    out = backfill_samples(reader, start_ts=1000, end_ts=2000)
    assert out == {
        "battery_samples": [],
        "charging_status_samples": [],
        "state_samples": [],
        "error_samples": [],
    }


def test_backfill_samples_skips_non_int_values():
    """A dict value (e.g., wrong-slot leak) is silently skipped."""
    reader = _StubReader({
        (3, 1): [(1000, 80), (1100, {"status": []}), (1200, 79)],
    })
    out = backfill_samples(reader, start_ts=900, end_ts=2000)
    assert out["battery_samples"] == [[1000, 80], [1200, 79]]
