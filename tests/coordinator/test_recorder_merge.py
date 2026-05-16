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


import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.dreame_a2_mower.coordinator._recorder_merge import (
    _read_battery_history_sync,
    _read_wifi_history_sync,
    BATTERY_ENTITY_ID,
    WIFI_RSSI_ENTITY_ID,
)


def _state(ts_unix: int, value: str) -> SimpleNamespace:
    """Fake HA State with the two fields our reader touches."""
    return SimpleNamespace(
        state=value,
        last_changed=dt.datetime.fromtimestamp(ts_unix, dt.UTC),
    )


def test_read_battery_history_sync_parses_valid_states() -> None:
    fake_states = {
        BATTERY_ENTITY_ID: [
            _state(1000, "85"),
            _state(1100, "84"),
            _state(1200, "83"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_battery_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1300, dt.UTC),
        )
    assert out == [[1000, 85], [1100, 84], [1200, 83]]


def test_read_battery_history_sync_skips_non_numeric_states() -> None:
    """unknown/unavailable/empty states get dropped silently."""
    fake_states = {
        BATTERY_ENTITY_ID: [
            _state(1000, "85"),
            _state(1100, "unavailable"),
            _state(1200, "unknown"),
            _state(1300, ""),
            _state(1400, "84"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_battery_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1500, dt.UTC),
        )
    assert out == [[1000, 85], [1400, 84]]


def test_read_battery_history_sync_skips_out_of_range() -> None:
    """Battery values outside 0..100 are skipped (recorder rounding
    or a value-class change can leak in non-percentages)."""
    fake_states = {
        BATTERY_ENTITY_ID: [
            _state(1000, "85"),
            _state(1100, "-5"),
            _state(1200, "101"),
            _state(1300, "80"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_battery_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1400, dt.UTC),
        )
    assert out == [[1000, 85], [1300, 80]]


def test_read_battery_history_sync_returns_empty_when_entity_missing() -> None:
    """state_changes_during_period returns {} when entity unknown."""
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value={},
    ):
        out = _read_battery_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1300, dt.UTC),
        )
    assert out == []


def test_read_wifi_history_sync_parses_valid_states() -> None:
    fake_states = {
        WIFI_RSSI_ENTITY_ID: [
            _state(1000, "-70"),
            _state(1100, "-69"),
            _state(1200, "-71"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_wifi_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1300, dt.UTC),
        )
    # Output shape: [None, None, rssi, ts]
    assert out == [[None, None, -70, 1000], [None, None, -69, 1100], [None, None, -71, 1200]]


def test_read_wifi_history_sync_skips_non_numeric_states() -> None:
    fake_states = {
        WIFI_RSSI_ENTITY_ID: [
            _state(1000, "-70"),
            _state(1100, "unavailable"),
            _state(1200, "-71"),
        ]
    }
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge."
        "state_changes_during_period",
        return_value=fake_states,
    ):
        out = _read_wifi_history_sync(
            hass=None,
            start_dt=dt.datetime.fromtimestamp(1000, dt.UTC),
            end_dt=dt.datetime.fromtimestamp(1300, dt.UTC),
        )
    assert out == [[None, None, -70, 1000], [None, None, -71, 1200]]
