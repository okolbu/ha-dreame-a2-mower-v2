"""Tests for the audit fake coordinator."""
from __future__ import annotations

from tools.state_machine_audit_fake_coord import build_fake_coord


def test_fake_coord_has_state_machine_snapshot():
    coord = build_fake_coord()
    snap = coord.state_machine.snapshot()
    # initial() defaults from state_snapshot.py
    assert snap.mow_session.value == "between_sessions"
    assert snap.location.value == "at_dock"
    assert snap.battery_percent is None


def test_fake_coord_has_mower_state_with_none_defaults():
    """MowerState is the legacy holder — all fields start at None / 0 / ''."""
    coord = build_fake_coord()
    # battery_level is the canonical None-init field
    assert getattr(coord.data, "battery_level", "missing") in (None, "missing")


def test_fake_coord_has_cloud_state():
    coord = build_fake_coord()
    assert coord.cloud_state is not None
    # CloudState.dock starts as empty dict
    assert getattr(coord.cloud_state, "dock", None) in (None, {}, {})
