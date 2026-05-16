"""Tests for tools._rebuild_session_lib.session_windows."""
from __future__ import annotations

from tools._rebuild_session_lib.session_windows import (
    Window,
    detect_windows,
)


def _ev(ts: int, sub_state):
    """Build a synthetic s2p56 event."""
    return (ts, sub_state)  # (ts_unix, sub_state_int_or_None)


def test_detect_single_session_happy_path():
    events = [
        _ev(1000, None),  # idle
        _ev(2000, 0),     # session START
        _ev(3000, 4),     # paused (recharge)
        _ev(4000, 0),     # resumed
        _ev(5000, 2),     # session END (complete)
        _ev(6000, None),  # idle again
    ]
    windows = detect_windows(events)
    assert windows == [Window(start_ts=2000, end_ts=5000)]


def test_detect_session_ending_in_none():
    events = [
        _ev(2000, 0),
        _ev(5000, None),  # END via "no task"
    ]
    windows = detect_windows(events)
    assert windows == [Window(start_ts=2000, end_ts=5000)]


def test_detect_two_sessions():
    events = [
        _ev(1000, None),
        _ev(2000, 0), _ev(5000, 2),    # session 1
        _ev(6000, None),
        _ev(7000, 0), _ev(9000, None), # session 2
    ]
    windows = detect_windows(events)
    assert windows == [
        Window(start_ts=2000, end_ts=5000),
        Window(start_ts=7000, end_ts=9000),
    ]


def test_detect_mid_log_start_drops_open_session():
    """Probe started while mower was already running. We don't see
    the start event, so the implicit window is dropped (incomplete)."""
    events = [
        _ev(1000, 0),    # already running when probe began
        _ev(5000, 2),    # end seen
    ]
    windows = detect_windows(events)
    # No prev=None or prev=2 transition seen for the start, so this
    # session has no valid start_ts and gets dropped.
    assert windows == []


def test_detect_mid_log_end_drops_open_session():
    """Probe truncated mid-session. No end event, so window is dropped."""
    events = [
        _ev(2000, 0),
    ]
    windows = detect_windows(events)
    assert windows == []


def test_detect_ignores_non_transition_events():
    """Multiple consecutive 0 events (heartbeat re-emission) shouldn't
    create new sessions."""
    events = [
        _ev(1000, None),  # confirmed idle before start
        _ev(2000, 0),     # confirmed start (prev=None → 0)
        _ev(3000, 0),     # re-emit (no transition)
        _ev(4000, 0),     # re-emit
        _ev(5000, 2),     # end
    ]
    windows = detect_windows(events)
    assert windows == [Window(start_ts=2000, end_ts=5000)]


def test_detect_empty_input():
    assert detect_windows([]) == []
