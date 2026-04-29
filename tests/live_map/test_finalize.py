"""Tests for live_map/finalize.py — comprehensive coverage of decide().

The gate's task_state semantics on g2408 (post-v1.0.0a18 s2p56 decode):
  - 0    = running
  - 4    = paused / resume_pending (recharge boundary)
  - None = no active task → SESSION END signal

Each FinalizeAction branch is exercised with synthetic MowerState
inputs. The gate is purely declarative (no I/O), so tests are fast
and hermetic.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.finalize import (
    MAX_AGE_SECONDS,
    MAX_ATTEMPTS,
    RETRY_INTERVAL_SECONDS,
    FinalizeAction,
    decide,
)
from custom_components.dreame_a2_mower.mower.state import MowerState

NOW = 1_000_000  # arbitrary baseline unix timestamp for tests


def _state(**kwargs) -> MowerState:
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
    state = _state()
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


def test_noop_when_running_steady_state():
    """Mower running (task_state=0), prev also 0, no pending OSS → NOOP."""
    state = _state(task_state_code=0, session_active=True)
    assert decide(state, prev_task_state=0, now_unix=NOW) == FinalizeAction.NOOP


def test_noop_when_idle_no_pending():
    """task_state=None, no prior task → NOOP (idle baseline)."""
    state = _state(task_state_code=None)
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


def test_noop_when_pending_oss_within_retry_window():
    state = _state(
        pending_session_object_name="session/abc123.json",
        pending_session_first_event_unix=NOW - (RETRY_INTERVAL_SECONDS - 5),
        pending_session_last_attempt_unix=NOW - (RETRY_INTERVAL_SECONDS - 5),
        pending_session_attempt_count=1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


# ---------------------------------------------------------------------------
# Session-ended detection — prev (0|4) → None transition
# ---------------------------------------------------------------------------


def test_finalize_complete_running_to_none_with_pending():
    """prev=0 (running) → new=None (no task) + OSS key → FINALIZE_COMPLETE."""
    state = _state(
        task_state_code=None,
        pending_session_object_name="session/xyz.json",
    )
    assert decide(state, prev_task_state=0, now_unix=NOW) == FinalizeAction.FINALIZE_COMPLETE


def test_finalize_complete_paused_to_none_with_pending():
    """prev=4 (paused) → new=None + OSS key → FINALIZE_COMPLETE."""
    state = _state(
        task_state_code=None,
        pending_session_object_name="session/xyz.json",
    )
    assert decide(state, prev_task_state=4, now_unix=NOW) == FinalizeAction.FINALIZE_COMPLETE


def test_finalize_incomplete_running_to_none_no_pending():
    """prev=0 → new=None, no OSS key → FINALIZE_INCOMPLETE."""
    state = _state(task_state_code=None, pending_session_object_name=None)
    assert decide(state, prev_task_state=0, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_finalize_incomplete_paused_to_none_no_pending():
    """prev=4 → new=None, no OSS key → FINALIZE_INCOMPLETE."""
    state = _state(task_state_code=None, pending_session_object_name=None)
    assert decide(state, prev_task_state=4, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_no_session_end_without_prior_running_state():
    """task_state=None with prev=None (cold start) → NOT a session-end → NOOP."""
    state = _state(task_state_code=None, pending_session_object_name=None)
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.NOOP


def test_no_session_end_when_paused_stays_paused():
    """prev=4 → new=4 → still in session → NOOP."""
    state = _state(task_state_code=4, session_active=True)
    assert decide(state, prev_task_state=4, now_unix=NOW) == FinalizeAction.NOOP


def test_no_session_end_when_running_stays_running():
    state = _state(task_state_code=0, session_active=True)
    assert decide(state, prev_task_state=0, now_unix=NOW) == FinalizeAction.NOOP


def test_pause_transition_is_not_session_end():
    """Running → paused is a recharge boundary, NOT a session end."""
    state = _state(task_state_code=4, session_active=True)
    assert decide(state, prev_task_state=0, now_unix=NOW) == FinalizeAction.NOOP


# ---------------------------------------------------------------------------
# Pending-OSS retry / max-age / max-attempts logic
# ---------------------------------------------------------------------------


def test_finalize_incomplete_on_max_age_exceeded():
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - MAX_AGE_SECONDS - 1,
        pending_session_last_attempt_unix=NOW - 60,
        pending_session_attempt_count=3,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_finalize_incomplete_on_max_attempts_exceeded():
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - 60,
        pending_session_last_attempt_unix=NOW - 60,
        pending_session_attempt_count=MAX_ATTEMPTS + 1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.FINALIZE_INCOMPLETE


def test_at_exactly_max_attempts_still_retries():
    """attempt_count == MAX_ATTEMPTS (not yet exceeded) + retry interval
    elapsed → AWAIT_OSS_FETCH, not FINALIZE_INCOMPLETE."""
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - RETRY_INTERVAL_SECONDS,
        pending_session_last_attempt_unix=NOW - RETRY_INTERVAL_SECONDS,
        pending_session_attempt_count=MAX_ATTEMPTS,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.AWAIT_OSS_FETCH


def test_await_oss_fetch_on_first_attempt_none():
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW,
        pending_session_last_attempt_unix=None,
        pending_session_attempt_count=0,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.AWAIT_OSS_FETCH


def test_await_oss_fetch_when_retry_interval_elapsed():
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW - RETRY_INTERVAL_SECONDS,
        pending_session_last_attempt_unix=NOW - RETRY_INTERVAL_SECONDS,
        pending_session_attempt_count=1,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.AWAIT_OSS_FETCH


def test_attempt_count_none_treated_as_zero():
    state = _state(
        pending_session_object_name="session/abc.json",
        pending_session_first_event_unix=NOW,
        pending_session_last_attempt_unix=None,
        pending_session_attempt_count=None,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW) == FinalizeAction.AWAIT_OSS_FETCH


# ---------------------------------------------------------------------------
# Priority — session-ended branch beats the pending-OSS retry checks
# ---------------------------------------------------------------------------


def test_session_ended_beats_max_age_check():
    """End-of-session transition fires before pending-OSS expiry checks."""
    state = _state(
        task_state_code=None,
        pending_session_object_name="session/old.json",
        pending_session_first_event_unix=NOW - MAX_AGE_SECONDS - 9999,
        pending_session_last_attempt_unix=NOW - MAX_AGE_SECONDS - 9999,
        pending_session_attempt_count=MAX_ATTEMPTS + 5,
    )
    assert decide(state, prev_task_state=0, now_unix=NOW) == FinalizeAction.FINALIZE_COMPLETE


# ---------------------------------------------------------------------------
# Stale-prev regression: the coordinator advances _prev_task_state to 0
# after a finalize. A subsequent periodic tick must NOT re-trigger the
# session-end branch.
# ---------------------------------------------------------------------------


def test_noop_on_periodic_tick_with_stale_prev_task_state():
    state = _state(
        session_active=False,
        pending_session_object_name=None,
        task_state_code=0,
    )
    assert decide(state, prev_task_state=0, now_unix=NOW + 3600) == FinalizeAction.NOOP


def test_noop_on_periodic_tick_prev_none():
    state = _state(
        session_active=False,
        pending_session_object_name=None,
        task_state_code=0,
    )
    assert decide(state, prev_task_state=None, now_unix=NOW + 3600) == FinalizeAction.NOOP
