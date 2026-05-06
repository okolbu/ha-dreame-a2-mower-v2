"""YAML-source-of-truth loader for the g2408 inventory.

Loads `custom_components/dreame_a2_mower/inventory.yaml` once per process
and returns a frozen `Inventory` dataclass with four indexed lookups for
fast runtime use:

- `suppressed_slots`: rows with `runtime.suppress: true`
- `value_catalogs`: `(siid, piid) → {value: label}` for rows with a
  `value_catalog` block
- `apk_known_never_seen`: rows with `references.apk` set AND
  `seen_on_wire: false`
- `all_known`: every (siid, piid) the inventory recognises (seen + apk-known)

@functools.cache ensures HA's per-config-entry setup pays the YAML parsing
cost only on the first call.
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__package__)

INVENTORY_PATH: Path = (
    Path(__file__).resolve().parents[1] / "inventory.yaml"
)


@dataclass(frozen=True, slots=True)
class Inventory:
    """Indexed snapshot of inventory.yaml for runtime lookup."""

    suppressed_slots: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    value_catalogs: dict[tuple[int, int], dict[Any, str]] = field(default_factory=dict)
    apk_known_never_seen: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    all_known: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    raw_yaml: dict[str, Any] = field(default_factory=dict)


def _slot_key(row: dict[str, Any]) -> tuple[int, int] | None:
    """Extract (siid, piid) from a properties-section row, or None."""
    siid = row.get("siid")
    piid = row.get("piid")
    if isinstance(siid, int) and isinstance(piid, int):
        return (siid, piid)
    return None


def _build_inventory(raw: dict[str, Any]) -> Inventory:
    suppressed: set[tuple[int, int]] = set()
    catalogs: dict[tuple[int, int], dict[Any, str]] = {}
    apk_unseen: set[tuple[int, int]] = set()
    all_known: set[tuple[int, int]] = set()

    for row in raw.get("properties") or []:
        if not isinstance(row, dict):
            continue
        key = _slot_key(row)
        if key is None:
            continue

        all_known.add(key)

        runtime = row.get("runtime") or {}
        if isinstance(runtime, dict) and runtime.get("suppress") is True:
            suppressed.add(key)

        catalog = row.get("value_catalog")
        if isinstance(catalog, dict) and catalog:
            # Coerce value_catalog keys to int where they look like ints
            # (YAML may load them as int already, but be defensive).
            normalised: dict[Any, str] = {}
            for k, v in catalog.items():
                normalised[k] = str(v)
            catalogs[key] = normalised

        status = row.get("status") or {}
        refs = row.get("references") or {}
        if (
            isinstance(status, dict)
            and isinstance(refs, dict)
            and status.get("seen_on_wire") is False
            and refs.get("apk")
        ):
            apk_unseen.add(key)

    return Inventory(
        suppressed_slots=frozenset(suppressed),
        value_catalogs=catalogs,
        apk_known_never_seen=frozenset(apk_unseen),
        all_known=frozenset(all_known),
        raw_yaml=raw,
    )


@functools.cache
def load_inventory(path: Path | None = None) -> Inventory:
    """Load inventory.yaml once and return the indexed snapshot.

    Cached via @functools.cache. Subsequent calls return the same instance.
    Pass `path` only in tests to override the default.
    """
    target = path if path is not None else INVENTORY_PATH
    raw = yaml.safe_load(target.read_text()) or {}
    inv = _build_inventory(raw)
    LOGGER.info(
        "inventory loaded: %d properties, %d cfg_individual, %d suppressed slots",
        len(raw.get("properties") or []),
        len(raw.get("cfg_individual") or []),
        len(inv.suppressed_slots),
    )
    return inv
