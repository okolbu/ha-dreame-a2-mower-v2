"""Tests for tools._rebuild_session_lib.wifi_replay."""
from __future__ import annotations

from tools._rebuild_session_lib.wifi_replay import reconstruct_wifi_samples


class _StubReader:
    def __init__(self, store: dict):
        self._store = store

    def events_for_slot(self, siid, piid, start_ts=None, end_ts=None):
        evs = self._store.get((siid, piid), [])
        return [(t, v) for t, v in evs
                if (start_ts is None or t >= start_ts)
                and (end_ts is None or t <= end_ts)]


def _hb_blob_with_rssi(rssi: int) -> list[int]:
    """Build a 20-byte heartbeat blob (as probe list-of-int) with the
    given RSSI byte (signed at index 17 per protocol/heartbeat.py).

    Blob layout requires 0xCE delimiter at [0] and [19].
    """
    blob = bytearray(20)
    blob[0] = 0xCE   # FRAME_DELIMITER
    blob[19] = 0xCE  # FRAME_DELIMITER
    blob[17] = rssi & 0xFF  # signed byte; both signs OK for these values
    return list(blob)


def test_reconstruct_empty_when_no_heartbeats():
    reader = _StubReader({})
    out = reconstruct_wifi_samples(reader, start_ts=1000, end_ts=2000)
    assert out == []


def test_reconstruct_pairs_heartbeat_with_position():
    """Heartbeat at t=1100 should pair with the most recent s1p4
    position at t=1050."""
    reader = _StubReader({
        (1, 1): [(1100, _hb_blob_with_rssi(186))],  # 186 = -70 signed
        (1, 4): [(1050, [1, 2, 3, 4])],
    })
    out = reconstruct_wifi_samples(
        reader, start_ts=1000, end_ts=2000,
        _position_decoder=lambda blob: (1.5, 2.5),
    )
    assert len(out) == 1
    x, y, rssi, ts = out[0]
    assert (x, y, rssi, ts) == (1.5, 2.5, -70, 1100)


def test_reconstruct_skips_heartbeat_with_no_prior_position():
    """A heartbeat that fires before any s1p4 position — no pair, skip."""
    reader = _StubReader({
        (1, 1): [(1100, _hb_blob_with_rssi(186))],
        (1, 4): [(1200, [1, 2, 3, 4])],   # position is AFTER heartbeat
    })
    out = reconstruct_wifi_samples(
        reader, start_ts=1000, end_ts=2000,
        _position_decoder=lambda blob: (1.0, 2.0),
    )
    assert out == []


def test_reconstruct_dedups_within_25cm_radius_at_same_rssi():
    """Two heartbeats both at RSSI -70 with positions within 25 cm
    should dedup to one sample."""
    reader = _StubReader({
        (1, 1): [
            (1100, _hb_blob_with_rssi(186)),
            (1110, _hb_blob_with_rssi(186)),
        ],
        (1, 4): [(1050, [1, 2, 3, 4]), (1108, [5, 6, 7, 8])],
    })
    pos_iter = iter([(1.0, 2.0), (1.001, 2.001)])
    out = reconstruct_wifi_samples(
        reader, start_ts=1000, end_ts=2000,
        _position_decoder=lambda blob: next(pos_iter),
    )
    # Second heartbeat dedups (same RSSI, position within 25cm)
    assert len(out) == 1
