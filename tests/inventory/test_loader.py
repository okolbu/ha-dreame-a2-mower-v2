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
