"""To-point (op=109) session-end: root cause + fix verification.

== Pinned cause (why the periodic-retry path alone couldn't fix it) ==

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

== The fix (Option A) ==

Two new triggers bypass the stuck periodic-retry gate entirely:

1. s2p2=75 (arrived_at_maintenance_point) fires inside the `_apply()` closure
   in `_mqtt_handlers.py` and schedules `_finalize_non_mow_immediate()` on the
   event loop. This is the primary, to-point-specific arrival signal.

2. Task-state edge 0/4→2/None inside `_on_state_update` — catches the
   structural completion signal BEFORE `_prev_task_state` is advanced (so the
   edge is still visible at that point). This is the robustness fallback in
   case s2p2=75 is delayed or missed.

Both triggers guard on `not _provisional_session_is_cloud_finalized()` so mow
and patrol sessions are NEVER affected. The `_run_finalize_incomplete` call that
follows also drops the prior `_wait_for_dock_return` in the non-cloud-finalized
branch of `_dispatch_finalize_action` — the return drive is no longer captured
(it is not part of the to-point session semantics).

Tests below pin the mow-unchanged / state-machine aspects (sections a–c)
and the fixed behavior (section d).
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
    """Once _prev_task_state is 2, finalize.decide() returns NOOP — explains the bug.

    This documents WHY the periodic-retry gate alone was not sufficient:
    by the time the 60-second _periodic_session_retry fires, _prev_task_state
    has already been set to 2 by _on_state_update (coordinator/
    _mqtt_handlers.py:517). decide() sees prev=2, task_state=2, which does
    NOT satisfy `prev ∈ {0, 4}`, so it returns NOOP.

    The fix adds new triggers (s2p2=75 and task-state edge-catch) that bypass
    this gate entirely — so finalize.decide() is never consulted for a to-point
    arrival. This test documents the gate behaviour that made the bug manifest;
    it remains CORRECT for finalize.decide() itself (that function is unchanged).
    """
    state = MowerState(task_state_code=2)
    # Simulate the 60-second poll *after* _prev_task_state was already set to 2
    action = decide(state, prev_task_state=2, now_unix=T0 + 100)
    assert action == FinalizeAction.NOOP, (
        f"Expected NOOP (confirming decide() gate behaviour), got {action!r}"
    )


def test_finalize_poll_sequence_demonstrates_stuck_session():
    """Full poll sequence shows finalize.decide() never fires for op=109 alone.

    Documents the root-cause mechanism: the periodic retry loop only consults
    finalize.decide(), which sees prev=2 on every tick and returns NOOP.
    This is why the fix does NOT rely on finalize.decide() for to-point sessions
    — it adds new side-channel triggers (s2p2=75, task-state edge) instead.

    finalize.decide() itself is unchanged; these NOOP assertions remain correct
    for that function. What changed is that the new triggers call
    _finalize_non_mow_immediate() directly, so decide() is never consulted.
    """
    # After _on_state_update processed the 0→2 edge, _prev_task_state = 2
    state = MowerState(task_state_code=2, pending_session_object_name=None)

    for tick in range(5):
        action = decide(state, prev_task_state=2, now_unix=T0 + 100 + tick * 60)
        assert action == FinalizeAction.NOOP, (
            f"Tick {tick}: expected NOOP from decide() (still correct; "
            f"fix bypasses decide() for to-point sessions), got {action!r}"
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


# ---------------------------------------------------------------------------
# (d) Fixed behavior: _finalize_non_mow_immediate + guard logic
#
# These tests pin the Option-A fix:
#   1. _finalize_non_mow_immediate calls _run_finalize_incomplete and ends
#      the live_map session.
#   2. It skips (no-ops) when live_map is not active.
#   3. It refuses (no-ops + warning) when the session is cloud-finalized.
#   4. The s2p2=75 trigger fires for non-mow sessions but NOT mow sessions
#      (provisional classification guard).
#   5. A to-point run that never delivers the s2p56 0→2 edge still finalizes
#      via s2p2=75 alone.
#   6. The task-state edge 0→2 (robustness) also triggers immediate finalize
#      for non-mow sessions.
# ---------------------------------------------------------------------------


def _build_finalize_coord():
    """Minimal coordinator stub wired for _finalize_non_mow_immediate tests.

    Uses __new__ (no HA imports) and wires the subset of attributes that
    _finalize_non_mow_immediate + _run_finalize_incomplete need.
    """
    import asyncio
    import types
    from unittest.mock import MagicMock

    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.archive.session import SessionArchive
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin

    c = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    c.live_map = LiveMapState()
    c.data = MowerState()
    c._active_map_id = 0
    c._rain_delay_started_at = None
    c._lifecycle_event = None
    c._notification_event = None
    # Synchronous double-finalize race latch (owned by _CoreMixin.__init__).
    # Tests build via __new__ so we must seed it manually.
    c._non_mow_finalize_in_progress = False

    # Bind _finalize_non_mow_immediate and _run_finalize_incomplete as bound methods.
    # _SessionMixin is a mixin with no __init__; bind via __get__ so `self` resolves.
    c._finalize_non_mow_immediate = _SessionMixin._finalize_non_mow_immediate.__get__(c)
    c._run_finalize_incomplete = _SessionMixin._run_finalize_incomplete.__get__(c)
    c._provisional_session_is_cloud_finalized = (
        _SessionMixin._provisional_session_is_cloud_finalized.__get__(c)
    )
    c._provisional_session_type = _SessionMixin._provisional_session_type.__get__(c)
    c._resolve_finalize_map_id = _SessionMixin._resolve_finalize_map_id.__get__(c)
    c._inject_live_map_into_raw_dict = MagicMock()  # suppress archive enrichment
    c._fire_mowing_ended = MagicMock()              # suppress event firing

    # SessionArchive backed by a real tmp dir for archive() + delete_in_progress().
    import tempfile
    tmpdir = tempfile.mkdtemp()
    c.session_archive = SessionArchive(tmpdir)

    # Fake hass: executor jobs run inline; async_set_updated_data updates c.data.
    hass = MagicMock()

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    c.hass = hass

    def _set_data(new):
        c.data = new

    c.async_set_updated_data = _set_data

    # cloud_state needed by _resolve_finalize_map_id fallback.
    c.cloud_state = MagicMock()
    c.cloud_state.maps_by_id = {}

    return c


async def test_finalize_non_mow_immediate_ends_session():
    """_finalize_non_mow_immediate calls _run_finalize_incomplete and ends
    live_map when the session is active and non-cloud-finalized."""
    c = _build_finalize_coord()
    now = T0 + 45

    # Set up a minimal non-mow live_map session (no 50/53 → maintenance_run).
    c.live_map.begin_session(T0)
    c.live_map.last_task_op = 109  # op=109: non-cloud-finalized
    c.live_map.append_point(t=T0 + 1, x_m=0.0, y_m=0.0, area_m2=0.0, heading_deg=0.0)

    assert c.live_map.is_active(), "precondition: session must be active"
    assert not c._provisional_session_is_cloud_finalized(), (
        "precondition: op=109 session must be non-cloud-finalized"
    )

    await c._finalize_non_mow_immediate(now, "s2p2=75")

    assert not c.live_map.is_active(), (
        "live_map.is_active() should be False after _finalize_non_mow_immediate"
    )


async def test_finalize_non_mow_immediate_noop_when_not_active():
    """_finalize_non_mow_immediate is a no-op when live_map is not active.
    Guards against double-finalize."""
    c = _build_finalize_coord()
    # live_map not started
    assert not c.live_map.is_active()

    # Should not raise, should not call _run_finalize_incomplete.
    original_run_finalize = c._run_finalize_incomplete
    finalize_called = []

    async def _spy(now):
        finalize_called.append(now)
        await original_run_finalize(now)

    c._run_finalize_incomplete = _spy
    await c._finalize_non_mow_immediate(T0, "s2p2=75")

    assert not finalize_called, (
        "_run_finalize_incomplete should NOT be called when live_map is not active"
    )


async def test_finalize_non_mow_immediate_refuses_cloud_finalized_session():
    """_finalize_non_mow_immediate refuses to finalize a cloud-finalized (mow)
    session — the hard guard that prevents mow path from being corrupted."""
    c = _build_finalize_coord()
    now = T0 + 45

    # Set up a mow session (error_samples with 50 → mow start → cloud-finalized).
    c.live_map.begin_session(T0)
    c.live_map.last_task_op = 100       # op=100: mow
    c.live_map.error_samples = [(T0 + 1, 50)]  # mow-start code
    c.live_map.area_ever_positive = True

    assert c.live_map.is_active(), "precondition: session must be active"
    assert c._provisional_session_is_cloud_finalized(), (
        "precondition: mow session must be cloud-finalized"
    )

    finalize_called = []
    original_run = c._run_finalize_incomplete

    async def _spy(n):
        finalize_called.append(n)
        await original_run(n)

    c._run_finalize_incomplete = _spy
    await c._finalize_non_mow_immediate(now, "test")

    assert not finalize_called, (
        "_run_finalize_incomplete must NOT be called for a cloud-finalized (mow) session"
    )
    assert c.live_map.is_active(), (
        "live_map should remain active — mow session must not be touched here"
    )


async def test_to_point_finalizes_on_s2p2_75_even_without_s2p56_edge():
    """A to-point run that never delivers the s2p56 0→2 edge still finalizes
    when s2p2=75 arrives.

    This tests the primary requirement: the s2p2=75 trigger is the fail-safe.
    Even if the s2p56 [[1,0]]→[[1,2]] MQTT push was dropped, the session ends
    cleanly at arrival.
    """
    c = _build_finalize_coord()
    now = T0 + 45

    # Session active with op=109, no s2p56 edge delivered (task_state_code stays
    # at 0, not 2 — simulating a missed s2p56 push).
    c.live_map.begin_session(T0)
    c.live_map.last_task_op = 109
    c.live_map.append_point(t=T0 + 1, x_m=5.0, y_m=3.0, area_m2=0.0, heading_deg=0.0)

    assert c.live_map.is_active()
    assert not c._provisional_session_is_cloud_finalized()

    # Simulate s2p2=75 trigger (what _apply() schedules in _mqtt_handlers.py).
    await c._finalize_non_mow_immediate(now, "s2p2=75")

    assert not c.live_map.is_active(), (
        "Session should end on s2p2=75 even though s2p56 0→2 edge was never delivered"
    )


async def test_task_state_edge_finalizes_non_mow_session():
    """The task-state edge catch (0→2) also triggers immediate finalize for
    non-mow sessions (robustness path, in case s2p2=75 is delayed or missed).

    _finalize_non_mow_immediate is the method that both triggers call.
    This test verifies it works for the 0→2 edge case.
    """
    c = _build_finalize_coord()
    now = T0 + 40

    c.live_map.begin_session(T0)
    c.live_map.last_task_op = 109  # op=109: non-cloud-finalized
    c.live_map.append_point(t=T0 + 1, x_m=2.0, y_m=2.0, area_m2=0.0, heading_deg=0.0)

    assert c.live_map.is_active()
    assert not c._provisional_session_is_cloud_finalized()

    # Simulate task-state edge trigger (what _on_state_update schedules).
    await c._finalize_non_mow_immediate(now, "task_state_edge")

    assert not c.live_map.is_active(), (
        "Session should end via the task-state edge trigger (robustness path)"
    )


async def test_mow_session_not_affected_by_s2p2_75_guard():
    """The s2p2=75 trigger guard: mow sessions are classified as cloud-finalized
    and _finalize_non_mow_immediate refuses to finalize them.

    This pins the load-bearing requirement: the mow path must be UNCHANGED.
    """
    c = _build_finalize_coord()
    now = T0 + 40

    # A mow session: op=100, error_samples has code 50 (mow-start), area grew.
    c.live_map.begin_session(T0)
    c.live_map.last_task_op = 100
    c.live_map.error_samples = [(T0 + 1, 50)]  # s2p2=50 mow-start code
    c.live_map.area_ever_positive = True
    c.live_map.append_point(t=T0 + 5, x_m=10.0, y_m=10.0, area_m2=5.0, heading_deg=90.0)

    assert c.live_map.is_active()
    assert c._provisional_session_is_cloud_finalized(), (
        "mow session (op=100 + s2p2=50 + area_ever_positive) must be cloud-finalized"
    )

    # _finalize_non_mow_immediate is guarded: must NOT end a mow session.
    await c._finalize_non_mow_immediate(now, "s2p2=75")

    assert c.live_map.is_active(), (
        "Mow session must NOT be ended by s2p2=75 trigger — guard failed"
    )


# ---------------------------------------------------------------------------
# (e) Double-finalize race guard: both triggers fire concurrently
# ---------------------------------------------------------------------------


async def test_double_trigger_finalizes_exactly_once():
    """Both s2p2=75 AND the task_state 0→2 edge arrive within ~1 s, each
    scheduling _finalize_non_mow_immediate as a separate async task.

    Without the _non_mow_finalize_in_progress latch both tasks can pass the
    live_map.is_active() guard before either reaches end_session() (the first
    yields at an await inside _run_finalize_incomplete).  With the latch the
    second caller sees the flag already set and bails — so the session is
    archived EXACTLY once.

    Strategy: run both coroutines as true concurrent tasks on a real event loop
    so that the synchronous latch is exercised at the natural yield point inside
    _run_finalize_incomplete (hass.async_add_executor_job).
    """
    import asyncio
    from unittest.mock import MagicMock

    c = _build_finalize_coord()
    now = T0 + 41

    c.live_map.begin_session(T0)
    c.live_map.last_task_op = 109
    c.live_map.append_point(t=T0 + 1, x_m=1.0, y_m=1.0, area_m2=0.0, heading_deg=0.0)

    assert c.live_map.is_active(), "precondition: session active"
    assert not c._provisional_session_is_cloud_finalized(), (
        "precondition: non-cloud-finalized"
    )

    # Count how many times _run_finalize_incomplete actually executes its body.
    # We wrap the REAL method so archive writes still happen; we just count calls.
    from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin
    real_run_finalize = _SessionMixin._run_finalize_incomplete

    finalize_body_calls: list[int] = []

    async def _counting_run_finalize(self_inner, now_ts):
        finalize_body_calls.append(now_ts)
        await real_run_finalize(self_inner, now_ts)

    c._run_finalize_incomplete = _counting_run_finalize.__get__(c)

    # Schedule both triggers as concurrent tasks — mirrors what the event loop
    # does when s2p2=75 and the 0→2 edge arrive within the same ~1 s window.
    task_a = asyncio.create_task(c._finalize_non_mow_immediate(now, "s2p2=75"))
    task_b = asyncio.create_task(c._finalize_non_mow_immediate(now, "task_state_edge"))
    await asyncio.gather(task_a, task_b)

    assert len(finalize_body_calls) == 1, (
        f"_run_finalize_incomplete must be called exactly ONCE; called {len(finalize_body_calls)} "
        f"time(s). Double-finalize race latch (_non_mow_finalize_in_progress) is broken."
    )
    assert not c.live_map.is_active(), (
        "live_map must be inactive after finalize"
    )
    # Exactly one archived entry.
    entries = c.session_archive.list_sessions()
    assert len(entries) == 1, (
        f"Expected exactly 1 archived entry, got {len(entries)}: {entries}"
    )
