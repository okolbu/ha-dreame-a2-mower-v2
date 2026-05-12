"""handle_mqtt_property — scalar slots (s3p1, s3p2) + freshness."""
from __future__ import annotations


def test_handle_s3p1_updates_battery():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1700000000)
    assert snap.battery_percent == 87
    assert snap.field_freshness["battery_percent"] == 1700000000


def test_handle_s3p2_updates_charging():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    snap = sm.handle_mqtt_property(siid=3, piid=2, value=1, now_unix=1700000000)
    assert snap.charging is True
    snap = sm.handle_mqtt_property(siid=3, piid=2, value=0, now_unix=1700000001)
    assert snap.charging is False


def test_handle_unknown_slot_does_not_raise_and_logs_novel():
    """Unknown (siid, piid) returns snapshot unchanged, no exception."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    before = sm.snapshot()
    snap = sm.handle_mqtt_property(siid=99, piid=99, value="x", now_unix=0)
    assert snap == before


def test_freshness_only_updates_when_value_changes():
    """Re-applying the same value does NOT bump the freshness timestamp."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1000)
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=2000)
    # Same value → no freshness bump, still 1000
    assert sm.snapshot().field_freshness["battery_percent"] == 1000


def test_freshness_bumps_on_value_change():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1000)
    sm.handle_mqtt_property(siid=3, piid=1, value=80, now_unix=2000)
    assert sm.snapshot().field_freshness["battery_percent"] == 2000


def test_s2p1_task_state_done_transitions_to_idle():
    """s2p1 = 2 (task done) → current_activity = IDLE."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=1, now_unix=1000)
    snap = sm.snapshot()
    assert snap.raw_s2p1 == 1
    sm.handle_mqtt_property(siid=2, piid=1, value=2, now_unix=2000)
    snap = sm.snapshot()
    assert snap.current_activity == CurrentActivity.IDLE
    assert snap.raw_s2p1 == 2


def test_s2p1_returning_sets_returning_activity():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=1, value=5, now_unix=1000)
    assert sm.snapshot().current_activity == CurrentActivity.RETURNING


def test_s2p2_event_50_starts_mow_session():
    """s2p2 = 50 (mowing_started) → mow_session = IN_SESSION."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        MowSession, CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=1000)
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.IN_SESSION
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.raw_s2p2 == 50


def test_s2p2_event_48_ends_mow_session():
    """s2p2 = 48 (mowing_complete) → mow_session = BETWEEN_SESSIONS."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        MowSession, CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=1000)
    sm.handle_mqtt_property(siid=2, piid=2, value=48, now_unix=2000)
    snap = sm.snapshot()
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS
    assert snap.current_activity == CurrentActivity.IDLE


def test_s2p2_event_75_signals_arrived_at_point():
    """s2p2 = 75 → location = AT_POINT, current_activity = AT_POINT."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location, CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=1000)
    snap = sm.snapshot()
    assert snap.location == Location.AT_POINT
    assert snap.current_activity == CurrentActivity.AT_POINT


def test_s2p50_op_100_mow_dispatches_mowing():
    """TASK envelope with op=100 (global mow) → current_activity = MOWING."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 100, "exe": True, "status": True}},
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.last_task_op == 100
    assert snap.current_activity == CurrentActivity.MOWING


def test_s2p50_op_109_dispatches_cruise_no_session():
    """op=109 → CRUISING_TO_POINT and mow_session stays BETWEEN_SESSIONS."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 109, "exe": True, "status": True}},
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.last_task_op == 109
    assert snap.current_activity == CurrentActivity.CRUISING_TO_POINT
    # Critical: cruise does NOT enter mow_session
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_s2p56_arrived_stage_transitions():
    """s2p56 [[N, 2]] (lifecycle stage 2) signals arrival from cruise."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    sm = MowerStateMachine()
    # Start cruise
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 109}}, now_unix=1000,
    )
    # Arrive
    sm.handle_mqtt_property(
        siid=2, piid=56,
        value={"status": [[1, 2]]}, now_unix=2000,
    )
    snap = sm.snapshot()
    assert snap.current_activity == CurrentActivity.AT_POINT


def test_s2p50_failed_status_does_not_transition_activity():
    """`status: False` in TASK echo → don't change activity, but DO record op."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 100, "status": False}},
        now_unix=1000,
    )
    assert sm.snapshot().current_activity == CurrentActivity.IDLE
    assert sm.snapshot().last_task_op == 100


def test_s2p50_op_10_fast_mapping():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 10, "status": True}},
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.current_activity == CurrentActivity.FAST_MAPPING
    # Fast mapping is NOT a mow session
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_s2p56_arrival_does_not_transition_if_not_cruising():
    """Stage 2 only flips to AT_POINT when we were CRUISING_TO_POINT.

    For a mow op finishing, stage 2 is handled by s2p1=2 or s2p2=48, not s2p56.
    """
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    sm = MowerStateMachine()
    # Start a mow
    sm.handle_mqtt_property(
        siid=2, piid=50,
        value={"t": "TASK", "d": {"o": 100, "status": True}},
        now_unix=1000,
    )
    # s2p56 stage 2 — should NOT flip to AT_POINT because we're MOWING not CRUISING
    sm.handle_mqtt_property(
        siid=2, piid=56,
        value={"status": [[1, 2]]}, now_unix=2000,
    )
    assert sm.snapshot().current_activity == CurrentActivity.MOWING
