"""Tests for MowerStateMachine.handle_position."""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state_machine import (
    MowerStateMachine,
)


def test_apply_position_writes_xy():
    sm = MowerStateMachine()
    snap = sm.handle_position(x_m=1.5, y_m=-2.0, north_m=None, east_m=None, now_unix=1000)
    assert snap.position_x_m == 1.5
    assert snap.position_y_m == -2.0
    assert snap.position_north_m is None
    assert snap.position_east_m is None


def test_apply_position_writes_all_four_when_supplied():
    sm = MowerStateMachine()
    snap = sm.handle_position(
        x_m=1.0, y_m=2.0, north_m=3.0, east_m=4.0, now_unix=1000,
    )
    assert snap.position_x_m == 1.0
    assert snap.position_y_m == 2.0
    assert snap.position_north_m == 3.0
    assert snap.position_east_m == 4.0


def test_apply_position_no_op_when_unchanged():
    sm = MowerStateMachine()
    sm.handle_position(x_m=1.0, y_m=2.0, north_m=None, east_m=None, now_unix=1000)
    sm._clear_dirty()
    sm.handle_position(x_m=1.0, y_m=2.0, north_m=None, east_m=None, now_unix=1001)
    assert not sm.is_dirty()


def test_apply_position_freshness_stamped():
    sm = MowerStateMachine()
    snap = sm.handle_position(x_m=1.0, y_m=2.0, north_m=None, east_m=None, now_unix=1000)
    assert snap.field_freshness.get("position_x_m") == 1000
    assert snap.field_freshness.get("position_y_m") == 1000
