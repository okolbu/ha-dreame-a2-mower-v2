"""CHARGE_RESUME projection must consider Location.

On g2408, current_activity stays at CHARGE_RESUME if the mower
transitioned via s2p1=6 and never received a follow-up. If the mower
is actually back ON_LAWN (mowing again), the lawn_mower entity must
not show DOCKED — the stale activity shouldn't override the location.
"""
from __future__ import annotations

import dataclasses


def test_charge_resume_on_lawn_projects_to_mowing():
    from homeassistant.components.lawn_mower import LawnMowerActivity
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot, CurrentActivity, Location,
    )
    snap = dataclasses.replace(
        StateSnapshot.initial(),
        current_activity=CurrentActivity.CHARGE_RESUME,
        location=Location.ON_LAWN,
    )
    assert project_activity(snap) == LawnMowerActivity.MOWING


def test_charge_resume_at_dock_still_projects_to_docked():
    from homeassistant.components.lawn_mower import LawnMowerActivity
    from custom_components.dreame_a2_mower.lawn_mower import project_activity
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot, CurrentActivity, Location,
    )
    snap = dataclasses.replace(
        StateSnapshot.initial(),
        current_activity=CurrentActivity.CHARGE_RESUME,
        location=Location.AT_DOCK,
    )
    assert project_activity(snap) == LawnMowerActivity.DOCKED
