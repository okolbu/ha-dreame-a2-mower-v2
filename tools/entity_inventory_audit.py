#!/usr/bin/env python3
"""Entity-inventory coverage gate.

Every concrete HA entity class in the integration must have an entry in
entity-inventory.yaml (matched by `class:`). Exits non-zero (and prints the
gaps) when coverage is incomplete — wired into CI so a new entity can't ship
un-inventoried.

A class counts as a CONCRETE ENTITY when:
  - its name starts with "DreameA2", and
  - it transitively derives from a Home Assistant entity base (a base whose
    simple name ends in "Entity" or "Camera" — note "*EntityDescription" ends
    in "Description", so descriptor dataclasses are excluded automatically), and
  - it is NOT itself used as a base by another class in the integration (i.e.
    it's a leaf — abstract/mixin bases like `_DreameA2PerMapSensorBase` are
    excluded), and
  - it is not an explicit `_EXEMPT` special case.

Inheritance is resolved transitively across the WHOLE package, so entities that
subclass a project-internal base (e.g. `_DreameA2PerMapSensorBase`,
`_PerMapSettingsNumberBase`, `_DreameA2ActionButton`) are detected — the earlier
direct-base heuristic missed ~30 of these.

`class:` values in the inventory that start with "(" are treated as intentional
tombstones (e.g. "(removed 2026-05-15)") and are exempt from the STALE check —
they deliberately record a removed entity so it isn't re-added.
"""
from __future__ import annotations

import ast
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components" / "dreame_a2_mower"
INV = CC / "entity-inventory.yaml"

# Explicit non-entity special cases (rare; the transitive + leaf rules handle
# almost everything). Keep empty unless a real false-positive appears.
_EXEMPT: set[str] = set()


def _is_ha_entity_base(name: str) -> bool:
    """A base simple-name that is a Home Assistant entity base."""
    return name.endswith("Entity") or name.endswith("Camera")


def _base_names(node: ast.ClassDef) -> list[str]:
    out: list[str] = []
    for b in node.bases:
        if isinstance(b, ast.Name):
            out.append(b.id)
        elif isinstance(b, ast.Attribute):
            out.append(b.attr)
    return out


def _class_graph() -> tuple[dict[str, list[str]], dict[str, str]]:
    """Parse every .py in the package. Returns (name->base names, name->loc)."""
    bases: dict[str, list[str]] = {}
    loc: dict[str, str] = {}
    for path in CC.glob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases[node.name] = _base_names(node)
                loc[node.name] = f"{path.relative_to(ROOT)}:{node.lineno}"
    return bases, loc


def _derives_from_entity(name: str, bases: dict[str, list[str]],
                         _seen: set[str] | None = None) -> bool:
    """True if `name` transitively derives from a HA entity base."""
    _seen = _seen or set()
    if name in _seen:
        return False
    _seen.add(name)
    for b in bases.get(name, []):
        if _is_ha_entity_base(b):
            return True
        if b in bases and _derives_from_entity(b, bases, _seen):
            return True
    return False


def _entity_classes() -> dict[str, str]:
    """concrete-entity class name -> 'relpath:line'."""
    bases, loc = _class_graph()
    used_as_base: set[str] = {b for bs in bases.values() for b in bs}
    found: dict[str, str] = {}
    for name in bases:
        if not name.startswith("DreameA2"):
            continue
        if name in _EXEMPT:
            continue
        if name in used_as_base:          # abstract/mixin base — not a leaf
            continue
        if _derives_from_entity(name, bases):
            found[name] = loc[name]
    return found


def _inventoried_classes() -> set[str]:
    data = yaml.safe_load(INV.read_text())
    out: set[str] = set()
    for e in (data.get("entities") or []):
        c = e.get("class")
        if c:
            out.add(c)
    return out


def main() -> int:
    classes = _entity_classes()
    inv = _inventoried_classes()
    missing = sorted(c for c in classes if c not in inv)
    # Tombstones (class starting with "(") are intentional removed-entity records.
    extra = sorted(
        c for c in inv if c not in classes and not c.startswith("(")
    )
    print(f"entity classes in code: {len(classes)}")
    print(f"classes inventoried:    {len(inv)}")
    print(f"missing from inventory:  {len(missing)}")
    for c in missing:
        print(f"  MISSING  {c}  ({classes[c]})")
    for c in extra:
        print(f"  STALE    {c}  (in inventory, not in code)")
    return 1 if (missing or extra) else 0


if __name__ == "__main__":
    sys.exit(main())
