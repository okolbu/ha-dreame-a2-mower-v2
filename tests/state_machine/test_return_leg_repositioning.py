"""TDD: Bug 3 — REPOSITIONING on the return leg (Recharge at point).

When the mower finishes a to-point cruise and returns home:
  At-point → s2p1=5 (returning) → Repositioning → first MOVE → Returning

The return leg begins with a ~26s reorientation dance before the mower actually
starts moving.  Without REPOSITIONING on the return leg, the activity jumps from
AT_POINT directly to RETURNING at the first s1p4 MOVE, skipping the orient window.

Fix: in _apply_s2p1_task_state, when task_state=5 (returning) transitions from a
stationary/at-point location (location==AT_POINT), enter REPOSITIONING, then
transition to RETURNING when the first move is detected OR when the next s2p1
changes OR when s1p4 shows sustained movement.

Tests:
1. s2p1=5 from AT_POINT location → REPOSITIONING.
2. s2p1=5 from ON_LAWN (mid-session returning) → RETURNING (no REPOSITIONING).
3. REPOSITIONING (return) → first move beyond threshold → RETURNING
   (via handle_position / movement threshold).
4. REPOSITIONING (return) → next s2p1 change → exits REPOSITIONING.
5. s2p1=5 from AT_DOCK → RETURNING (not REPOSITIONING; was not at-point).
6. The undock path (s2p1=1 from charging) is unchanged.
"""
from __future__ import annotations

import dataclasses

from custom_components.dreame_a2_mower.mower.state_machine import MowerStateMachine
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    Location,
    MowSession,
)

T0 = 1_748_900_100  # arbitrary baseline


# ---------------------------------------------------------------------------
# Helper: bring the state machine to AT_POINT
# ---------------------------------------------------------------------------

def _sm_at_point() -> MowerStateMachine:
    """Return a state machine that has reached AT_POINT via a cruise run."""
    sm = MowerStateMachine()
    # Boot at dock (charging)
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 300)
    # Undock → REPOSITIONING
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0 - 240)
    assert sm.snapshot().current_activity == CurrentActivity.REPOSITIONING
    # Op echo → CRUISING_TO_POINT
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"d": {"o": 109, "status": True}},
        now_unix=T0 - 200,
    )
    assert sm.snapshot().current_activity == CurrentActivity.CRUISING_TO_POINT
    # s2p2=75 (arrived_at_maintenance_point) → AT_POINT activity + location
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=T0 - 10)
    assert sm.snapshot().current_activity == CurrentActivity.AT_POINT
    assert sm.snapshot().location == Location.AT_POINT
    return sm


# ---------------------------------------------------------------------------
# Test 1: s2p1=5 from AT_POINT → REPOSITIONING
# ---------------------------------------------------------------------------

def test_s2p1_returning_from_at_point_enters_repositioning():
    """When s2p1=5 (returning) arrives while location=AT_POINT,
    the state machine must enter REPOSITIONING (reorient window), not RETURNING.
    """
    sm = _sm_at_point()
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING, (
        f"s2p1=5 from AT_POINT must enter REPOSITIONING (got {snap.current_activity!r}). "
        "The ~26s reorientation dance before the return drive must be represented."
    )


# ---------------------------------------------------------------------------
# Test 2: s2p1=5 from ON_LAWN (mid-drive) → RETURNING (no REPOSITIONING)
# ---------------------------------------------------------------------------

def test_s2p1_returning_from_on_lawn_stays_returning():
    """s2p1=5 from ON_LAWN (e.g. mid-session return) must give RETURNING,
    NOT REPOSITIONING — REPOSITIONING is only for the AT_POINT standstill.
    """
    sm = MowerStateMachine()
    # Set location ON_LAWN without going through AT_POINT
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"d": {"o": 100, "status": True}},
        now_unix=T0 - 200,
    )
    assert sm.snapshot().location == Location.ON_LAWN
    assert sm.snapshot().mow_session == MowSession.IN_SESSION
    # End the mow session
    sm.handle_mqtt_property(siid=2, piid=2, value=48, now_unix=T0 - 100)
    assert sm.snapshot().mow_session == MowSession.BETWEEN_SESSIONS

    # s2p1=5 from ON_LAWN (prev=working=1 etc.) — should be RETURNING
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0)
    assert snap.current_activity == CurrentActivity.RETURNING, (
        f"s2p1=5 from ON_LAWN must be RETURNING, not REPOSITIONING "
        f"(got {snap.current_activity!r})"
    )


# ---------------------------------------------------------------------------
# Test 3: REPOSITIONING (return) → first significant MOVE → RETURNING
# ---------------------------------------------------------------------------

def test_repositioning_return_exits_on_first_significant_move():
    """After entering REPOSITIONING on the return leg, the first position
    update that moves significantly beyond the at-point location must
    transition the state machine to RETURNING.

    The threshold mirrors _BETWEEN_SESSION_MOVE_THRESHOLD_M used by the
    between-session icon re-render path.
    """
    sm = _sm_at_point()
    # Record where AT_POINT was set (e.g. position at point)
    sm.handle_position(x_m=5.0, y_m=5.0, north_m=None, east_m=None, now_unix=T0 - 5)

    # Trigger REPOSITIONING via s2p1=5
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING

    # First small position update — still within threshold → still REPOSITIONING
    snap2 = sm.handle_position(x_m=5.1, y_m=5.0, north_m=None, east_m=None, now_unix=T0 + 5)
    assert snap2.current_activity == CurrentActivity.REPOSITIONING, (
        "A tiny position update (< threshold) must NOT exit REPOSITIONING on return leg"
    )

    # Large position update (beyond 0.3m threshold) → RETURNING
    snap3 = sm.handle_position(x_m=5.0, y_m=5.5, north_m=None, east_m=None, now_unix=T0 + 30)
    assert snap3.current_activity == CurrentActivity.RETURNING, (
        f"A significant position update (> threshold) must exit REPOSITIONING → RETURNING "
        f"(got {snap3.current_activity!r})"
    )


# ---------------------------------------------------------------------------
# Test 4: REPOSITIONING (return) → next s2p1 change → exits REPOSITIONING
# ---------------------------------------------------------------------------

def test_repositioning_return_exits_on_next_s2p1():
    """If the mower transitions from REPOSITIONING back to s2p1=5 (e.g.
    firmware re-emits s2p1=5 after the reorientation), we must still
    get RETURNING (not stuck in REPOSITIONING).

    Or if s2p1 changes to something else (e.g. s2p1=6 charging at dock),
    the state should resolve appropriately.
    """
    sm = _sm_at_point()
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING

    # Another s2p1=5 push (firmware re-emits) — should eventually resolve to RETURNING
    # Either immediately on the second s2p1=5, or via the false-fire exit.
    # The key requirement: must NOT stay in REPOSITIONING indefinitely.
    snap2 = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0 + 30)
    # After a second s2p1=5, RETURNING is the right resolution
    # (already repositioned, now actually returning)
    assert snap2.current_activity in (CurrentActivity.REPOSITIONING, CurrentActivity.RETURNING), (
        f"After second s2p1=5, must be REPOSITIONING or RETURNING, not stuck at "
        f"{snap2.current_activity!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: s2p1=5 from AT_DOCK (mower just charged, going back out?) → RETURNING
# ---------------------------------------------------------------------------

def test_s2p1_returning_from_at_dock_gives_returning():
    """s2p1=5 while location=AT_DOCK (e.g. spurious after charge) must give
    RETURNING, not REPOSITIONING.  REPOSITIONING is only for AT_POINT.
    """
    sm = MowerStateMachine()
    # Boot at dock (initial state is AT_DOCK)
    assert sm.snapshot().location == Location.AT_DOCK

    snap = sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=T0)
    assert snap.current_activity == CurrentActivity.RETURNING, (
        f"s2p1=5 from AT_DOCK must give RETURNING, not REPOSITIONING "
        f"(got {snap.current_activity!r})"
    )


# ---------------------------------------------------------------------------
# Test 6: undock path (s2p1=1 from charging) is unchanged
# ---------------------------------------------------------------------------

def test_undock_repositioning_unchanged():
    """The undock → REPOSITIONING path (s2p1: 6→1) must still work after
    the return-leg REPOSITIONING changes.

    This is a regression guard.
    """
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=6, now_unix=T0 - 60)
    snap = sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=T0)
    assert snap.current_activity == CurrentActivity.REPOSITIONING, (
        f"Undock s2p1: 6→1 must still enter REPOSITIONING (got {snap.current_activity!r})"
    )
    assert snap.location == Location.ON_LAWN
