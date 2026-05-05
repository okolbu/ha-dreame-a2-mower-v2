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
        "uint16_le",
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

_BANNER = (
    "<!-- DO NOT EDIT BY HAND. Source: docs/research/inventory/inventory.yaml. "
    "Regenerate via `python tools/inventory_gen.py`. -->\n\n"
)

# Order in which sections render. Names mirror inventory.yaml top-level keys.
_RENDER_ORDER: tuple[tuple[str, str], ...] = (
    ("properties", "Properties"),
    ("events", "Events"),
    ("actions", "Actions"),
    ("opcodes", "Routed-action opcodes"),
    ("cfg_keys", "CFG keys"),
    ("cfg_individual", "cfg_individual endpoints"),
    ("heartbeat_bytes", "Heartbeat (s1p1) bytes"),
    ("telemetry_fields", "Telemetry (s1p4) fields"),
    ("telemetry_variants", "Telemetry frame variants"),
    ("s2p51_shapes", "s2p51 multiplexed-config shapes"),
    ("state_codes", "s2p2 state codes"),
    ("mode_enum", "s2p1 mode enum"),
    ("oss_map_keys", "OSS map blob keys"),
    ("session_summary_fields", "Session-summary JSON fields"),
    ("m_path_encoding", "M_PATH encoding"),
    ("lidar_pcd", "LiDAR PCD format"),
)

# Display unit prettifier — maps wire/display strings to user-facing forms.
_DISPLAY_PRETTIFY: dict[str, str] = {
    "m2": "m²",
}


def _prettify_display(value: str) -> str:
    return _DISPLAY_PRETTIFY.get(value, value)


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


def _derive_status_label(row: dict[str, Any]) -> str:
    """Map status booleans to a single human label."""
    refs = row.get("references") or {}
    status = row.get("status") or {}
    if refs.get("integration_code"):
        return "WIRED"
    seen = status.get("seen_on_wire", False)
    decoded = status.get("decoded")
    if status.get("not_on_g2408"):
        return "NOT-ON-G2408"
    if status.get("bt_only"):
        return "BT-ONLY"
    if seen and decoded == "confirmed":
        return "DECODED-UNWIRED"
    if seen:
        return "SEEN-UNDECODED"
    if refs.get("apk"):
        return "APK-KNOWN"
    if refs.get("alt_repos"):
        return "UPSTREAM-KNOWN"
    return "UNCLASSIFIED"


def _render_unit(unit: dict[str, Any] | None) -> str:
    if not unit:
        return ""
    display = _prettify_display(unit.get("display", ""))
    scale = unit.get("scale")
    if scale is None:
        return display
    return f"{display} (×{scale})"


def _render_chapter(section: str, title: str, rows: list[dict[str, Any]]) -> str:
    out: list[str] = [f"## {title}\n"]
    if not rows:
        out.append("\n_(none)_\n")
        return "".join(out)
    out.append("\n| id | name | shape | status | unit |\n")
    out.append("|----|------|-------|--------|------|\n")
    for row in rows:
        rid = row.get("id", "?")
        name = row.get("name", "")
        shape = row.get("payload_shape", "")
        label = _derive_status_label(row)
        unit = _render_unit(row.get("unit"))
        out.append(f"| {rid} | {name} | {shape} | {label} | {unit} |\n")
    out.append("\n")
    for row in rows:
        rid = row.get("id", "?")
        name = row.get("name", "")
        out.append(f"### {rid} — `{name}`\n\n")
        semantic = (row.get("semantic") or "").rstrip()
        if semantic:
            out.append(semantic + "\n\n")
        oqs = row.get("open_questions") or []
        if oqs:
            out.append("**Open questions:**\n")
            for oq in oqs:
                out.append(f"- {oq}\n")
            out.append("\n")
        refs = row.get("references") or {}
        ref_pieces: list[str] = []
        if refs.get("integration_code"):
            ref_pieces.append(refs["integration_code"])
        if refs.get("protocol_doc"):
            ref_pieces.append(refs["protocol_doc"])
        if refs.get("apk"):
            ref_pieces.append(f"apk: {refs['apk']}")
        for alt in refs.get("alt_repos") or []:
            ref_pieces.append(alt)
        if ref_pieces:
            out.append("**See also:** " + ", ".join(f"`{p}`" for p in ref_pieces) + "\n\n")
    return "".join(out)


def render_canonical(inventory: dict[str, Any]) -> str:
    body: list[str] = [_BANNER, "# g2408 Protocol — Canonical Reference\n\n"]
    for section, title in _RENDER_ORDER:
        rows = inventory.get(section) or []
        body.append(_render_chapter(section, title, rows))
    return "".join(body)


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
    parser.add_argument(
        "--output-dir", type=Path,
        default=REPO_ROOT / "docs" / "research" / "inventory" / "generated",
        help="Where to write generated files (default: %(default)s)",
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

    # Generate canonical doc.
    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = out_dir / "g2408-canonical.md"
    canonical_path.write_text(render_canonical(inventory))
    coverage_path = out_dir / "coverage-report.md"
    if not coverage_path.exists():
        coverage_path.write_text(
            _BANNER + "# Coverage Report\n\n_Run `python tools/inventory_audit.py` to populate._\n"
        )
    print(f"ok: rendered {canonical_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
