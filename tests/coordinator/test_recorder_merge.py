"""Tests for the session recorder-merge helpers."""
from __future__ import annotations

from custom_components.dreame_a2_mower.coordinator._recorder_merge import (
    _merge_samples,
    _merge_wifi_samples,
)


def test_merge_samples_empty_inputs() -> None:
    assert _merge_samples([], []) == []


def test_merge_samples_dedups_on_ts_value() -> None:
    existing = [[100, 80], [200, 79]]
    additions = [[100, 80], [150, 79], [200, 79], [250, 78]]
    out = _merge_samples(existing, additions)
    # (100,80), (150,79), (200,79), (250,78) — dups removed
    assert out == [[100, 80], [150, 79], [200, 79], [250, 78]]


def test_merge_samples_sorts_by_ts() -> None:
    existing = [[300, 70], [100, 80]]
    additions = [[200, 75]]
    out = _merge_samples(existing, additions)
    assert [s[0] for s in out] == [100, 200, 300]


def test_merge_samples_preserves_value_difference_at_same_ts() -> None:
    """Two different values at the same timestamp both survive
    (rare but possible — a battery sample and a recorder-side
    rounding artifact could land at the same second with
    different ints)."""
    existing = [[100, 80]]
    additions = [[100, 81]]
    out = _merge_samples(existing, additions)
    assert sorted(out) == [[100, 80], [100, 81]]


def test_merge_wifi_samples_empty_inputs() -> None:
    assert _merge_wifi_samples([], []) == []


def test_merge_wifi_samples_dedups_on_ts_rssi() -> None:
    # WiFi sample shape: [lat_offset, lon_offset, rssi, ts]
    existing = [[1.0, 2.0, -70, 100], [1.0, 2.0, -71, 200]]
    additions = [
        [None, None, -70, 100],  # dup on (ts=100, rssi=-70)
        [None, None, -69, 150],  # new
        [None, None, -71, 200],  # dup on (ts=200, rssi=-71)
    ]
    out = _merge_wifi_samples(existing, additions)
    rssi_ts = [(s[3], s[2]) for s in out]
    assert rssi_ts == [(100, -70), (150, -69), (200, -71)]


def test_merge_wifi_samples_sorts_by_ts() -> None:
    existing = [[1.0, 2.0, -70, 300]]
    additions = [[None, None, -65, 100], [None, None, -68, 200]]
    out = _merge_wifi_samples(existing, additions)
    assert [s[3] for s in out] == [100, 200, 300]
