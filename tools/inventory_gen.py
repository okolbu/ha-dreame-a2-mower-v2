#!/usr/bin/env python3
"""Inventory generator + validator.

Validates docs/research/inventory/inventory.yaml against the schema
described in docs/research/inventory/README.md, and (in a later step)
renders generated/g2408-canonical.md.

CLI:
    python tools/inventory_gen.py                   # full generate
    python tools/inventory_gen.py --validate-only   # schema check only
    python tools/inventory_gen.py PATH              # validate a different file
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "docs" / "research" / "inventory" / "inventory.yaml"

_UNIT_VOCAB: frozenset[str] = frozenset(
    {
        "cm", "mm", "m", "decimetres", "centiares", "m2", "m2_x100",
        "signed_dbm", "unsigned_byte", "signed_byte",
        "minutes_from_midnight", "unix_seconds",
        "percent", "percent_x100",
        "degrees", "degrees_x256",
        "bool", "enum", "raw_bytes", "string",
    }
)

_DECODED_VALUES: frozenset[str] = frozenset({"confirmed", "hypothesized", "unknown"})

_REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "_sources", "properties", "events", "actions", "opcodes",
    "cfg_keys", "cfg_individual",
    "heartbeat_bytes", "telemetry_fields", "telemetry_variants",
    "s2p51_shapes", "state_codes", "mode_enum",
    "oss_map_keys", "session_summary_fields",
    "m_path_encoding", "lidar_pcd",
)


class ValidationError(Exception):
    pass


def _validate_row(section: str, idx: int, row: dict[str, Any]) -> Iterable[str]:
    """Yield error strings for a single row."""
    if "id" not in row:
        yield f"{section}[{idx}]: missing 'id'"
        return
    rid = row["id"]
    unit = row.get("unit")
    if unit is not None:
        if not isinstance(unit, dict):
            yield (
                f"{section}[{rid}].unit: expected dict, "
                f"got {type(unit).__name__}"
            )
        else:
            wire = unit.get("wire")
            if wire is None:
                yield f"{section}[{rid}].unit: missing 'wire'"
            elif wire not in _UNIT_VOCAB:
                yield (
                    f"{section}[{rid}].unit.wire: '{wire}' not in vocabulary "
                    f"(extend tools/inventory_gen.py:_UNIT_VOCAB if intentional)"
                )
    status = row.get("status")
    if status is not None:
        if not isinstance(status, dict):
            yield (
                f"{section}[{rid}].status: expected dict, "
                f"got {type(status).__name__}"
            )
        else:
            decoded = status.get("decoded")
            if decoded is not None and decoded not in _DECODED_VALUES:
                yield (
                    f"{section}[{rid}].status.decoded: '{decoded}' invalid "
                    f"(must be one of {sorted(_DECODED_VALUES)})"
                )


def validate(inventory: dict[str, Any]) -> list[str]:
    """Return a list of error strings; empty list = valid."""
    errors: list[str] = []
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in inventory:
            errors.append(f"top-level: missing required key '{key}'")
    for section in _REQUIRED_TOP_LEVEL_KEYS:
        if section == "_sources":
            continue
        rows = inventory.get(section)
        if rows is None:
            continue
        if not isinstance(rows, list):
            errors.append(f"{section}: expected list, got {type(rows).__name__}")
            continue
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{section}[{idx}]: expected dict, got {type(row).__name__}")
                continue
            errors.extend(_validate_row(section, idx, row))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inventory_path", nargs="?", type=Path, default=DEFAULT_INVENTORY,
        help="Path to inventory.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Run schema validation and exit; do not render docs.",
    )
    args = parser.parse_args(argv)

    try:
        inventory = yaml.safe_load(args.inventory_path.read_text())
    except FileNotFoundError:
        print(f"error: {args.inventory_path} not found", file=sys.stderr)
        return 2

    errors = validate(inventory)
    if errors:
        print("validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if args.validate_only:
        print("ok: inventory schema valid")
        return 0

    # Generation is added in Task 3.
    print("ok: schema valid (generator not yet implemented)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
