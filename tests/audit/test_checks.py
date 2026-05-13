"""Tests for the three audit checks."""
from __future__ import annotations

from pathlib import Path

from tools.state_machine_audit_checks import load_expectations

ROOT = Path(__file__).resolve().parent.parent.parent
YAML = ROOT / "tools" / "state_machine_audit_expectations.yaml"


def test_load_expectations_parses_known_entries():
    exp = load_expectations(YAML)
    assert "binary_sensor.mower_in_dock" in exp
    assert exp["binary_sensor.mower_in_dock"].idle is True
    assert exp["sensor.battery_level"].idle == "persisted_value"
    assert exp["sensor.area_mowed_m2"].idle == 0
    assert exp["sensor.battery_level"].reboot == "required"


def test_load_expectations_raises_on_missing_file():
    from tools.state_machine_audit_checks import load_expectations

    try:
        load_expectations(Path("/nonexistent/path.yaml"))
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


from tools.state_machine_audit_discover import EntityDescriptor
from tools.state_machine_audit_checks import (
    SNAPSHOT_FIELDS,
    check_sourcing,
    Expectation,
    Result,
)


def test_snapshot_fields_includes_known():
    """SNAPSHOT_FIELDS is derived from StateSnapshot — must contain known names."""
    assert "battery_percent" in SNAPSHOT_FIELDS
    assert "location" in SNAPSHOT_FIELDS
    assert "mow_session" in SNAPSHOT_FIELDS
    # MowerState-only fields must NOT be in the set:
    assert "obstacle_flag" not in SNAPSHOT_FIELDS


def test_sourcing_green_when_battery_reads_snapshot():
    ed = EntityDescriptor(
        platform="sensor",
        key="battery_level",
        name="Battery",
        value_fn_src="lambda coord: coord.state_machine.snapshot().battery_percent",
        source_file="sensor.py",
        line=126,
    )
    r = check_sourcing(ed)
    assert r.status == "green"


def test_sourcing_red_when_battery_reads_mower_state():
    """battery_percent is snapshot-owned; reading from MowerState = RED."""
    ed = EntityDescriptor(
        platform="sensor",
        key="battery_level",
        name="Battery",
        value_fn_src="lambda s: s.battery_percent",
        source_file="sensor.py",
        line=126,
    )
    r = check_sourcing(ed)
    assert r.status == "red"
    assert "battery_percent" in r.detail


from tools.state_machine_audit_checks import check_idle


def test_idle_green_when_mower_in_dock_returns_true():
    ed = EntityDescriptor(
        platform="binary_sensor",
        key="mower_in_dock",
        name="Mower in dock",
        value_fn_src=(
            "lambda coord: coord.state_machine.snapshot().location == Location.AT_DOCK"
        ),
        source_file="binary_sensor.py",
        line=155,
    )
    exp = Expectation(holder="snapshot", idle=True, reboot="required")
    r = check_idle(ed, exp)
    assert r.status == "green", r.detail


def test_idle_red_when_battery_reads_none_but_expected_persisted():
    ed = EntityDescriptor(
        platform="sensor",
        key="battery_level",
        name="Battery",
        value_fn_src="lambda s: s.battery_level",
        source_file="sensor.py",
        line=126,
    )
    exp = Expectation(holder="snapshot", idle="persisted_value", reboot="required")
    r = check_idle(ed, exp)
    assert r.status == "red"
    assert "None" in r.detail or "null" in r.detail.lower()


def test_idle_red_when_value_does_not_match_literal():
    """An entity whose idle value is expected to be 0 must return 0."""
    ed = EntityDescriptor(
        platform="sensor",
        key="area_mowed_m2",
        name="Area mowed",
        value_fn_src="lambda s: s.area_mowed_m2",
        source_file="sensor.py",
        line=999,
    )
    exp = Expectation(holder="snapshot", idle=0, reboot="required")
    r = check_idle(ed, exp)
    # On fresh MowerState, area_mowed_m2 is None; expected 0 → red
    assert r.status == "red"
