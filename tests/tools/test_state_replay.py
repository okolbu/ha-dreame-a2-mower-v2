"""Tests for tools._rebuild_session_lib.state_replay."""
from __future__ import annotations

from tools._rebuild_session_lib.state_replay import (
    charge_at_start,
    settings_snapshot_at_start,
)


class _StubReader:
    def __init__(self, store: dict):
        self._store = store
    def events_for_slot(self, siid, piid, start_ts=None, end_ts=None):
        evs = self._store.get((siid, piid), [])
        return [(t, v) for t, v in evs
                if (start_ts is None or t >= start_ts)
                and (end_ts is None or t <= end_ts)]


# === charge_at_start ===

def test_charge_at_start_returns_latest_before_window():
    reader = _StubReader({
        (3, 1): [(900, 90), (950, 88), (1100, 80)],  # 1100 is in-window
    })
    assert charge_at_start(reader, start_ts=1000) == 88


def test_charge_at_start_returns_none_when_no_prior_event():
    reader = _StubReader({(3, 1): [(1100, 80)]})
    assert charge_at_start(reader, start_ts=1000) is None


def test_charge_at_start_returns_none_when_no_events():
    reader = _StubReader({})
    assert charge_at_start(reader, start_ts=1000) is None


def test_charge_at_start_returns_value_at_exact_start_ts():
    """A sample exactly at start_ts counts as 'just before' (boundary)."""
    reader = _StubReader({(3, 1): [(1000, 85)]})
    assert charge_at_start(reader, start_ts=1000) == 85


# === settings_snapshot_at_start ===

def test_settings_snapshot_picks_latest_per_slot_before_start():
    reader = _StubReader({
        (5, 107): [(900, 100), (950, 105)],  # latest before start = 105
        (6, 1):   [(800, 1)],                  # latest before start = 1
        (2, 51):  [(1100, 5)],                 # AFTER start — ignored
    })
    snap = settings_snapshot_at_start(reader, start_ts=1000)
    assert snap.get("s5p107") == 105
    assert snap.get("s6p1") == 1
    assert "s2p51" not in snap


def test_settings_snapshot_empty_when_no_prior_events():
    reader = _StubReader({})
    assert settings_snapshot_at_start(reader, start_ts=1000) == {}


def test_settings_snapshot_handles_dict_values():
    """s6p1 carries a dict payload; preserve as-is (decode is downstream)."""
    reader = _StubReader({(6, 1): [(900, {"some": "dict"})]})
    snap = settings_snapshot_at_start(reader, start_ts=1000)
    assert snap.get("s6p1") == {"some": "dict"}
