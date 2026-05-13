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
    assert snap_after.current_activity == CurrentActivity.MOWING


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
