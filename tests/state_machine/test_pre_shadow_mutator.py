"""Tests for MowerStateMachine.handle_pre_shadow_update.

s6.2 is the user-edit profile push that the Dreame app emits whenever
the user saves the settings page on a map. It carries the FULL active-
map profile (height + efficiency + edgemaster). We learn per-map
values over time by tagging each push with the active map_id.

See docs/research/g2408-protocol.md § s6.2 for the wire-shape
derivation and the live test sequence confirming this model.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.mower.state_machine import (
    MowerStateMachine,
)
from custom_components.dreame_a2_mower.mower.state_snapshot import (
    StateSnapshot,
)


def test_pre_shadow_writes_all_three_fields_for_active_map():
    sm = MowerStateMachine()
    snap = sm.handle_pre_shadow_update(
        map_id=2,
        mowing_height_mm=60,
        mowing_efficiency=1,
        edgemaster=True,
        now_unix=1000,
    )
    assert snap.pre_shadow_by_map_id == {
        2: {
            "mowing_height_mm": 60,
            "mowing_efficiency": 1,
            "edgemaster": True,
        }
    }
    # Freshness stamp keyed by map_id.
    assert snap.field_freshness.get("pre_shadow[2]") == 1000


def test_pre_shadow_partial_update_preserves_other_fields():
    sm = MowerStateMachine()
    sm.handle_pre_shadow_update(
        map_id=2,
        mowing_height_mm=60,
        mowing_efficiency=1,
        edgemaster=True,
        now_unix=1000,
    )
    # Subsequent push only changes efficiency.
    snap = sm.handle_pre_shadow_update(
        map_id=2,
        mowing_efficiency=0,
        now_unix=2000,
    )
    assert snap.pre_shadow_by_map_id[2]["mowing_height_mm"] == 60
    assert snap.pre_shadow_by_map_id[2]["mowing_efficiency"] == 0
    assert snap.pre_shadow_by_map_id[2]["edgemaster"] is True
    assert snap.field_freshness.get("pre_shadow[2]") == 2000


def test_pre_shadow_no_op_when_values_unchanged():
    sm = MowerStateMachine()
    sm.handle_pre_shadow_update(
        map_id=0,
        mowing_height_mm=30,
        mowing_efficiency=0,
        edgemaster=False,
        now_unix=1000,
    )
    sm._clear_dirty()
    snap = sm.handle_pre_shadow_update(
        map_id=0,
        mowing_height_mm=30,
        mowing_efficiency=0,
        edgemaster=False,
        now_unix=2000,
    )
    assert not sm.is_dirty()
    # Freshness for unchanged values must NOT bump.
    assert snap.field_freshness.get("pre_shadow[0]") == 1000


def test_pre_shadow_no_op_when_all_none():
    sm = MowerStateMachine()
    sm.handle_pre_shadow_update(
        map_id=1,
        mowing_height_mm=40,
        now_unix=1000,
    )
    sm._clear_dirty()
    snap = sm.handle_pre_shadow_update(
        map_id=1,
        mowing_height_mm=None,
        mowing_efficiency=None,
        edgemaster=None,
        now_unix=2000,
    )
    assert not sm.is_dirty()
    # Pre-existing height untouched.
    assert snap.pre_shadow_by_map_id[1] == {"mowing_height_mm": 40}


def test_pre_shadow_multi_map_independent_entries():
    """Each map_id maps to its own shadow entry."""
    sm = MowerStateMachine()
    sm.handle_pre_shadow_update(
        map_id=0,
        mowing_height_mm=30,
        mowing_efficiency=0,
        edgemaster=False,
        now_unix=1000,
    )
    snap = sm.handle_pre_shadow_update(
        map_id=2,
        mowing_height_mm=60,
        mowing_efficiency=1,
        edgemaster=True,
        now_unix=2000,
    )
    assert snap.pre_shadow_by_map_id[0] == {
        "mowing_height_mm": 30,
        "mowing_efficiency": 0,
        "edgemaster": False,
    }
    assert snap.pre_shadow_by_map_id[2] == {
        "mowing_height_mm": 60,
        "mowing_efficiency": 1,
        "edgemaster": True,
    }
    assert snap.field_freshness.get("pre_shadow[0]") == 1000
    assert snap.field_freshness.get("pre_shadow[2]") == 2000


def test_pre_shadow_partial_first_push_only_writes_supplied():
    """First push for a map only writes the fields it carries."""
    sm = MowerStateMachine()
    snap = sm.handle_pre_shadow_update(
        map_id=0,
        mowing_efficiency=1,
        now_unix=1000,
    )
    assert snap.pre_shadow_by_map_id == {
        0: {"mowing_efficiency": 1},
    }


def test_pre_shadow_serialization_round_trip():
    """Snapshot with pre_shadow_by_map_id serialises and restores cleanly.

    JSON dict keys must be strings; from_dict re-coerces them to int.
    """
    sm = MowerStateMachine()
    sm.handle_pre_shadow_update(
        map_id=0,
        mowing_height_mm=30,
        mowing_efficiency=0,
        edgemaster=False,
        now_unix=1000,
    )
    sm.handle_pre_shadow_update(
        map_id=2,
        mowing_height_mm=60,
        mowing_efficiency=1,
        edgemaster=True,
        now_unix=2000,
    )
    raw = sm.snapshot().to_dict()
    # JSON-serialised keys are strings.
    assert "pre_shadow_by_map_id" in raw
    assert set(raw["pre_shadow_by_map_id"].keys()) == {"0", "2"}
    restored = StateSnapshot.from_dict(raw)
    # Restored keys are int.
    assert set(restored.pre_shadow_by_map_id.keys()) == {0, 2}
    assert restored.pre_shadow_by_map_id[0]["mowing_height_mm"] == 30
    assert restored.pre_shadow_by_map_id[2]["edgemaster"] is True


def test_pre_shadow_from_dict_tolerates_missing_field():
    """Legacy snapshots without pre_shadow_by_map_id must restore cleanly."""
    raw = StateSnapshot.initial().to_dict()
    raw.pop("pre_shadow_by_map_id", None)
    restored = StateSnapshot.from_dict(raw)
    assert restored.pre_shadow_by_map_id == {}


def test_pre_shadow_from_dict_drops_unparseable_keys():
    """Corrupt map_id keys are skipped, valid ones preserved."""
    raw = StateSnapshot.initial().to_dict()
    raw["pre_shadow_by_map_id"] = {
        "0": {"mowing_height_mm": 30},
        "not-an-int": {"mowing_height_mm": 99},
    }
    restored = StateSnapshot.from_dict(raw)
    assert restored.pre_shadow_by_map_id == {0: {"mowing_height_mm": 30}}
