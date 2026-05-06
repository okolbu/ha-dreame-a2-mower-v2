"""Inventory package — runtime loader for the YAML source-of-truth.

See docs/research/inventory/README.md for the schema; the YAML lives at
`custom_components/dreame_a2_mower/inventory.yaml` so HACS-installed
users get it alongside the integration code.
"""
from __future__ import annotations

from custom_components.dreame_a2_mower.inventory.loader import (
    Inventory,
    load_inventory,
)

__all__ = ["Inventory", "load_inventory"]
