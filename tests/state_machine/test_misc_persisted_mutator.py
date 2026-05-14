"""Tests for MowerStateMachine.handle_misc_persisted + the
session-conditioned CHARGE_RESUME mapping in _apply_s2p1_task_state.

handle_misc_persisted is the writer for the three snapshot-backed
diagnostic sensors: mowing_phase, task_state_code, slam_task_label.
Survival across HA restart is exercised by the existing snapshot
persistence tests; here we only verify the mutator contract.

The CHARGE_RESUME-session-conditioning is in the same file because the
fix lands as part of the same release.
"""
from __future__ import annotations

import dataclasses

from custom_components.dreame_a2_mower.mower.state_machine import (
    MowerStateMachine,
)
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    CurrentActivity,
    MowSession,
)


# ---------------------------------------------------------------------------
# handle_misc_persisted
# ---------------------------------------------------------------------------

def test_handle_misc_persisted_sets_single_field_and_stamps_freshness():
    sm = MowerStateMachine()
    snap = sm.handle_misc_persisted(mowing_phase=15, now_unix=1000)
    assert snap.mowing_phase == 15
    assert snap.task_state_code is None
    assert snap.slam_task_label is None
    assert snap.field_freshness.get("mowing_phase") == 1000


def test_handle_misc_persisted_sets_all_three_when_supplied():
    sm = MowerStateMachine()
    snap = sm.handle_misc_persisted(
        mowing_phase=15,
        task_state_code=53,
        slam_task_label="mowing",
        now_unix=1000,
    )
    assert snap.mowing_phase == 15
    assert snap.task_state_code == 53
    assert snap.slam_task_label == "mowing"
    assert snap.field_freshness.get("mowing_phase") == 1000
    assert snap.field_freshness.get("task_state_code") == 1000
    assert snap.field_freshness.get("slam_task_label") == 1000


def test_handle_misc_persisted_no_op_when_value_unchanged():
    sm = MowerStateMachine()
    sm.handle_misc_persisted(mowing_phase=15, now_unix=1000)
    sm._clear_dirty()
    snap = sm.handle_misc_persisted(mowing_phase=15, now_unix=2000)
    assert not sm.is_dirty()
    # Freshness for unchanged value must NOT bump.
    assert snap.field_freshness.get("mowing_phase") == 1000


def test_handle_misc_persisted_skips_none_inputs():
    """None inputs leave the corresponding field alone (no overwrite)."""
    sm = MowerStateMachine()
    sm.handle_misc_persisted(
        mowing_phase=15,
        task_state_code=53,
        slam_task_label="mowing",
        now_unix=1000,
    )
    # Re-call with all None → should be a complete no-op.
    sm._clear_dirty()
    snap = sm.handle_misc_persisted(
        mowing_phase=None,
        task_state_code=None,
        slam_task_label=None,
        now_unix=2000,
    )
    assert not sm.is_dirty()
    assert snap.mowing_phase == 15
    assert snap.task_state_code == 53
    assert snap.slam_task_label == "mowing"


def test_handle_misc_persisted_partial_update_preserves_others():
    sm = MowerStateMachine()
    sm.handle_misc_persisted(
        mowing_phase=15,
        task_state_code=53,
        slam_task_label="mowing",
        now_unix=1000,
    )
    snap = sm.handle_misc_persisted(task_state_code=99, now_unix=2000)
    assert snap.mowing_phase == 15
    assert snap.task_state_code == 99
    assert snap.slam_task_label == "mowing"
    # Only the changed field's freshness bumps.
    assert snap.field_freshness.get("mowing_phase") == 1000
    assert snap.field_freshness.get("task_state_code") == 2000
    assert snap.field_freshness.get("slam_task_label") == 1000


# ---------------------------------------------------------------------------
# task_state=6 (charging) → activity depends on mow_session
# ---------------------------------------------------------------------------

def _seed_mow_session(sm: MowerStateMachine, session: MowSession) -> None:
    """Force the snapshot into a chosen MowSession for testing."""
    sm._snapshot = dataclasses.replace(sm._snapshot, mow_session=session)


def test_task_state_6_in_session_maps_to_charge_resume():
    sm = MowerStateMachine()
    _seed_mow_session(sm, MowSession.IN_SESSION)
    snap = sm._apply_s2p1_task_state(6, now_unix=1000)
    assert snap.current_activity == CurrentActivity.CHARGE_RESUME
    assert snap.mow_session == MowSession.IN_SESSION
    assert snap.raw_s2p1 == 6


def test_task_state_6_between_sessions_maps_to_idle():
    """Idle-charging at the dock with no active session must surface as
    IDLE, not CHARGE_RESUME (the "Charging mid-session" label is
    misleading outside a session)."""
    sm = MowerStateMachine()
    _seed_mow_session(sm, MowSession.BETWEEN_SESSIONS)
    snap = sm._apply_s2p1_task_state(6, now_unix=1000)
    assert snap.current_activity == CurrentActivity.IDLE
    assert snap.mow_session == MowSession.BETWEEN_SESSIONS
    assert snap.raw_s2p1 == 6
