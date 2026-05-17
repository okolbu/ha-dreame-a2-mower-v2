"""Tests for the session recorder-merge helpers."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.dreame_a2_mower.coordinator._recorder_merge import (
    BATTERY_ENTITY_ID,
    WIFI_RSSI_ENTITY_ID,
    _merge_samples,
    _merge_wifi_samples,
    _read_battery_history_sync,
    _read_wifi_history_sync,
    merge_recorder_samples,
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


# ---------------------------------------------------------------------------
# Async orchestrator tests
# ---------------------------------------------------------------------------


class _FakeRecorderInstance:
    """Minimal hass-like object for the merge orchestrator test."""

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class _FakeHass:
    def __init__(self) -> None:
        self._instance = _FakeRecorderInstance()


@pytest.mark.asyncio
async def test_merge_recorder_samples_fills_gaps() -> None:
    """When raw_dict has 2 battery samples and recorder has 5, the
    merged list should have 5 (deduped, sorted, source-agnostic)."""
    raw_dict: dict = {
        "battery_samples": [[1000, 85], [2000, 80]],
        "wifi_samples": [[1.0, 2.0, -70, 1000]],
    }
    hass = _FakeHass()

    fake_battery = [[1000, 85], [1500, 82], [2000, 80], [2500, 78], [3000, 75]]
    fake_wifi = [[None, None, -70, 1000], [None, None, -68, 1500], [None, None, -71, 2500]]

    with (
        patch(
            "custom_components.dreame_a2_mower.coordinator._recorder_merge."
            "_async_fetch_battery_from_recorder",
            return_value=fake_battery,
        ),
        patch(
            "custom_components.dreame_a2_mower.coordinator._recorder_merge."
            "_async_fetch_wifi_from_recorder",
            return_value=fake_wifi,
        ),
    ):
        counts = await merge_recorder_samples(hass, raw_dict, 1000, 3000)

    # Battery: 5 distinct ts (1000, 1500, 2000, 2500, 3000), all values present.
    assert [s[0] for s in raw_dict["battery_samples"]] == [1000, 1500, 2000, 2500, 3000]
    # WiFi: 3 distinct ts (1000, 1500, 2500).
    assert [s[3] for s in raw_dict["wifi_samples"]] == [1000, 1500, 2500]
    # Counts reflect what the recorder contributed (raw fetch count, not net-new).
    # state/charging/error fetchers return [] since they aren't patched here.
    assert counts == {
        "battery_recorder_count": 5,
        "wifi_recorder_count": 3,
        "state_recorder_count": 0,
        "charging_recorder_count": 0,
        "error_recorder_count": 0,
    }


@pytest.mark.asyncio
async def test_merge_recorder_samples_handles_missing_raw_keys() -> None:
    """raw_dict without battery_samples / wifi_samples should not crash."""
    raw_dict: dict = {}
    hass = _FakeHass()

    with (
        patch(
            "custom_components.dreame_a2_mower.coordinator._recorder_merge."
            "_async_fetch_battery_from_recorder",
            return_value=[[100, 90]],
        ),
        patch(
            "custom_components.dreame_a2_mower.coordinator._recorder_merge."
            "_async_fetch_wifi_from_recorder",
            return_value=[[None, None, -65, 100]],
        ),
    ):
        await merge_recorder_samples(hass, raw_dict, 100, 200)

    assert raw_dict["battery_samples"] == [[100, 90]]
    assert raw_dict["wifi_samples"] == [[None, None, -65, 100]]
