"""Tests for live_map/state.py — sample buffers + lifecycle."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_default_state_is_inactive():
    s = LiveMapState()
    assert not s.is_active()
    assert s.total_points() == 0


def test_append_telemetry_sample_debounces_identical():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    assert s.append_telemetry_sample(s.battery_samples, 80, 1010) is True
    assert s.append_telemetry_sample(s.battery_samples, 80, 1020) is False
    assert s.append_telemetry_sample(s.battery_samples, 79, 1030) is True
    assert s.battery_samples == [(1010, 80), (1030, 79)]


def test_append_wifi_sample_debounces_stationary():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    assert s.append_wifi_sample(1.0, 2.0, -50, 1010) is True
    assert s.append_wifi_sample(1.05, 2.05, -50, 1020) is False
    assert s.append_wifi_sample(1.0, 2.0, -55, 1030) is True
    assert len(s.wifi_samples) == 2
