"""RED baseline: to-point (op=109) session-end bug.

== Pinned cause ==

The 0→2 task_state edge is consumed by `_on_state_update` (coordinator/
_mqtt_handlers.py:517) which writes `self._prev_task_state = new_task_state`
SYNCHRONOUSLY, advancing `_prev_task_state` from 0 to 2 immediately when the
s2p56 [[1,0]]→[[1,2]] push arrives (~40 s into the run).

The only path that calls `finalize.decide()` is the 60-second periodic tick
`_periodic_session_retry` (coordinator/_session.py:397). By the time that tick
fires, `_prev_task_state` is already 2 — not 0. `finalize.decide()` requires
`prev ∈ {0, 4}` to declare session-end (live_map/finalize.py:95-98); with
`prev=2` it returns NOOP and the session is never finalized.

Additionally, op=109 does NOT set `mow_session=IN_SESSION` in the state machine
(`_apply_s2p50_task_envelope`, state_machine.py:231 — only MOW_MODE_CODES do
that). So when s2p1=6 (CHARGING) arrives later, `mow_session` is
BETWEEN_SESSIONS, and `_apply_s2p1_task_state` correctly avoids CHARGE_RESUME
for an op=109 run that hasn't touched the state machine's mow_session.
The "Charging mid-session" symptom reported on 2026-05-31 therefore originates
from the live_map session staying ACTIVE (live_map.is_active() = True because
end_session() is never called), which the reconcile loop interprets as an
in-progress session — driving the UI, not from the state machine's mow_session.

Evidence: `finalize.py:95-98`, `_mqtt_handlers.py:517`,
`_session.py:397`, `state_machine.py:225-234`.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from custom_components.dreame_a2_mower.live_map.finalize import (
    FinalizeAction,
    decide,
)
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    MowSession,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = 1_748_700_000  # arbitrary baseline unix (approx 2026-05-31 15:40 UTC)


def _s2p50_envelope(op: int, status: bool = True) -> dict:
    """Minimal s2p50 TASK envelope as the firmware emits it."""
    return {"d": {"o": op, "status": status}}


def _s2p56_envelope(task_id: int, stage: int) -> dict:
    """Minimal s2p56 lifecycle envelope."""
    return {"status": [[task_id, stage]]}


def _s2p56_empty() -> dict:
    """s2p56 with no active task (session end / idle)."""
    return {"status": []}


# ---------------------------------------------------------------------------
# (a) op=109 does NOT set mow_session=IN_SESSION
# ---------------------------------------------------------------------------


def test_op109_does_not_enter_mow_session():
    """s2p50 op=109 (cruise-to-point) must NOT set mow_session=IN_SESSION.

    Only mow-variant ops (100-103) enter a mow session.  op=109 is a
    point-navigation op and intentionally excluded from MOW_MODE_CODES.
    """
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0
    )
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS, (
        f"op=109 incorrectly set mow_session to {snap.mow_session!r}; "
        "expected BETWEEN_SESSIONS"
    )
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT


def test_op109_followed_by_s2p1_6_does_not_produce_charge_resume():
    """After op=109 the state machine has mow_session=BETWEEN_SESSIONS.

    When s2p1=6 (charging) arrives, the guard at state_machine.py:98-106
    must fall through to IDLE (not CHARGE_RESUME), because mow_session
    is not IN_SESSION.
    """
    sm = MowerStateMachine()
    # Session begin — op=109 task accepted
    sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0
    )
    # Arrived at point, then idle
    sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=T0 + 40)
    # s2p2=75 (arrived_at_maintenance_point)
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=T0 + 41)
    # User presses Recharge: RETURNING
    sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0 + 338)
    # Docked → CHARGING (s2p1=6)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 + 462)

    assert snap.mow_session == MowSession.BETWEEN_SESSIONS, (
        f"mow_session should be BETWEEN_SESSIONS after op=109 run, got {snap.mow_session!r}"
    )
    assert snap.current_activity == CurrentActivity.IDLE, (
        f"current_activity should be IDLE after op=109 + dock, got {snap.current_activity!r}; "
        "CHARGE_RESUME would be wrong here because mow_session was never IN_SESSION"
    )


# ---------------------------------------------------------------------------
# (b) finalize.decide() on the 0→2 edge (correct; fires on the initial push)
#     vs on a later poll where _prev_task_state has already advanced to 2
# ---------------------------------------------------------------------------


def test_finalize_decide_fires_on_0_to_2_edge():
    """prev=0 (running) → task_state=2 (complete) → FINALIZE_INCOMPLETE.

    This is the only window in which decide() correctly detects session-end
    for an op=109 run.  In the real coordinator this edge is captured by
    _on_state_update but _prev_task_state is advanced to 2 *in the same call*
    (coordinator/_mqtt_handlers.py:517), so no periodic tick sees it with
    prev=0 anymore.
    """
    state = MowerState(task_state_code=2)
    action = decide(state, prev_task_state=0, now_unix=T0 + 40)
    assert action == FinalizeAction.FINALIZE_INCOMPLETE, (
        f"Expected FINALIZE_INCOMPLETE on 0→2 edge, got {action!r}"
    )


def test_finalize_decide_is_noop_when_prev_already_advanced_to_2():
    """Once _prev_task_state is 2, subsequent polls cannot detect session-end.

    This is the ROOT CAUSE of the bug: by the time the 60-second
    _periodic_session_retry fires, _prev_task_state has already been set to 2
    by _on_state_update (coordinator/_mqtt_handlers.py:517).  decide() sees
    prev=2, task_state=2, which does NOT satisfy `prev ∈ {0, 4}`, so it
    returns NOOP and the session is stuck open forever.
    """
    state = MowerState(task_state_code=2)
    # Simulate the 60-second poll *after* _prev_task_state was already set to 2
    action = decide(state, prev_task_state=2, now_unix=T0 + 100)
    assert action == FinalizeAction.NOOP, (
        f"Expected NOOP (confirming the stuck state), got {action!r}"
    )


def test_finalize_poll_sequence_demonstrates_stuck_session():
    """Full poll sequence confirms the finalize gate never fires for op=109.

    Simulates exactly what the periodic retry loop sees:
      - First poll after arrival (prev=2, state=2) → NOOP (BUG)
      - Second poll 60s later (prev=2, state=2) → NOOP (still stuck)
      - ...session never ends.

    This contrasts with a normal mow where state transitions to None after
    task_state=2, which would then fire FINALIZE_INCOMPLETE. For op=109 the
    s2p56 stays permanently at [[1,2]] and never transitions to [].
    """
    # After _on_state_update processed the 0→2 edge, _prev_task_state = 2
    state = MowerState(task_state_code=2, pending_session_object_name=None)

    for tick in range(5):
        action = decide(state, prev_task_state=2, now_unix=T0 + 100 + tick * 60)
        assert action == FinalizeAction.NOOP, (
            f"Tick {tick}: expected NOOP (session stuck open), got {action!r}"
        )


# ---------------------------------------------------------------------------
# (c) mow_session state machine trace for the full wire sequence
#     (confirms mow_session remains BETWEEN_SESSIONS throughout)
# ---------------------------------------------------------------------------


def test_full_wire_trace_op109_mow_session_never_enters_in_session():
    """Drive the exact 2026-05-31 wire trace through the state machine.

    Wire trace:
      15:51:25  s2p50 o=109 status:true
      15:51:25  s2p56 [] → [[1,0]]         task_state_code = 0
      15:52:05  s2p56 [[1,0]] → [[1,2]]     task_state_code = 2  (ARRIVED)
      15:52:06  s2p1 1→2  (MOWING→IDLE)
      15:52:06  s2p2 48→75  (arrived_at_maintenance_point)
      15:57:44  s2p1 2→5  (IDLE→RETURNING)
      15:59:07  s2p1 5→6  (RETURNING→CHARGING)

    Expected: mow_session stays BETWEEN_SESSIONS the whole time because
    op=109 never enters IN_SESSION (only MOW_MODE_CODES=100-103 do).
    """
    sm = MowerStateMachine()

    # t+0: s2p50 op=109 accepted
    sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.CRUISING_TO_POINT
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS

    # s2p56 [] → [[1,0]]  (task_state_code becomes 0 via MowerState, not SM)
    # The SM handles s2p56 in _apply_s2p56_lifecycle — stage=0 is a no-op
    sm.handle_mqtt_property(siid=2, piid=56, value=_s2p56_envelope(1, 0), now_unix=T0 + 1)
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS  # still

    # t+40: s2p56 [[1,0]] → [[1,2]] — arrived; SM sees stage=2 +
    # CRUISING_TO_POINT → sets AT_POINT
    sm.handle_mqtt_property(siid=2, piid=56, value=_s2p56_envelope(1, 2), now_unix=T0 + 40)
    assert sm.snapshot().current_activity == CurrentActivity.AT_POINT
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS

    # t+41: s2p1=2 (MOWING→IDLE) — state machine sets IDLE, mow_session→BETWEEN_SESSIONS
    sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=T0 + 41)
    assert sm.snapshot().current_activity == CurrentActivity.IDLE
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS

    # t+41: s2p2=75 (arrived_at_maintenance_point) — SM sets AT_POINT + AT_POINT location
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=T0 + 41)
    assert sm.snapshot().current_activity == CurrentActivity.AT_POINT
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS

    # t+379: s2p1=5 (IDLE→RETURNING)
    sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0 + 379)
    assert sm.snapshot().current_activity == CurrentActivity.RETURNING
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS

    # t+462: s2p1=6 (RETURNING→CHARGING) — the key assertion:
    # mow_session is BETWEEN_SESSIONS, so CHARGE_RESUME must NOT fire
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 + 462)
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS, (
        f"mow_session={snap.mow_session!r} — expected BETWEEN_SESSIONS after "
        "op=109 run; state machine should never have entered IN_SESSION"
    )
    assert snap.current_activity == CurrentActivity.IDLE, (
        f"current_activity={snap.current_activity!r} — expected IDLE, not "
        "CHARGE_RESUME, because mow_session was never IN_SESSION for op=109"
    )
