"""Recorder-merge backfill for state/charging/error sample arrays."""
from unittest.mock import MagicMock, patch
import datetime as dt
import pytest

from custom_components.dreame_a2_mower.coordinator._recorder_merge import (
    _read_state_history_sync,
    _read_charging_status_history_sync,
    _read_error_history_sync,
)


def _mk_state(state_str, ts_seconds):
    s = MagicMock()
    s.state = state_str
    s.last_changed = dt.datetime.fromtimestamp(ts_seconds, dt.timezone.utc)
    return s


def test_read_state_history_returns_int_pairs():
    fake_rows = [_mk_state("0", 1000), _mk_state("4", 1100), _mk_state("0", 1200)]
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge.state_changes_during_period",
        return_value={"sensor.dreame_a2_mower_task_state_code": fake_rows},
    ):
        out = _read_state_history_sync(MagicMock(), dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))
    assert out == [[1000, 0], [1100, 4], [1200, 0]]


def test_read_state_history_skips_unknown_states():
    fake_rows = [_mk_state("unknown", 1000), _mk_state("0", 1100), _mk_state("unavailable", 1200)]
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge.state_changes_during_period",
        return_value={"sensor.dreame_a2_mower_task_state_code": fake_rows},
    ):
        out = _read_state_history_sync(MagicMock(), dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))
    assert out == [[1100, 0]]


def test_read_charging_status_history_returns_int_pairs():
    fake_rows = [_mk_state("1", 5000), _mk_state("0", 6000)]
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge.state_changes_during_period",
        return_value={"sensor.dreame_a2_mower_charging_status_code_raw": fake_rows},
    ):
        out = _read_charging_status_history_sync(MagicMock(), dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))
    assert out == [[5000, 1], [6000, 0]]


def test_read_error_history_returns_int_pairs():
    fake_rows = [_mk_state("56", 7000), _mk_state("0", 7100)]
    with patch(
        "custom_components.dreame_a2_mower.coordinator._recorder_merge.state_changes_during_period",
        return_value={"sensor.dreame_a2_mower_error_code": fake_rows},
    ):
        out = _read_error_history_sync(MagicMock(), dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2))
    assert out == [[7000, 56], [7100, 0]]
