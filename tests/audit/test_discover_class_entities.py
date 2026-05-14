"""Tests for class-attribute entity discovery."""
from __future__ import annotations

from tools.state_machine_audit_discover import discover_entities


def test_discover_finds_snapshot_attribute_entities():
    """Snapshot-attribute entities (DreameA2CurrentActivitySensor etc.) must be discovered."""
    entities = discover_entities()
    keys = {(e.platform, e.key) for e in entities}
    # 4 _SnapshotEnumSensorBase subclasses
    assert ("sensor", "current_activity") in keys
    assert ("sensor", "mower_location") in keys
    assert ("sensor", "positioning_health") in keys
    assert ("sensor", "mqtt_connectivity") in keys


def test_snapshot_entity_value_fn_reads_snapshot_field():
    entities = discover_entities()
    current = next(
        e for e in entities if e.platform == "sensor" and e.key == "current_activity"
    )
    assert "state_machine.snapshot" in current.value_fn_src
    assert "current_activity" in current.value_fn_src


def test_discover_finds_standalone_class_entities():
    """Standalone classes from the registry must be picked up."""
    entities = discover_entities()
    keys = {(e.platform, e.key) for e in entities}
    # Sample of registry entries — all should appear
    assert ("sensor", "ota_status") in keys
    assert ("sensor", "schedule_count") in keys
    assert ("sensor", "cloud_device_id") in keys
    assert ("number", "settings_mowing_height") in keys
    assert ("select", "action_mode") in keys
    assert ("switch", "cloud_state_ai_human_enabled") in keys


def test_discovered_entities_have_value_fn_src():
    """Every newly-discovered entity must have a non-empty value_fn_src for the audit checks."""
    entities = discover_entities()
    # Check a sample of the new entities
    for key in [
        "current_activity", "mower_location", "ota_status",
        "schedule_count", "cloud_device_id",
    ]:
        e = next(
            (e for e in entities if e.platform == "sensor" and e.key == key),
            None,
        )
        assert e is not None, f"missing {key}"
        assert e.value_fn_src, f"missing value_fn_src for {key}"
