"""Tests for entity discovery."""
from __future__ import annotations

from tools.state_machine_audit_discover import discover_entities


def test_discover_returns_known_entity_count_floor():
    """Discovery should find at least the entity tuples we know exist.

    Counts are floors — they can grow as new entities are added. Verified
    via AST walk on 2026-05-14 (instances only, class definitions excluded;
    entities without a value-reader closure such as the action_mode select
    are filtered out by discover_entities):
      binary_sensor.py: 17
      sensor.py:        50
      switch.py:        25
      number.py:         4
      time.py:           6  (read via `minutes_fn`)
    Total floor: 102.
    """
    entities = discover_entities()
    assert len(entities) >= 102, f"found {len(entities)} entities; expected >= 102"


def test_discover_each_entity_has_required_attrs():
    """Every discovered entity must have key, name, platform, value_fn_src."""
    entities = discover_entities()
    for ent in entities:
        assert ent.key, f"missing key on {ent}"
        assert ent.platform in {
            "binary_sensor", "sensor", "switch", "select",
            "number", "time",
        }, f"unexpected platform on {ent}: {ent.platform}"
        # name can be None for some entity_category=diagnostic, but
        # value_fn_src must always be present.
        assert ent.value_fn_src, f"missing value_fn_src on {ent.key}"


def test_discover_finds_battery_level():
    """The Battery sensor must appear in the discovered set."""
    entities = discover_entities()
    keys = [e.key for e in entities]
    assert "battery_level" in keys


def test_discover_finds_mower_in_dock():
    """The Mower-in-dock binary sensor must appear."""
    entities = discover_entities()
    keys = [e.key for e in entities]
    assert "mower_in_dock" in keys
