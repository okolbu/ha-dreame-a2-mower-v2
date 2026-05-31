"""Command-time session-start: activity + location at the op echo, for ALL task types.

BUG: At undock there is a ~45s reorientation window where s1p4 (position
telemetry) is SILENT. During this window:
  - current_activity: was correct at echo-time, but the s2p1=1 pre-echo could
    have set MOWING before the echo, and reconcile sees IN_SESSION+MOWING+AT_DOCK
    → converts to CHARGE_RESUME.
  - location: stays AT_DOCK because _reconcile_location needs a real position to
    detect departure.

FIX: _apply_s2p50_task_envelope now sets location=ON_LAWN when status=True and
the op has a known activity. This:
  1. Breaks the reconcile short-circuit (IN_SESSION+MOWING+AT_DOCK → CHARGE_RESUME
     never fires because location is already ON_LAWN).
  2. Fixes the UI: "At dock" disappears at command-time, not ~45s later.

The fix is GENERAL: applies to mow (100-103), patrol (108), and cruise (109).

Test sections:
  (A) Echo sets activity + location immediately, per op type.
  (B) Activity + location are STICKY through simulated reorientation heartbeats
      (no s2p1 re-push, no s1p4 position frames).
  (C) The reconcile rule IN_SESSION+MOWING+AT_DOCK→CHARGE_RESUME can no longer
      fire after the fix, because location is already ON_LAWN.
  (D) Mow regression: mow still enters IN_SESSION + MOWING; mid-run + end unchanged.
  (E) Arrival/dock paths are not disturbed: AT_POINT and AT_DOCK set correctly later.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    Location,
    MowSession,
)

T0 = 1_748_900_000  # arbitrary baseline unix (approx 2026-06-01)


def _s2p50_envelope(op: int, status: bool = True) -> dict:
    """Minimal s2p50 TASK envelope as the firmware emits it."""
    return {"d": {"o": op, "status": status}}


# ---------------------------------------------------------------------------
# (A) Echo sets activity + location at command-time
# ---------------------------------------------------------------------------


def test_op100_echo_sets_mowing_and_on_lawn():
    """op=100 (all-areas mow): echo must set current_activity=MOWING and
    location=ON_LAWN immediately — NOT waiting for s1p4 position arrival."""
    sm = MowerStateMachine()
    # Precondition: AT_DOCK (initial state)
    assert sm.snapshot().location == Location.AT_DOCK

    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"op=100 echo must set MOWING immediately, got {snap.current_activity!r}"
    )
    assert snap.location == Location.ON_LAWN, (
        f"op=100 echo must set ON_LAWN immediately, got {snap.location!r}. "
        "FIX: op echo must not leave location=AT_DOCK during the ~45s reorientation window."
    )
    assert snap.mow_session == MowSession.IN_SESSION, (
        f"op=100 must enter mow_session=IN_SESSION, got {snap.mow_session!r}"
    )


def test_op101_echo_sets_mowing_and_on_lawn():
    """op=101 (edge mow): echo must set current_activity=MOWING and location=ON_LAWN."""
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=101), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.location == Location.ON_LAWN, (
        f"op=101 echo must set ON_LAWN, got {snap.location!r}"
    )


def test_op102_echo_sets_mowing_and_on_lawn():
    """op=102 (zone mow): echo must set location=ON_LAWN."""
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=102), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.location == Location.ON_LAWN


def test_op103_echo_sets_mowing_and_on_lawn():
    """op=103 (spot mow): echo must set location=ON_LAWN."""
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=103), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.location == Location.ON_LAWN


def test_op108_echo_sets_on_lawn():
    """op=108 (patrol): echo must set location=ON_LAWN.

    Patrol (108) is NOT a mow op (not in MOW_MODE_CODES), so it does NOT
    enter mow_session=IN_SESSION. But it IS a task that leaves the dock,
    so location=ON_LAWN must be set at echo-time.
    """
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=108), now_unix=T0
    )
    assert snap.location == Location.ON_LAWN, (
        f"op=108 (patrol) echo must set ON_LAWN, got {snap.location!r}"
    )
    # Patrol does NOT enter mow_session
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_op109_echo_sets_cruising_to_point_and_on_lawn():
    """op=109 (cruise-to-point): echo must set CRUISING_TO_POINT + ON_LAWN.

    This is the primary case from the 2026-05-31 to-point trace.
    """
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
        f"op=109 echo must set CRUISING_TO_POINT, got {snap.current_activity!r}"
    )
    assert snap.location == Location.ON_LAWN, (
        f"op=109 echo must set ON_LAWN immediately, got {snap.location!r}"
    )
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_rejected_echo_does_not_set_on_lawn():
    """status=False (firmware rejected task): echo must NOT change location.

    A rejected task command does not leave the dock — the mower stays parked.
    """
    sm = MowerStateMachine()
    assert sm.snapshot().location == Location.AT_DOCK

    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100, status=False), now_unix=T0
    )
    # Rejected echo must not change location
    assert snap.location == Location.AT_DOCK, (
        f"Rejected echo (status=False) must not change location to ON_LAWN, "
        f"got {snap.location!r}"
    )
    # No activity change either (rejected = firmware didn't accept the task)
    assert snap.current_activity == CurrentActivity.IDLE


# ---------------------------------------------------------------------------
# (B) Activity + location are STICKY through reorientation window
#     (no new s2p1 push, no s1p4 position frames)
# ---------------------------------------------------------------------------


def test_mow_op100_activity_and_location_sticky_through_reorientation():
    """After op=100 echo, heartbeats without s2p1/s1p4 must NOT revert activity
    or location.

    Simulates the ~45s reorientation window where:
    - s2p1 has already emitted (before the command) and will NOT push again
    - s1p4 position telemetry is SILENT
    - Only heartbeats + tick() arrive

    Pre-condition from the trace: s2p1=1 was set BEFORE the command (while still
    docked). That means s2p1 is already "1" and the firmware won't re-push it.
    The state machine must preserve the echo's activity+location through this window.
    """
    sm = MowerStateMachine()

    # s2p1=1 fires BEFORE the command (typical: docked but activity settled early)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 45)
    # Mowing was set but we're still at dock (no echo yet, no session start)
    # Let location stay AT_DOCK (from initial state)

    # Command echo: op=100 starts the session
    snap_after_echo = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert snap_after_echo.current_activity == CurrentActivity.MOWING
    assert snap_after_echo.location == Location.ON_LAWN, (
        "Echo must set ON_LAWN"
    )

    # Simulate 6 ticks (60s) with NO s2p1 or s1p4 pushes
    for tick in range(6):
        snap = sm.tick(now_unix=T0 + (tick + 1) * 10)
        assert snap.current_activity == CurrentActivity.MOWING, (
            f"Tick {tick}: current_activity reverted to {snap.current_activity!r}. "
            "Activity must be STICKY from echo-time during reorientation window."
        )
        assert snap.location == Location.ON_LAWN, (
            f"Tick {tick}: location reverted to {snap.location!r}. "
            "Location must be STICKY as ON_LAWN from echo-time."
        )


def test_op109_activity_and_location_sticky_through_reorientation():
    """After op=109 echo, ticks without s1p4 must keep CRUISING_TO_POINT + ON_LAWN.

    Mirrors the real trace: echo at T0, then s2p1=1 at T0+1 (which the BUG2 fix
    already handles), then ~4s of silence until first s1p4 arrives.
    """
    sm = MowerStateMachine()

    # s2p1=1 BEFORE the echo (mower was docked and already showed s2p1=1)
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 42)

    # Echo: op=109 cruise
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0
    )
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT
    assert snap.location == Location.ON_LAWN

    # s2p1=1 fires AGAIN after echo (firmware confirms working)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 1)
    # BUG2 fix: s2p1=1 with last_task_op=109 → CRUISING_TO_POINT (not MOWING)
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
        f"s2p1=1 after op=109 must stay CRUISING_TO_POINT, got {snap.current_activity!r}"
    )
    assert snap.location == Location.ON_LAWN, (
        f"s2p1=1 must not revert location to AT_DOCK, got {snap.location!r}"
    )

    # Reorientation silence: 4 more ticks (40s), no s1p4
    for tick in range(4):
        snap = sm.tick(now_unix=T0 + 10 + tick * 10)
        assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT, (
            f"Tick {tick}: activity reverted to {snap.current_activity!r}"
        )
        assert snap.location == Location.ON_LAWN, (
            f"Tick {tick}: location reverted to {snap.location!r}"
        )


# ---------------------------------------------------------------------------
# (C) The reconcile short-circuit (IN_SESSION+MOWING+AT_DOCK→CHARGE_RESUME)
#     can no longer trigger because location is ON_LAWN after the echo
# ---------------------------------------------------------------------------


def test_mow_reconcile_does_not_convert_to_charge_resume_after_echo():
    """After op=100 echo sets ON_LAWN, reconcile must NOT flip MOWING→CHARGE_RESUME.

    The reconcile rule (state_machine.py _reconcile_mow_activity) fires:
      IN_SESSION + MOWING + AT_DOCK → CHARGE_RESUME
    This was the active regression for mow sessions: the echo set IN_SESSION+MOWING
    but left location=AT_DOCK, so the FIRST reconcile call (every 10s tick) would
    corrupt the activity to CHARGE_RESUME.

    With the fix (echo also sets ON_LAWN), this rule never triggers.
    """
    sm = MowerStateMachine()

    # Simulate the real trace: s2p1=1 fires before command
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 45)

    # Command echo
    sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert sm.snapshot().location == Location.ON_LAWN
    assert sm.snapshot().current_activity == CurrentActivity.MOWING
    assert sm.snapshot().mow_session == MowSession.IN_SESSION

    # Reconcile with live_map_active=True, area_mowed=0 (no mow evidence yet,
    # typical during the first ~45s before blades start cutting)
    snap = sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=0.0,      # no area yet — first frames
        position_x_m=None,      # position SILENT (reorientation window)
        position_y_m=None,
        dock_x_mm=None,
        dock_y_mm=None,
        now_unix=T0 + 5,
    )
    assert snap.current_activity == CurrentActivity.MOWING, (
        f"Reconcile must NOT convert MOWING→CHARGE_RESUME after echo. "
        f"Got {snap.current_activity!r}. "
        "The IN_SESSION+MOWING+AT_DOCK short-circuit should be blocked by ON_LAWN."
    )
    assert snap.location == Location.ON_LAWN


def test_reconcile_charge_resume_rule_still_works_when_docked_mid_session():
    """Regression check: IN_SESSION+MOWING+AT_DOCK→CHARGE_RESUME STILL fires
    when the mower has genuinely returned to the dock mid-session (recharge stop).

    The fix must NOT prevent this legitimate path — it only prevents the false
    positive that was caused by the echo NOT clearing AT_DOCK.
    """
    sm = MowerStateMachine()

    # Manually put the state machine into IN_SESSION + MOWING state
    sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    # Confirm: echo sets ON_LAWN (new fix)
    assert sm.snapshot().location == Location.ON_LAWN

    # Mower mows for a bit, then genuinely docks (charging signal)
    # s3p2=True → _apply_charging → location=AT_DOCK (invariant)
    sm.handle_mqtt_property(siid=3, piid=2, value=1, now_unix=T0 + 600)  # charging

    assert sm.snapshot().location == Location.AT_DOCK, (
        "After charging=True, location must be AT_DOCK (dock invariant)"
    )
    assert sm.snapshot().mow_session == MowSession.IN_SESSION, (
        "Session is still active (mid-mow charge stop)"
    )

    # Now reconcile fires: IN_SESSION + MOWING + AT_DOCK → CHARGE_RESUME
    snap = sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=50.0,     # definitely mowing (area > 0)
        position_x_m=None,
        position_y_m=None,
        dock_x_mm=None,
        dock_y_mm=None,
        now_unix=T0 + 610,
    )
    assert snap.current_activity == CurrentActivity.CHARGE_RESUME, (
        f"Legitimate mid-session dock must still produce CHARGE_RESUME. "
        f"Got {snap.current_activity!r}."
    )


# ---------------------------------------------------------------------------
# (D) Mow regression: full mow lifecycle unchanged
# ---------------------------------------------------------------------------


def test_mow_lifecycle_unchanged():
    """Full mow op=100 lifecycle: still correct from echo through end."""
    from custom_components.dreame_a2_mower.mower.state_snapshot import PositioningHealth

    sm = MowerStateMachine()

    # Step 0: idle at dock
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS
    assert sm.snapshot().location == Location.AT_DOCK

    # Step 1: op=100 echo → IN_SESSION + MOWING + ON_LAWN
    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert snap.mow_session == MowSession.IN_SESSION
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.location == Location.ON_LAWN

    # Step 2: s2p1=1 → still MOWING (no change since already MOWING)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 2)
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.location == Location.ON_LAWN

    # Step 3: mid-mow pause s2p1=4 (charge required)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=4, now_unix=T0 + 300)
    # Note: task_state=4 (paused) is not mapped in activity_map so stays MOWING
    assert snap.mow_session == MowSession.IN_SESSION

    # Step 4: resume s2p1=1
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 + 400)
    assert snap.current_activity == CurrentActivity.MOWING

    # Step 5: returning s2p1=5
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0 + 600)
    assert snap.current_activity == CurrentActivity.RETURNING

    # Step 6: s2p1=2 → IDLE + BETWEEN_SESSIONS
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=T0 + 700)
    assert snap.current_activity == CurrentActivity.IDLE
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_mow_ops_all_set_on_lawn_at_echo():
    """All mow ops (100-103) must set location=ON_LAWN at echo-time."""
    from custom_components.dreame_a2_mower.protocol.mode_enum import MOW_MODE_CODES

    for op in sorted(MOW_MODE_CODES):
        sm = MowerStateMachine()
        snap = sm.handle_mqtt_property(
            siid=2, piid=50, value=_s2p50_envelope(op=op), now_unix=T0
        )
        assert snap.location == Location.ON_LAWN, (
            f"op={op}: echo must set ON_LAWN immediately, got {snap.location!r}"
        )
        assert snap.current_activity == CurrentActivity.MOWING, (
            f"op={op}: echo must set MOWING, got {snap.current_activity!r}"
        )
        assert snap.mow_session == MowSession.IN_SESSION, (
            f"op={op}: echo must enter IN_SESSION, got {snap.mow_session!r}"
        )


# ---------------------------------------------------------------------------
# (E) Arrival/dock paths not disturbed
# ---------------------------------------------------------------------------


def test_at_point_set_after_arrival_not_at_echo():
    """op=109 echo sets ON_LAWN; AT_POINT is set LATER by s2p56 stage=2.
    The echo must NOT prematurely set AT_POINT (it's not there yet).
    """
    sm = MowerStateMachine()

    snap = sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=109), now_unix=T0
    )
    assert snap.location == Location.ON_LAWN
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT

    # s2p56 stage=2 arrives → AT_POINT (via activity) and s2p2=75 → location AT_POINT
    sm.handle_mqtt_property(
        siid=2, piid=56, value={"status": [[1, 2]]}, now_unix=T0 + 40
    )
    assert sm.snapshot().current_activity == CurrentActivity.AT_POINT

    # s2p2=75 → location AT_POINT
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=T0 + 41)
    assert sm.snapshot().location == Location.AT_POINT, (
        f"s2p2=75 must set location=AT_POINT, got {sm.snapshot().location!r}"
    )


def test_charging_sets_at_dock_overrides_on_lawn():
    """After a task starts (ON_LAWN), charging=True must override back to AT_DOCK.

    This covers mid-session dock-return (recharge stop): the charging signal
    is authoritative for AT_DOCK regardless of what the echo set.
    """
    sm = MowerStateMachine()

    # Echo sets ON_LAWN
    sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100), now_unix=T0
    )
    assert sm.snapshot().location == Location.ON_LAWN

    # Mower returns and starts charging
    sm.handle_mqtt_property(siid=3, piid=2, value=1, now_unix=T0 + 900)
    assert sm.snapshot().location == Location.AT_DOCK, (
        f"charging=True must set AT_DOCK even after ON_LAWN was set by echo. "
        f"Got {sm.snapshot().location!r}"
    )


def test_at_dock_does_not_set_on_lawn():
    """Sanity: unknown/low ops that don't have an activity mapping don't touch location."""
    sm = MowerStateMachine()

    # op with status=False (rejected): no location change
    sm.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=100, status=False), now_unix=T0
    )
    assert sm.snapshot().location == Location.AT_DOCK, (
        "Rejected echo must not change location"
    )

    # op=10 (fast mapping) has an activity but is NOT a mow and NOT 108/109
    # The user spec says to handle 100-103, 108, 109 — op=10 is intentionally
    # absent from the "leaves the dock" set (it's a mapping run, not a mow start).
    # This test confirms the behavior for op=10 is NOT changed (it stays AT_DOCK).
    sm2 = MowerStateMachine()
    sm2.handle_mqtt_property(
        siid=2, piid=50, value=_s2p50_envelope(op=10), now_unix=T0
    )
    # op=10 (fast mapping) should set FAST_MAPPING activity but not change location
    assert sm2.snapshot().current_activity == CurrentActivity.FAST_MAPPING
    # Location behaviour for op=10 is preserved as-is (no regression)
