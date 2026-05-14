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
    # After R10 expectation refinement, battery_level idle is `unavailable`
    # (snapshot-backed; fake-coord harness cold-starts without load_persisted).
    assert exp["sensor.battery_level"].idle == "unavailable"
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


from tools.state_machine_audit_checks import check_reboot


def test_reboot_green_when_battery_reads_snapshot():
    ed = EntityDescriptor(
        platform="sensor",
        key="battery_level",
        name="Battery",
        value_fn_src="lambda coord: coord.state_machine.snapshot().battery_percent",
        source_file="sensor.py",
        line=126,
    )
    exp = Expectation(holder="snapshot", idle="persisted_value", reboot="required")
    r = check_reboot(ed, exp)
    assert r.status == "green", r.detail


def test_reboot_red_when_required_field_reads_mower_state():
    """battery_level requires reboot survival; reading MowerState ≠ persisted."""
    ed = EntityDescriptor(
        platform="sensor",
        key="battery_level",
        name="Battery",
        value_fn_src="lambda s: s.battery_level",
        source_file="sensor.py",
        line=126,
    )
    exp = Expectation(holder="snapshot", idle="persisted_value", reboot="required")
    r = check_reboot(ed, exp)
    assert r.status == "red"
    assert "MowerState" in r.detail


def test_reboot_green_when_required_field_reads_mower_state_but_idle_is_literal():
    """area_mowed reads MowerState but expected idle == 0 — RED on idle, not reboot.

    Reboot check passes because the cold-start literal IS what we want;
    `0` is correct without needing persistence.
    """
    ed = EntityDescriptor(
        platform="sensor",
        key="area_mowed_m2",
        name="Area mowed",
        value_fn_src="lambda s: s.area_mowed_m2",
        source_file="sensor.py",
        line=999,
    )
    exp = Expectation(holder="snapshot", idle=0, reboot="required")
    r = check_reboot(ed, exp)
    # idle==0 means the entity doesn't NEED reboot-persistence; a literal
    # is enough. Reboot check is GREEN here; idle check (Task 8) catches
    # the None vs 0 mismatch separately.
    assert r.status == "green"


def test_reboot_green_when_unavailable_ok():
    ed = EntityDescriptor(
        platform="sensor",
        key="live_map_legs_count",
        name="Live legs",
        value_fn_src="lambda coord: len(coord.live_map.legs)",
        source_file="sensor.py",
        line=900,
    )
    exp = Expectation(holder="live_map", idle="unavailable", reboot="unavailable_ok")
    r = check_reboot(ed, exp)
    assert r.status == "green"


from tools.state_machine_audit_checks import find_orphan_fields


def test_find_orphan_fields_returns_unread_names():
    """A MowerState field that no entity reads is an orphan candidate."""
    # Pick a synthetic name that won't be referenced by any value_fn.
    fake_entities = [
        EntityDescriptor(
            platform="sensor", key="battery_level", name="Battery",
            value_fn_src="lambda s: s.battery_level",
            source_file="sensor.py", line=126,
        ),
    ]
    orphans = find_orphan_fields(fake_entities, all_fields={"battery_level", "definitely_unread_xxx"})
    assert "definitely_unread_xxx" in orphans
    assert "battery_level" not in orphans
