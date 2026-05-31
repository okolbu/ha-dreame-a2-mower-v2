"""BUG 2 fix verification: s2p1=1 during a to-point (op=109) run.

During a cruise-to-point session the firmware emits s2p1=1 ("working")
shortly after the s2p50 op=109 echo. Before the fix the state machine
mapped s2p1=1 unconditionally to CurrentActivity.MOWING, clobbering the
CRUISING_TO_POINT activity set by the op=109 echo.

The fix: when last_task_op == 109, resolve s2p1==1 to CRUISING_TO_POINT
instead of MOWING. A real mow (last_task_op in {100,101,102,103} or None)
must still yield MOWING.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    MowSession,
)

T0 = 1_748_700_000  # arbitrary baseline unix (approx 2026-05-31 15:40 UTC)


def _s2p50_envelope(op: int, status: bool = True) -> dict:
    return {"d": {"o": op, "status": status}}


# ---------------------------------------------------------------------------
# BUG 2: s2p1=1 during op=109 should yield CRUISING_TO_POINT, not MOWING
# ---------------------------------------------------------------------------


def test_s2p1_1_after_op109_yields_cruising_to_point():
    """s2p1=1 during a to-point run (last_task_op=109) → CRUISING_TO_POINT.

    The firmware emits s2p1=1 ("working") after accepting the op=109 task.
    This must NOT clobber the CRUISING_TO_POINT activity set by the op=109
    echo — both before and after the fix the state machine should consistently
    report CRUISING_TO_POINT when the mower is driving to a maintenance point.
    """
    sm = MowerStateMachine()
    # Step 1: op=109 echo → CRUISING_TO_POINT
    sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.CRUISING_TO_POINT

    # Step 2: s2p1=1 arrives (firmware confirms working) — BUG: this clobbered CRUISING
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 1)
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
        f"s2p1=1 with last_task_op=109 should yield CRUISING_TO_POINT, got {snap.current_activity!r}. "
        "BUG 2 regression: s2p1=1 is clobbering the CRUISING_TO_POINT activity."
    )
    # Mow session must NOT have been entered (op=109 is never IN_SESSION)
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_s2p1_1_during_real_mow_still_yields_mowing():
    """s2p1=1 during a real mow (last_task_op=100) must still yield MOWING.

    The BUG 2 fix must be scoped to op=109 only. A real all-area mow
    (op=100) that emits s2p1=1 must continue to yield MOWING.
    """
    sm = MowerStateMachine()
    # op=100 echo → MOWING + IN_SESSION
    sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.MOWING
    assert sm.snapshot().mow_session == MowSession.IN_SESSION

    # s2p1=1 arrives — must KEEP MOWING
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 1)
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"s2p1=1 with last_task_op=100 must yield MOWING, got {snap.current_activity!r}"
    )
    assert snap.mow_session == MowSession.IN_SESSION


def test_s2p1_1_without_prior_op_still_yields_mowing():
    """s2p1=1 with no prior task op (last_task_op=None) → MOWING.

    Scheduled mows often don't deliver a s2p50 op echo before s2p1.
    Must remain MOWING.
    """
    sm = MowerStateMachine()
    # No prior s2p50 — last_task_op is None
    assert sm.snapshot().last_task_op is None
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"s2p1=1 with no prior op must yield MOWING, got {snap.current_activity!r}"
    )


def test_s2p1_1_after_other_mow_ops_still_yields_mowing():
    """s2p1=1 after op=101/102/103 (mow variants) still yields MOWING."""
    from custom_components.dreame_a2_mower.protocol.mode_enum import MOW_MODE_CODES
    for op in MOW_MODE_CODES:
        sm = MowerStateMachine()
        sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=op), now_unix=T0)
        snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 1)
        assert snap.current_activity == CurrentActivity.MOWING, (
            f"s2p1=1 after op={op} must yield MOWING, got {snap.current_activity!r}"
        )


def test_full_to_point_sequence_activity_is_consistent():
    """Drive the full to-point wire sequence and verify consistent activity.

    Wire sequence (simplified):
      s2p50 op=109 status:true  → CRUISING_TO_POINT
      s2p1 = 1                  → should still be CRUISING_TO_POINT (BUG 2 fix)
      s2p56 stage=2             → AT_POINT
      s2p1 = 2                  → IDLE
    """
    sm = MowerStateMachine()

    sm.handle_mqtt_property(siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.CRUISING_TO_POINT

    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 1)
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
        "s2p1=1 during to-point must not downgrade to MOWING"
    )

    # s2p56 stage=2 → AT_POINT
    sm.handle_mqtt_property(
        siid=2, piid=56, value={"status": [[1, 2]]}, now_unix=T0 + 40
    )
    assert sm.snapshot().current_activity == CurrentActivity.AT_POINT

    # s2p1=2 → IDLE
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=T0 + 41)
    assert snap.current_activity == CurrentActivity.IDLE
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS
