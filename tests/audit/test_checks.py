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
