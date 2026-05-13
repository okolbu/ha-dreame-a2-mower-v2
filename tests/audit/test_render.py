"""Tests for the markdown renderer."""
from __future__ import annotations

from tools.state_machine_audit_render import render_doc3
from tools.state_machine_audit_discover import EntityDescriptor
from tools.state_machine_audit_checks import Result


def test_render_doc3_emits_table_with_headers():
    entities = [
        EntityDescriptor(
            platform="sensor", key="battery_level", name="Battery",
            value_fn_src="lambda s: s.battery_level",
            source_file="sensor.py", line=126,
        ),
    ]
    results = [
        Result(entity_key="sensor.battery_level", check="sourcing", status="red",
               detail="reads snapshot-owned field from MowerState"),
        Result(entity_key="sensor.battery_level", check="idle", status="red",
               detail="expected persisted value, got None"),
        Result(entity_key="sensor.battery_level", check="reboot", status="red",
               detail="reads MowerState"),
    ]
    md = render_doc3(entities, results)
    assert "| Entity |" in md
    assert "sensor.battery_level" in md
    assert "RED" in md.upper()


def test_render_doc3_sorts_by_field():
    """Entries reading the same field should cluster together."""
    eds = [
        EntityDescriptor(
            platform="sensor", key="z_last", name="Z",
            value_fn_src="lambda s: s.battery_level",
            source_file="sensor.py", line=999,
        ),
        EntityDescriptor(
            platform="sensor", key="a_first", name="A",
            value_fn_src="lambda s: s.battery_level",
            source_file="sensor.py", line=100,
        ),
    ]
    md = render_doc3(eds, [])
    i_a = md.find("a_first")
    i_z = md.find("z_last")
    assert i_a < i_z, "expected entities sorted alphabetically"
