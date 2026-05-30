#!/usr/bin/env python3
"""Entity-inventory coverage gate.

Every concrete HA entity class in the platform files must have an entry in
entity-inventory.yaml (matched by `class:`). Base/mixin classes are exempt via
_EXEMPT. Exits non-zero (and prints the missing classes) when coverage is
incomplete — wired into CI so a new entity can't ship un-inventoried.
"""
from __future__ import annotations
import ast
import pathlib
import sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components" / "dreame_a2_mower"
INV = CC / "entity-inventory.yaml"

PLATFORM_GLOBS = [
    "switch*.py", "sensor*.py", "select*.py", "number*.py",
    "binary_sensor*.py", "button*.py", "device_tracker*.py", "event*.py",
    "lawn_mower*.py", "calendar*.py", "camera*.py", "_camera_*.py",
    "_sensor_*.py",
]

_EXEMPT: set[str] = {
    # EntityDescription dataclasses — these are typed config descriptors passed
    # to entity constructors; they are never directly instantiated as HA entities
    # and never appear in async_add_entities() calls.
    "DreameA2BinarySensorEntityDescription",   # binary_sensor.py — descriptor for DreameA2BinarySensor
    "DreameA2SensorEntityDescription",          # _sensor_base.py — descriptor for DreameA2Sensor
    "DreameA2DiagnosticSensorEntityDescription",  # _sensor_base.py — descriptor for DreameA2DiagnosticSensor
    "DreameA2NumberEntityDescription",          # number.py — descriptor for DreameA2Number
}

_ENTITY_BASE_HINTS = (
    "Entity", "SwitchEntity", "SensorEntity", "SelectEntity", "NumberEntity",
    "BinarySensorEntity", "ButtonEntity", "Camera", "TrackerEntity",
    "EventEntity", "LawnMowerEntity", "CalendarEntity",
)


def _entity_classes() -> dict[str, str]:
    found: dict[str, str] = {}
    seen: set[pathlib.Path] = set()
    for glob in PLATFORM_GLOBS:
        for path in CC.glob(glob):
            if path in seen:
                continue
            seen.add(path)
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not node.name.startswith("DreameA2"):
                    continue
                base_names = " ".join(
                    b.id if isinstance(b, ast.Name)
                    else (b.attr if isinstance(b, ast.Attribute) else "")
                    for b in node.bases
                )
                if not any(h in base_names for h in _ENTITY_BASE_HINTS):
                    continue
                if node.name in _EXEMPT:
                    continue
                found[node.name] = f"{path.relative_to(ROOT)}:{node.lineno}"
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
    extra = sorted(c for c in inv if c not in classes)
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
