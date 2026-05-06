"""Tests for the runtime-check helpers (catalog miss detection)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.protocol.unknown_watchdog import (
    UnknownFieldWatchdog,
)


def test_saw_catalog_miss_returns_true_on_first_unseen_value() -> None:
    """First time a value not in the catalog appears, return True."""
    w = UnknownFieldWatchdog()
    catalog = {0: "off", 1: "on"}
    # 2 is not in the catalog
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is True


def test_saw_catalog_miss_returns_false_for_in_catalog_values() -> None:
    """Values that ARE in the catalog never trigger a miss."""
    w = UnknownFieldWatchdog()
    catalog = {0: "off", 1: "on"}
    assert w.saw_catalog_miss(siid=4, piid=27, value=0, catalog=catalog) is False
    assert w.saw_catalog_miss(siid=4, piid=27, value=1, catalog=catalog) is False


def test_saw_catalog_miss_dedupes_repeated_misses() -> None:
    """The same out-of-catalog value reported twice → True once, then False."""
    w = UnknownFieldWatchdog()
    catalog = {0: "off", 1: "on"}
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is True
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is False


def test_saw_catalog_miss_reports_distinct_misses_separately() -> None:
    """Different out-of-catalog values each get a one-shot True."""
    w = UnknownFieldWatchdog()
    catalog = {0: "off", 1: "on"}
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is True
    assert w.saw_catalog_miss(siid=4, piid=27, value=3, catalog=catalog) is True
    # And the original miss is still deduped:
    assert w.saw_catalog_miss(siid=4, piid=27, value=2, catalog=catalog) is False
