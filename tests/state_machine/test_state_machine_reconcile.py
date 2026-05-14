"""Tests for reconcile_from_telemetry — cold-boot state inference.

When the integration starts during an active mow, the start events
(s2p1=1, s2p2=50, s2p50 op=100) already fired hours ago. MQTT
properties_changed only fires on change, so we never receive them
post-subscribe. Telemetry (battery, position, area_mowed, live_map)
keeps flowing — those are the signals we use to infer that a mow
session is actually in progress.

The user's caveat: telemetry alone can't distinguish a mow from a
cruise-to-point. Only mow-specific signals (area_mowed_m2 > 0) make
the inference safe.
"""
from __future__ import annotations


def test_reconcile_idle_to_mowing_when_live_map_active_and_area_mowed():
    """live_map active + area_mowed > 0 → infer MOWING + IN_SESSION."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    # Initial: IDLE + BETWEEN_SESSIONS (typical post-boot)
    sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=42.0,
        position_x_m=5.0, position_y_m=-3.0,
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.current_activity == CurrentActivity.MOWING
    assert snap.mow_session == MowSession.IN_SESSION


def test_reconcile_does_not_assume_mowing_for_cruise():
    """live_map active + area_mowed == 0 → don't infer MOWING (could be cruise)."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=0.0,
        position_x_m=5.0, position_y_m=-3.0,
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    snap = sm.snapshot()
    # Stays at initial IDLE + BETWEEN_SESSIONS — too ambiguous to claim a mow
    assert snap.current_activity == CurrentActivity.IDLE
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS


def test_reconcile_does_not_overwrite_authoritative_state():
    """If state machine ALREADY in MOWING (from a real start event), don't
    overwrite. The reconciliation is for the boot-window gap only."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    sm = MowerStateMachine()
    # Seed from a real start event
    sm.handle_mqtt_property(siid=2, piid=2, value=50, now_unix=500)
    assert sm.snapshot().mow_session == MowSession.IN_SESSION
    # Keep position on dock so the location inference is a no-op and we
    # isolate the mow-session-overwrite check.
    sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=42.0,
        position_x_m=0.15, position_y_m=0.01,
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    snap_after = sm.snapshot()
    # mow_session was already IN_SESSION; reconcile must not bump or churn it
    assert snap_after.mow_session == MowSession.IN_SESSION
    # mow_session freshness must not have been re-stamped by reconcile —
    # 500 is when s2p2=50 set it.
    assert snap_after.field_freshness["mow_session"] == 500


def test_reconcile_location_at_dock_to_on_lawn_when_position_far():
    """position far from dock + location=AT_DOCK → flip to ON_LAWN."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location,
    )
    sm = MowerStateMachine()
    # Default location is AT_DOCK
    assert sm.snapshot().location == Location.AT_DOCK
    sm.reconcile_from_telemetry(
        live_map_active=False,
        area_mowed_m2=0.0,
        position_x_m=8.5,   # mower position in metres
        position_y_m=-4.2,
        dock_x_mm=155, dock_y_mm=10,  # dock in mm — different units
        now_unix=1000,
    )
    # Position (8.5m, -4.2m) is ~8.5m from (0.155m, 0.01m) dock — clearly off-dock
    assert sm.snapshot().location == Location.ON_LAWN


def test_reconcile_location_stays_at_dock_when_position_near_dock():
    """position near dock origin → stay AT_DOCK."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location,
    )
    sm = MowerStateMachine()
    sm.reconcile_from_telemetry(
        live_map_active=False,
        area_mowed_m2=0.0,
        position_x_m=0.2,   # 20cm from origin — on dock
        position_y_m=0.05,
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    assert sm.snapshot().location == Location.AT_DOCK


def test_reconcile_handles_none_position():
    """No position data → don't change location."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location,
    )
    sm = MowerStateMachine()
    sm.reconcile_from_telemetry(
        live_map_active=False,
        area_mowed_m2=0.0,
        position_x_m=None, position_y_m=None,
        dock_x_mm=None, dock_y_mm=None,
        now_unix=1000,
    )
    # Stays at initial AT_DOCK
    assert sm.snapshot().location == Location.AT_DOCK


def test_reconcile_overrides_stuck_charge_resume_when_area_increasing():
    """If state machine is stuck at CHARGE_RESUME but area_mowed is still
    increasing, the mower has clearly resumed mowing. Reconcile must
    update current_activity to MOWING.

    The MQTT s2p1=1 message that would normally trigger this transition
    only fires on change — if the integration was offline at the moment
    the mower transitioned 6→1, that signal is gone forever."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession, Location,
    )
    import dataclasses
    sm = MowerStateMachine()
    # Set state machine to "stuck" CHARGE_RESUME + IN_SESSION + ON_LAWN
    sm._snapshot = dataclasses.replace(
        sm._snapshot,
        mow_session=MowSession.IN_SESSION,
        current_activity=CurrentActivity.CHARGE_RESUME,
        location=Location.ON_LAWN,
    )
    # Area mowed increased → real evidence of mowing
    sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=120.0,  # > 0
        position_x_m=5.0, position_y_m=-3.0,
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    snap = sm.snapshot()
    assert snap.current_activity == CurrentActivity.MOWING


def test_reconcile_does_not_override_authoritative_charge_resume_at_dock():
    """If state machine is CHARGE_RESUME and location is AT_DOCK, the
    mower is genuinely charging on the dock — reconcile must not flip."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession, Location,
    )
    import dataclasses
    sm = MowerStateMachine()
    sm._snapshot = dataclasses.replace(
        sm._snapshot,
        mow_session=MowSession.IN_SESSION,
        current_activity=CurrentActivity.CHARGE_RESUME,
        location=Location.AT_DOCK,
    )
    sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=120.0,
        position_x_m=0.1, position_y_m=0.05,  # at dock
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    assert sm.snapshot().current_activity == CurrentActivity.CHARGE_RESUME


def test_reconcile_flips_stuck_mowing_to_charge_resume_at_dock():
    """Mirror of the CHARGE_RESUME→MOWING case: state machine was
    seeded IN_SESSION+MOWING via _restore_in_progress, mower then
    returned to dock to charge, but the s2p1=6/CHARGE_RESUME push was
    missed (integration was reloading at that moment). Now AT_DOCK +
    IN_SESSION but activity stuck at MOWING. Flip to CHARGE_RESUME so
    the lawn_mower entity projects to DOCKED instead of MOWING."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession, Location,
    )
    import dataclasses
    sm = MowerStateMachine()
    sm._snapshot = dataclasses.replace(
        sm._snapshot,
        mow_session=MowSession.IN_SESSION,
        current_activity=CurrentActivity.MOWING,
        location=Location.AT_DOCK,
    )
    sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=120.0,
        position_x_m=0.1, position_y_m=0.05,  # at dock
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    assert sm.snapshot().current_activity == CurrentActivity.CHARGE_RESUME


def test_reconcile_does_not_clobber_explicit_at_point_location():
    """location=AT_POINT (from s2p2=75) must not be overwritten to ON_LAWN
    just because position is non-zero. The user is AT a maintenance point."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        Location,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=2, piid=2, value=75, now_unix=500)
    assert sm.snapshot().location == Location.AT_POINT
    sm.reconcile_from_telemetry(
        live_map_active=False,
        area_mowed_m2=0.0,
        position_x_m=8.5, position_y_m=-4.2,
        dock_x_mm=155, dock_y_mm=10,
        now_unix=1000,
    )
    # AT_POINT is preserved
    assert sm.snapshot().location == Location.AT_POINT


def test_reconcile_resolves_stuck_charge_resume_between_sessions():
    """Persistent CHARGE_RESUME outside a session should self-heal to IDLE.

    v1.0.10a3 fixed _apply_s2p1_task_state so future task_state=6 events
    outside a session map to IDLE, but a snapshot persisted with
    CHARGE_RESUME under the old logic stuck around until the next s2p1
    event. The reconcile case picks it up on the next 10 s tick."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    import dataclasses
    sm = MowerStateMachine()
    sm._snapshot = dataclasses.replace(
        sm._snapshot,
        mow_session=MowSession.BETWEEN_SESSIONS,
        current_activity=CurrentActivity.CHARGE_RESUME,
    )
    sm.reconcile_from_telemetry(
        live_map_active=False,
        area_mowed_m2=None,
        position_x_m=None,
        position_y_m=None,
        dock_x_mm=None,
        dock_y_mm=None,
        now_unix=1000,
    )
    assert sm.snapshot().current_activity == CurrentActivity.IDLE


def test_reconcile_preserves_charge_resume_in_session():
    """Mid-session CHARGE_RESUME must NOT be reset by the out-of-session
    self-heal — that's a legitimate recharge boundary inside a mow."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession, Location,
    )
    import dataclasses
    sm = MowerStateMachine()
    sm._snapshot = dataclasses.replace(
        sm._snapshot,
        mow_session=MowSession.IN_SESSION,
        current_activity=CurrentActivity.CHARGE_RESUME,
        location=Location.AT_DOCK,
    )
    sm.reconcile_from_telemetry(
        live_map_active=True,
        area_mowed_m2=0.5,
        position_x_m=0.1, position_y_m=0.05,
        dock_x_mm=0, dock_y_mm=0,
        now_unix=1000,
    )
    assert sm.snapshot().current_activity == CurrentActivity.CHARGE_RESUME
