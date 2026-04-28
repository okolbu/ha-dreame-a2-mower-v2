"""Tests for live_map/finalize.py — comprehensive coverage of decide().

Each FinalizeAction branch is exercised with synthetic MowerState inputs.
The gate is purely declarative (no I/O), so tests are fast and hermetic.
"""
from __future__ import annotations

import pytest

from custom_components.dreame_a2_mower.live_map.finalize import (
    MAX_AGE_SECONDS,
    MAX_ATTEMPTS,
    RETRY_INTERVAL_SECONDS,
    FinalizeAction,
    decide,
)
from custom_components.dreame_a2_mower.mower.state import MowerState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = 1_000_000  # arbitrary baseline unix timestamp for tests


def _state(**kwargs) -> MowerState:
    """Construct a MowerState with sensible defaults for finalize tests."""
    return MowerState(**kwargs)


# ---------------------------------------------------------------------------
# Module-level constants sanity checks
# ---------------------------------------------------------------------------


def test_constants_are_sane():
    assert MAX_AGE_SECONDS == 30 * 60
    assert MAX_ATTEMPTS == 10
    assert RETRY_INTERVAL_SECONDS == 60


def test_finalize_action_enum_has_six_values():
    assert {a.name for a in FinalizeAction} == {
        "NOOP",
        "BEGIN_SESSION",
        "BEGIN_LEG",
        "FINALIZE_COMPLETE",
        "FINALIZE_INCOMPLETE",
        "AWAIT_OSS_FETCH",
    }


# ---------------------------------------------------------------------------
# NOOP — baseline / idle cases
# ---------------------------------------------------------------------------


def test_noop_when_state_is_empty():
    """Fresh MowerState with no fields set → NOOP."""
    state = _state()
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


def test_noop_when_running_steady_state():
    """Mower running (task_state=2), prev also 2, no pending OSS → NOOP."""
    state = _state(task_state_code=2, session_active=True)
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.NOOP


def test_noop_when_standby_no_pending():
    """Mower idle (task_state=None, session_active=None) → NOOP."""
    state = _state(task_state_code=None, session_active=None)
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


def test_noop_when_pending_oss_within_retry_window():
    """OSS key pending but last attempt was < RETRY_INTERVAL ago → NOOP."""
    state = _state(
        pending_session_object_name="session/abc123.json",
        pending_session_first_event_unix=NOW - (RETRY_INTERVAL_SECONDS - 5),
        pending_session_last_attempt_unix=NOW - (RETRY_INTERVAL_SECONDS - 5),
        pending_session_attempt_count=1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


# ---------------------------------------------------------------------------
# BEGIN_SESSION — any→1 transition
# ---------------------------------------------------------------------------


def test_begin_session_from_none():
    """First s2p56=1 with prev=None → BEGIN_SESSION."""
    state = _state(task_state_code=1)
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.BEGIN_SESSION


def test_begin_session_from_charging():
    """Transition from task_state_code=6 (or any non-1) → 1 → BEGIN_SESSION."""
    state = _state(task_state_code=1)
    assert decide(state, prev_task_state=6, now_unix=NOW) == FinalizeAction.BEGIN_SESSION


def test_begin_session_from_zero():
    """Transition from 0 → 1 → BEGIN_SESSION."""
    state = _state(task_state_code=1)
    assert decide(state, prev_task_state=0, now_unix=NOW) == FinalizeAction.BEGIN_SESSION


def test_no_begin_session_when_already_in_start_pending():
    """Staying at task_state_code=1 (prev=1) → NOOP, not BEGIN_SESSION again."""
    state = _state(task_state_code=1)
    assert decide(state, prev_task_state=1, now_unix=NOW) == FinalizeAction.NOOP


def test_begin_session_from_two_after_first_loop():
    """Transition 2→1 (restart without explicit end) → BEGIN_SESSION."""
    state = _state(task_state_code=1)
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.BEGIN_SESSION


# ---------------------------------------------------------------------------
# BEGIN_LEG — 4→2 recharge-resume transition
# ---------------------------------------------------------------------------


def test_begin_leg_on_recharge_resume():
    """prev=4 (resume_pending) → new=2 (running) → BEGIN_LEG."""
    state = _state(task_state_code=2, session_active=True)
    assert decide(state, prev_task_state=4, now_unix=NOW) == FinalizeAction.BEGIN_LEG


def test_no_begin_leg_on_fresh_start():
    """1→2 (first start) is NOT a recharge-resume → NOOP (leg already begun by begin_session)."""
    state = _state(task_state_code=2, session_active=True)
    assert decide(state, prev_task_state=1, now_unix=NOW) == FinalizeAction.NOOP


def test_no_begin_leg_on_already_running():
    """2→2 steady-state → NOOP."""
    state = _state(task_state_code=2, session_active=True)
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.NOOP


# ---------------------------------------------------------------------------
# FINALIZE_COMPLETE — session ended with pending OSS key
# ---------------------------------------------------------------------------


def test_finalize_complete_on_task_state_5_with_pending():
    """task_state_code=5 (ended) + pending OSS key → FINALIZE_COMPLETE."""
    state = _state(
        task_state_code=5,
        pending_session_object_name="session/xyz.json",
    )
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_COMPLETE


def test_finalize_complete_on_task_state_3_with_pending():
    """task_state_code=3 (complete) + pending OSS key → FINALIZE_COMPLETE."""
    state = _state(
        task_state_code=3,
        pending_session_object_name="session/xyz.json",
    )
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_COMPLETE


def test_finalize_complete_on_session_active_flip_from_running():
    """session_active=False, prev_task_state=2 (was running) + OSS key → FINALIZE_COMPLETE."""
    state = _state(
        task_state_code=None,
        session_active=False,
        pending_session_object_name="session/xyz.json",
    )
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_COMPLETE


def test_finalize_complete_on_session_active_flip_from_resume_pending():
    """session_active=False, prev_task_state=4 (was resume_pending) + OSS key → FINALIZE_COMPLETE."""
    state = _state(
        task_state_code=None,
        session_active=False,
        pending_session_object_name="session/xyz.json",
    )
    assert decide(state, prev_task_state=4, now_unix=NOW) == FinalizeAction.FINALIZE_COMPLETE


# ---------------------------------------------------------------------------
# FINALIZE_INCOMPLETE — session ended without pending OSS key
# ---------------------------------------------------------------------------


def test_finalize_incomplete_on_task_state_5_no_pending():
    """task_state_code=5 + no OSS key → FINALIZE_INCOMPLETE."""
    state = _state(task_state_code=5, pending_session_object_name=None)
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_finalize_incomplete_on_task_state_3_no_pending():
    """task_state_code=3 + no OSS key → FINALIZE_INCOMPLETE."""
    state = _state(task_state_code=3, pending_session_object_name=None)
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_finalize_incomplete_on_session_active_flip_no_pending():
    """session_active flipped False with prev=2, no OSS key → FINALIZE_INCOMPLETE."""
    state = _state(
        task_state_code=None,
        session_active=False,
        pending_session_object_name=None,
    )
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_finalize_incomplete_on_max_age_exceeded():
    """OSS key pending, first event older than MAX_AGE_SECONDS → FINALIZE_INCOMPLETE."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - MAX_AGE_SECONDS - 1,
        pending_session_last_attempt_unix=NOW - 60,
        pending_session_attempt_count=3,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_finalize_incomplete_one_second_past_max_age():
    """Boundary: first_event is 1 second past MAX_AGE_SECONDS → FINALIZE_INCOMPLETE."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - MAX_AGE_SECONDS - 1,
        pending_session_last_attempt_unix=NOW - 60,
        pending_session_attempt_count=1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_finalize_incomplete_on_max_attempts_exceeded():
    """attempt_count > MAX_ATTEMPTS → FINALIZE_INCOMPLETE."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - 60,
        pending_session_last_attempt_unix=NOW - 60,
        pending_session_attempt_count=MAX_ATTEMPTS + 1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_finalize_incomplete_exactly_at_max_attempts_plus_one():
    """attempt_count == MAX_ATTEMPTS + 1 → FINALIZE_INCOMPLETE (> not >=)."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - 60,
        pending_session_last_attempt_unix=NOW - 60,
        pending_session_attempt_count=MAX_ATTEMPTS + 1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_no_finalize_incomplete_at_exactly_max_attempts():
    """attempt_count == MAX_ATTEMPTS (not exceeded yet) → AWAIT_OSS_FETCH, not INCOMPLETE."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - RETRY_INTERVAL_SECONDS,
        pending_session_last_attempt_unix=NOW - RETRY_INTERVAL_SECONDS,
        pending_session_attempt_count=MAX_ATTEMPTS,
    )
    # At exactly MAX_ATTEMPTS (not exceeded) + retry interval passed → AWAIT_OSS_FETCH
    result = decide(state, prev_task_state=None, now_unix=NOW)
    assert result == FinalizeAction.AWAIT_OSS_FETCH


# ---------------------------------------------------------------------------
# AWAIT_OSS_FETCH — pending OSS key, retry window elapsed
# ---------------------------------------------------------------------------


def test_await_oss_fetch_on_first_attempt_none():
    """OSS key pending, last_attempt=None (never tried) → AWAIT_OSS_FETCH immediately."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW,
        pending_session_last_attempt_unix=None,
        pending_session_attempt_count=0,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.AWAIT_OSS_FETCH


def test_await_oss_fetch_when_retry_interval_elapsed():
    """OSS key pending, last attempt >= RETRY_INTERVAL_SECONDS ago → AWAIT_OSS_FETCH."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - RETRY_INTERVAL_SECONDS,
        pending_session_last_attempt_unix=NOW - RETRY_INTERVAL_SECONDS,
        pending_session_attempt_count=1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.AWAIT_OSS_FETCH


def test_await_oss_fetch_well_past_retry_interval():
    """OSS key pending, 5 minutes after last attempt, within max-age → AWAIT_OSS_FETCH."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - 300,  # 5 min ago
        pending_session_last_attempt_unix=NOW - 300,  # 5 min ago
        pending_session_attempt_count=4,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.AWAIT_OSS_FETCH


def test_noop_when_still_within_retry_window():
    """OSS key pending, only 30s since last attempt (< RETRY_INTERVAL) → NOOP."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - 30,
        pending_session_last_attempt_unix=NOW - 30,
        pending_session_attempt_count=1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


# ---------------------------------------------------------------------------
# Priority ordering — session-ended beats pending-OSS checks
# ---------------------------------------------------------------------------


def test_session_ended_beats_max_age_check():
    """task_state=5 + expired OSS key → FINALIZE_COMPLETE (not FINALIZE_INCOMPLETE from max-age)."""
    # The session-ended branch fires first and sees the OSS key.
    state = _state(
        task_state_code=5,
        pending_session_object_name="session/old.json",
        pending_session_first_event_unix=NOW - MAX_AGE_SECONDS - 9999,
        pending_session_last_attempt_unix=NOW - MAX_AGE_SECONDS - 9999,
        pending_session_attempt_count=MAX_ATTEMPTS + 5,
    )
    # Even though max-age and max-attempts are exceeded, the session-ended
    # branch (priority 1) sees the OSS key and returns FINALIZE_COMPLETE.
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_COMPLETE


def test_begin_session_only_when_no_session_ended():
    """task_state=1 but session_active=False with prev=2 → FINALIZE_INCOMPLETE (ended first)."""
    # A 2→1 transition where session_active is False means the session ended
    # (session_active flip with prev=2), which is priority 1.
    state = _state(
        task_state_code=1,
        session_active=False,
        pending_session_object_name=None,
    )
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


# ---------------------------------------------------------------------------
# Edge cases — None values + 0 counts
# ---------------------------------------------------------------------------


def test_attempt_count_none_treated_as_zero():
    """pending_session_attempt_count=None (missing) → treated as 0, not exceeded."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW,
        pending_session_last_attempt_unix=None,
        pending_session_attempt_count=None,
    )
    # attempt_count None → 0, not > MAX_ATTEMPTS, last_attempt None → AWAIT_OSS_FETCH
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.AWAIT_OSS_FETCH


def test_session_active_false_with_prev_none_not_finalized():
    """session_active=False, prev=None → prev not in {2, 4}, no task_state 3/5 → NOOP."""
    state = _state(session_active=False, task_state_code=None)
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


def test_session_active_false_with_prev_1_not_finalized():
    """session_active=False, prev=1 (start_pending) → not in {2, 4} → NOOP."""
    state = _state(session_active=False, task_state_code=None)
    assert decide(state, prev_task_state=1, now_unix=NOW) == FinalizeAction.NOOP


def test_task_state_3_no_pending_is_incomplete():
    """task_state=3 (complete state code) with no OSS key → FINALIZE_INCOMPLETE."""
    state = _state(task_state_code=3)
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_task_state_4_not_ended():
    """task_state=4 (resume_pending) is NOT an end state → NOOP (no pending OSS)."""
    state = _state(task_state_code=4, session_active=True)
    assert decide(state, prev_task_state=2, now_unix=NOW) == FinalizeAction.NOOP


# ---------------------------------------------------------------------------
# Regression: stale _prev_task_state must not re-trigger session-end branch
# ---------------------------------------------------------------------------


def test_noop_on_periodic_tick_with_stale_prev_task_state():
    """Session ended hours ago; all pending fields cleared; task_state=0 (idle).

    Scenario: the coordinator correctly advanced _prev_task_state to 0 after
    the last session was finalised (by updating it via _on_state_update on the
    same tick that cleared pending_session_object_name). A subsequent periodic
    60 s tick re-runs decide() with:
      - session_active=False
      - pending_session_object_name=None
      - task_state_code=0  (mower idle)
      - prev_task_state=0  (correctly advanced by coordinator after session end)

    Verify decide() returns NOOP and does NOT trigger any session-end branch.
    task_state=0 is not in (3, 5), and prev=0 is not in {2, 4}, so the
    session_just_ended guard is False → falls through to NOOP.
    """
    state = _state(
        session_active=False,
        pending_session_object_name=None,
        task_state_code=0,
    )
    assert decide(state, prev_task_state=0, now_unix=NOW + 3600) == FinalizeAction.NOOP


def test_noop_on_periodic_tick_session_inactive_no_pending_prev_none():
    """session_active=False, no pending, task_state=0, prev=None (startup tick) → NOOP.

    Confirms that a cold-start tick with no mowing history does not
    accidentally trigger a session-end branch when prev_task_state is None.
    prev=None is not in {2, 4}, so session_just_ended is False → NOOP.
    """
    state = _state(
        session_active=False,
        pending_session_object_name=None,
        task_state_code=0,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW + 3600) == FinalizeAction.NOOP
