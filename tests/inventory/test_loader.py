"""Tests for the inventory loader."""
from __future__ import annotations

from custom_components.dreame_a2_mower.inventory.loader import (
    Inventory,
    load_inventory,
)


def test_load_inventory_returns_frozen_dataclass() -> None:
    inv = load_inventory()
    assert isinstance(inv, Inventory)


def test_load_inventory_has_indexed_lookups() -> None:
    inv = load_inventory()
    # All four lookups defined in spec §4.3
    assert isinstance(inv.suppressed_slots, frozenset)
    assert isinstance(inv.value_catalogs, dict)
    assert isinstance(inv.apk_known_never_seen, frozenset)
    assert isinstance(inv.all_known, frozenset)


def test_load_inventory_caches() -> None:
    """@functools.cache must return the same instance across calls."""
    a = load_inventory()
    b = load_inventory()
    assert a is b


def test_all_known_includes_seen_and_apk_known() -> None:
    """Every property row's (siid, piid) is in all_known."""
    inv = load_inventory()
    # Spot-check: s2p1 (seen, decoded) and s1p2 (apk-known-never-seen) are both there.
    assert (2, 1) in inv.all_known
    assert (1, 2) in inv.all_known


def test_apk_known_never_seen_excludes_observed() -> None:
    """A row with seen_on_wire:true must NOT be in apk_known_never_seen."""
    inv = load_inventory()
    # s2p1 was observed extensively in the corpus.
    assert (2, 1) not in inv.apk_known_never_seen


def test_value_catalogs_keyed_by_siid_piid() -> None:
    """Rows with value_catalog blocks surface in the dict keyed by tuple."""
    inv = load_inventory()
    # s2p1 has a value_catalog (mode enum).
    catalog = inv.value_catalogs.get((2, 1))
    assert catalog is not None
    assert 1 in catalog  # 1: Mowing
    assert 2 in catalog  # 2: Idle/Standby


def test_suppressed_slots_match_legacy_set() -> None:
    """The 5 rows with runtime.suppress:true reproduce the legacy literal.

    Migration safety check: coordinator.py:79 had
    _SUPPRESSED_SLOTS = frozenset({(2,50),(1,50),(1,51),(1,52),(6,117)}).
    Axis 3 derives this from the inventory; the derived set must equal
    the legacy set on day one.
    """
    inv = load_inventory.__wrapped__()  # bypass cache for test isolation
    legacy = frozenset({(2, 50), (1, 50), (1, 51), (1, 52), (6, 117)})
    assert inv.suppressed_slots == legacy, (
        f"derived suppressed_slots {sorted(inv.suppressed_slots)} != "
        f"legacy {sorted(legacy)}"
    )


def test_state_codes_section_merged_into_s2p2_catalog() -> None:
    """state_codes: section entries become value_catalogs[(2, 2)] entries.

    The s2p2 property row carries no inline value_catalog (axis 1 deferred
    the catalog to the state_codes: section). After the loader's section-
    merge step, value_catalogs[(2, 2)] should contain every s2p2 code from
    the section.
    """
    inv = load_inventory.__wrapped__()
    catalog = inv.value_catalogs.get((2, 2))
    assert catalog is not None, "state_codes: section did not produce a (2,2) catalog"
    # Spot-check three well-known codes (axis 1 confirmed):
    assert 48 in catalog, f"48 (MOWING_COMPLETE) missing from {sorted(catalog.keys())}"
    assert 50 in catalog, f"50 (manual session start) missing"
    assert 70 in catalog, f"70 (mowing) missing"
    # Names should be the section's name field, e.g. "MOWING_COMPLETE"
    assert catalog[48] == "MOWING_COMPLETE"


def test_mode_enum_section_merged_into_s2p1_catalog() -> None:
    """mode_enum: section entries augment value_catalogs[(2, 1)].

    The s2p1 property row has an inline value_catalog with 9 entries; the
    mode_enum: section also has 9 rows for the same property. The merge
    should produce a catalog with at least 9 entries, including value 3
    (PAUSED) which is the lone DECODED-UNWIRED axis-4 candidate.
    """
    inv = load_inventory.__wrapped__()
    catalog = inv.value_catalogs.get((2, 1))
    assert catalog is not None
    assert 3 in catalog, f"3 (PAUSED) missing from {sorted(catalog.keys())}"
    # Other expected values from the inline catalog plus the section.
    for v in (1, 2, 5, 6, 11, 13, 14, 16):
        assert v in catalog, f"value {v} missing"


def test_inline_value_catalog_takes_precedence_over_section() -> None:
    """If both inline and section carry an entry for the same (siid, piid, value),
    the inline catalog wins. Defends against future contradictions.
    """
    # Build a fresh inventory from a tiny fixture in-memory rather than the
    # full live YAML, since the live file may not have a deliberate conflict.
    from custom_components.dreame_a2_mower.inventory.loader import _build_inventory
    raw = {
        "_sources": {},
        "properties": [
            {
                "id": "s2p1",
                "siid": 2,
                "piid": 1,
                "name": "status",
                "category": "property",
                "value_catalog": {1: "INLINE_WINS"},  # inline says "INLINE_WINS"
                "status": {"seen_on_wire": True, "decoded": "confirmed",
                           "bt_only": False, "not_on_g2408": False},
                "references": {},
            },
        ],
        "events": [], "actions": [], "opcodes": [], "cfg_keys": [],
        "cfg_individual": [], "heartbeat_bytes": [], "telemetry_fields": [],
        "telemetry_variants": [], "s2p51_shapes": [], "state_codes": [],
        "oss_map_keys": [], "session_summary_fields": [], "m_path_encoding": [],
        "lidar_pcd": [],
        "mode_enum": [
            {"id": "s2p1_1", "value": 1, "name": "SECTION_LOSES",
             "category": "mode_enum",
             "status": {"seen_on_wire": True, "decoded": "confirmed",
                        "bt_only": False, "not_on_g2408": False},
             "references": {}},
        ],
    }
    inv = _build_inventory(raw)
    assert inv.value_catalogs[(2, 1)][1] == "INLINE_WINS"
