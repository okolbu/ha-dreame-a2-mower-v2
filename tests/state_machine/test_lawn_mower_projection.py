"""lawn_mower projection from StateSnapshot."""
from __future__ import annotations
import dataclasses


def _build_snapshot(**overrides):
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    return dataclasses.replace(StateSnapshot.initial(), **overrides)


def test_projection_mowing():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.MOWING,
        mow_session=MowSession.IN_SESSION,
    )
    assert project_activity(s) == LawnMowerActivity.MOWING


def test_projection_paused_in_session():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, MowSession,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.PAUSED,
        mow_session=MowSession.IN_SESSION,
    )
    assert project_activity(s) == LawnMowerActivity.PAUSED


def test_projection_idle_at_dock_is_docked():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, Location,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.IDLE,
        location=Location.AT_DOCK,
    )
    assert project_activity(s) == LawnMowerActivity.DOCKED


def test_projection_idle_on_lawn_is_paused():
    """KEY FIX: IDLE away from dock → PAUSED, not DOCKED."""
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity, Location,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.IDLE,
        location=Location.AT_POINT,
    )
    assert project_activity(s) == LawnMowerActivity.PAUSED


def test_projection_cruising_to_point_is_mowing():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.CRUISING_TO_POINT)
    assert project_activity(s) == LawnMowerActivity.MOWING


def test_projection_at_point_is_paused():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.AT_POINT)
    assert project_activity(s) == LawnMowerActivity.PAUSED


def test_projection_returning():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.RETURNING)
    assert project_activity(s) == LawnMowerActivity.RETURNING


def test_projection_with_error_is_error():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(
        current_activity=CurrentActivity.MOWING,
        errors=frozenset({27}),
    )
    # ERROR wins over MOWING when any error is set
    assert project_activity(s) == LawnMowerActivity.ERROR


def test_projection_charge_resume_is_docked():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.CHARGE_RESUME)
    assert project_activity(s) == LawnMowerActivity.DOCKED


def test_projection_fast_mapping_is_mowing():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.FAST_MAPPING)
    assert project_activity(s) == LawnMowerActivity.MOWING


def test_projection_repositioning_is_mowing():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.REPOSITIONING)
    assert project_activity(s) == LawnMowerActivity.MOWING


def test_projection_driving_blades_up_is_mowing():
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        CurrentActivity,
    )
    from homeassistant.components.lawn_mower import LawnMowerActivity
    s = _build_snapshot(current_activity=CurrentActivity.DRIVING_BLADES_UP)
    assert project_activity(s) == LawnMowerActivity.MOWING
