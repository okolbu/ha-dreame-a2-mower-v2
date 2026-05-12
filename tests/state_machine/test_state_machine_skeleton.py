"""Skeleton tests — class instantiates, snapshot accessor, dirty flag."""
from __future__ import annotations


def test_state_machine_instantiates_with_initial_snapshot():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    sm = MowerStateMachine()
    assert isinstance(sm.snapshot(), StateSnapshot)


def test_snapshot_returns_same_instance_when_unchanged():
    """Cheap accessor — returns the cached snapshot, not a fresh copy."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    s1 = sm.snapshot()
    s2 = sm.snapshot()
    assert s1 is s2


def test_state_machine_dirty_flag():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    assert sm.is_dirty() is False
    sm._mark_dirty()
    assert sm.is_dirty() is True
    sm._clear_dirty()
    assert sm.is_dirty() is False
