"""REPOSITIONING on undock: s2p1→working(1) from a docked prior state.

Spec: when s2p1 transitions INTO working(1) FROM a stationary/docked prior
state (raw_s2p1 ∈ {6 charging, 13 charging-completed, 2 idle, 16 batt-temp-hold}),
the state machine enters REPOSITIONING + ON_LAWN and clears any stale last_task_op
so a previous task type can't corrupt the label.

The op echo (~42s later) sets the real task activity (MOWING / CRUISING_TO_POINT)
via _apply_s2p50_task_envelope — that handler already sets current_activity
directly and OVERRIDES REPOSITIONING.

False-fire exit: if s2p1 leaves working(1) while REPOSITIONING with no echo,
resolve to the appropriate activity for the new s2p1 (e.g. → IDLE).

Return-leg: s2p1=5 (RETURNING) must not enter REPOSITIONING.
Active-session guard: mid-session s2p1=1 (NOT from a docked prior state)
must not enter REPOSITIONING.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    Location,
    MowSession,
)

T0 = 1_748_900_000  # arbitrary baseline unix (approx 2026-06-01)

# ---------------------------------------------------------------------------
# (1) Undock-repro: docked prior state → REPOSITIONING
# ---------------------------------------------------------------------------

_DOCKED_STATES = [6, 13, 2, 16]  # charging / charge-completed / idle / batt-temp-hold


def test_s2p1_working_from_charging_enters_repositioning():
    """s2p1=6(charging) → 1(working) → REPOSITIONING + ON_LAWN."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING, (
        f"s2p1: 6→1 must enter REPOSITIONING (got {snap.current_activity!r})"
    )
    assert snap.location == Location.ON_LAWN, (
        f"Undock transition must set ON_LAWN (got {snap.location!r})"
    )


def test_s2p1_working_from_charging_completed_enters_repositioning():
    """s2p1=13(charge-completed) → 1(working) → REPOSITIONING."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=13, now_unix=T0 - 60)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING, (
        f"s2p1: 13→1 must enter REPOSITIONING (got {snap.current_activity!r})"
    )
    assert snap.location == Location.ON_LAWN


def test_s2p1_working_from_idle_enters_repositioning():
    """s2p1=2(idle) → 1(working) → REPOSITIONING.

    This covers a schedule-triggered mow where the mower is in idle (not
    actively charging) but still docked.
    """
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=T0 - 60)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING, (
        f"s2p1: 2→1 must enter REPOSITIONING (got {snap.current_activity!r})"
    )
    assert snap.location == Location.ON_LAWN


def test_s2p1_working_from_batt_temp_hold_enters_repositioning():
    """s2p1=16(batt-temp-hold) → 1(working) → REPOSITIONING."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=16, now_unix=T0 - 60)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING, (
        f"s2p1: 16→1 must enter REPOSITIONING (got {snap.current_activity!r})"
    )
    assert snap.location == Location.ON_LAWN


def test_stale_last_task_op_cleared_on_undock():
    """A stale last_task_op (e.g. 109 from a prior cruise) must be cleared
    when entering REPOSITIONING so the label doesn't read "Cruising" during
    the ~42s reorientation window.
    """
    sm = MowerStateMachine()
    # Simulate a prior cruise that ended: last_task_op stays as 109
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"d": {"o": 109, "status": True}},
        now_unix=T0 - 300,
    )
    assert sm.snapshot().last_task_op == 109  # stale

    # Dock (charging state)
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)

    # New undock
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING
    assert snap.last_task_op is None, (
        f"Stale last_task_op must be cleared on undock, got {snap.last_task_op!r}"
    )


def test_repositioning_holds_across_heartbeats():
    """REPOSITIONING must persist through tick() calls (no echo yet)."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.REPOSITIONING

    for i in range(5):
        snap = sm.tick(now_unix=T0 + (i + 1) * 10)
        assert snap.current_activity == CurrentActivity.REPOSITIONING, (
            f"Tick {i}: REPOSITIONING must hold through heartbeats "
            f"(got {snap.current_activity!r})"
        )
        assert snap.location == Location.ON_LAWN, (
            f"Tick {i}: ON_LAWN must hold (got {snap.location!r})"
        )


# ---------------------------------------------------------------------------
# (2) Op echo refines REPOSITIONING → task activity
# ---------------------------------------------------------------------------

def test_op100_echo_after_repositioning_sets_mowing():
    """REPOSITIONING → op=100 echo → MOWING (the refine step)."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.REPOSITIONING

    snap = sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"d": {"o": 100, "status": True}},
        now_unix=T0 + 42,
    )
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"op=100 echo must refine REPOSITIONING → MOWING (got {snap.current_activity!r})"
    )
    assert snap.location == Location.ON_LAWN
    assert snap.mow_session == MowSession.IN_SESSION


def test_op109_echo_after_repositioning_sets_cruising():
    """REPOSITIONING → op=109 echo → CRUISING_TO_POINT."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=13, now_unix=T0 - 60)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.REPOSITIONING

    snap = sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"d": {"o": 109, "status": True}},
        now_unix=T0 + 42,
    )
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
        f"op=109 echo must refine REPOSITIONING → CRUISING_TO_POINT "
        f"(got {snap.current_activity!r})"
    )
    assert snap.location == Location.ON_LAWN
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_s2p1_working_after_op_echo_does_not_reenter_repositioning():
    """After the op echo, a subsequent s2p1=1 push (firmware confirms working)
    must NOT re-enter REPOSITIONING.

    In the real trace firmware emits s2p1=1 again after the op echo (~1s).
    At that point last_task_op is set (e.g. 100), raw_s2p1 is already 1
    (no prior-state transition), so the active-session guard must block it.
    """
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    sm.handle_mqtt_property(
        siid=2, piid=50, value={"d": {"o": 100, "status": True}}, now_unix=T0 + 42
    )
    assert sm.snapshot().current_activity == CurrentActivity.MOWING

    # Firmware re-pushes s2p1=1 after the echo
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 43)
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"Post-echo s2p1=1 must NOT re-enter REPOSITIONING (got {snap.current_activity!r})"
    )


# ---------------------------------------------------------------------------
# (3) Active-session guard: mid-session s2p1=1 must NOT enter REPOSITIONING
# ---------------------------------------------------------------------------

def test_mid_session_s2p1_working_does_not_reposition():
    """During an active mow session, s2p1=1 (e.g. after CHARGE_RESUME) must
    NOT enter REPOSITIONING. The prior raw_s2p1 is not a docked state."""
    sm = MowerStateMachine()
    # Start a mow: op echo (sets MOWING + IN_SESSION)
    sm.handle_mqtt_property(
        siid=2, piid=50, value={"d": {"o": 100, "status": True}}, now_unix=T0
    )
    assert sm.snapshot().current_activity == CurrentActivity.MOWING
    assert sm.snapshot().mow_session == MowSession.IN_SESSION

    # s2p1=1 push during mid-session
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 10)
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"Mid-session s2p1=1 must keep MOWING (got {snap.current_activity!r})"
    )
    assert snap.location == Location.ON_LAWN


def test_charge_resume_to_working_does_not_reposition():
    """s2p1=6→1 within an active IN_SESSION must resolve to MOWING (not
    REPOSITIONING): the mower is resuming mid-mow after a dock, not undocking
    from a fresh start.

    raw_s2p1=6 IS in the docked set, so the gate must additionally check
    mow_session: if IN_SESSION, keep MOWING, not REPOSITIONING.
    """
    sm = MowerStateMachine()
    # Start a mow session via op echo
    sm.handle_mqtt_property(
        siid=2, piid=50, value={"d": {"o": 100, "status": True}}, now_unix=T0
    )
    assert sm.snapshot().mow_session == MowSession.IN_SESSION

    # Mower goes to dock for recharge: s2p1=6
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 + 600)
    # Resumes: s2p1=1 — within an active session
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 1800)
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"IN_SESSION s2p1: 6→1 must keep MOWING, not REPOSITIONING "
        f"(got {snap.current_activity!r})"
    )
    assert snap.mow_session == MowSession.IN_SESSION


# ---------------------------------------------------------------------------
# (4) False-fire exit: REPOSITIONING → s2p1 leaves working state
# ---------------------------------------------------------------------------

def test_false_fire_exit_to_idle():
    """s2p1→1 (REPOSITIONING) then s2p1→2 (idle) with no echo → IDLE."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.REPOSITIONING

    snap = sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=T0 + 30)
    assert snap.current_activity == CurrentActivity.IDLE, (
        f"REPOSITIONING + s2p1→2 (idle) without echo must resolve to IDLE "
        f"(got {snap.current_activity!r})"
    )


def test_false_fire_exit_to_returning():
    """s2p1→1 (REPOSITIONING) then s2p1→5 (returning) → RETURNING."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.REPOSITIONING

    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0 + 30)
    assert snap.current_activity == CurrentActivity.RETURNING, (
        f"REPOSITIONING + s2p1→5 must resolve to RETURNING (got {snap.current_activity!r})"
    )


# ---------------------------------------------------------------------------
# (5) Return leg: s2p1=5 is RETURNING, not REPOSITIONING
# ---------------------------------------------------------------------------

def test_s2p1_returning_stays_returning_not_repositioning():
    """s2p1=5 (returning to dock) must still give RETURNING activity."""
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0)
    assert sm.snapshot().current_activity == CurrentActivity.RETURNING, (
        f"s2p1=5 must be RETURNING (got {sm.snapshot().current_activity!r})"
    )


# ---------------------------------------------------------------------------
# (6) Freshness: ON_LAWN stamp at undock must protect against stale cloud
# ---------------------------------------------------------------------------

def test_undock_on_lawn_freshness_protects_against_stale_cloud():
    """After the undock → REPOSITIONING transition, the freshness stamp for
    'location' must be set so a stale cloud AT_DOCK poll (with an earlier
    now_unix) cannot revert it back to AT_DOCK.
    """
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert sm.snapshot().location == Location.ON_LAWN

    # Simulate a stale cloud DOCK poll with an earlier timestamp
    snap = sm.handle_cloud_poll(
        "DOCK", {"connect_status": 1}, now_unix=T0 - 1
    )
    assert snap.location == Location.ON_LAWN, (
        "Stale cloud AT_DOCK poll must not revert ON_LAWN set at undock "
        f"(got {snap.location!r})"
    )
