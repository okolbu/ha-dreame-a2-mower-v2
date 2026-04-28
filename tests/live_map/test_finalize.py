"""Tests for live_map/finalize.py."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.finalize import (
    FinalizeAction,
    decide,
)
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_decide_default_returns_noop():
    """Stub gate returns NOOP. F5.5 fills in the real logic + tests."""
    state = MowerState()
    assert decide(state, prev_task_state=None, now_unix=1000) == FinalizeAction.NOOP


def test_finalize_action_enum_has_six_values():
    assert {a.name for a in FinalizeAction} == {
        "NOOP", "BEGIN_SESSION", "BEGIN_LEG",
        "FINALIZE_COMPLETE", "FINALIZE_INCOMPLETE", "AWAIT_OSS_FETCH",
    }
