"""Tests for LiveMapState."""
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_begin_session_clears_settings_snapshot():
    state = LiveMapState()
    state.settings_snapshot = {"foo": 1}
    state.begin_session(123456)
    assert state.settings_snapshot is None


def test_end_session_clears_settings_snapshot():
    state = LiveMapState()
    state.begin_session(123456)
    state.settings_snapshot = {"foo": 1}
    state.end_session()
    assert state.settings_snapshot is None


def test_settings_snapshot_defaults_none():
    state = LiveMapState()
    assert state.settings_snapshot is None
