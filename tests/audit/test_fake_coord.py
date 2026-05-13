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


from tools.state_machine_audit_fake_coord import observe_cold_value


def test_observe_snapshot_field_returns_initial():
    """An entity reading snapshot.location should see Location.AT_DOCK (initial)."""
    src = (
        "lambda coord: "
        "coord.state_machine.snapshot().location.value"
    )
    val, exc = observe_cold_value(src)
    assert exc is None
    assert val == "at_dock"


def test_observe_mower_state_field_returns_none():
    """coord.data.battery_level starts as None on a fresh MowerState."""
    src = "lambda s: s.battery_level"
    # value_fn shorthand `lambda s:` takes data, not the coord.
    val, exc = observe_cold_value(src, arg_kind="data")
    assert exc is None
    assert val is None


def test_observe_returns_exception_on_attr_error():
    """An unreachable attribute should be reported as an exception, not crash."""
    src = "lambda coord: coord.nonexistent_attr.subfield"
    val, exc = observe_cold_value(src)
    # _PermissiveCoord.__getattr__ returns None → .subfield AttributeError
    assert exc is not None


def test_observe_can_reference_location_enum():
    """The Location enum must be in scope when value_fns reference it.

    Regression: an earlier implementation passed _eval_globals as locals
    instead of globals; the lambda's frame couldn't see the enum names.
    """
    src = "lambda coord: coord.state_machine.snapshot().location == Location.AT_DOCK"
    val, exc = observe_cold_value(src)
    assert exc is None, f"expected no exception, got {exc!r}"
    assert val is True
