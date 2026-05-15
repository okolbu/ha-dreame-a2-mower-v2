#!/usr/bin/env python3
"""Audit outstanding retractions across the inventory files.

A retraction is "outstanding" when an entry's most recent verification
has `status: retracted` — i.e. the prior claim has been withdrawn AND
no follow-up `verified`/`partial`/`presumed` has been written since.
Once a retraction is resolved (the claim re-stated correctly or the
implementation fixed and re-verified), the entry will gain a newer
verification record and stop appearing in this report.

Walks both inventory.yaml and entity-inventory.yaml. Emits a
human-readable summary on stdout and one GitHub Actions
`::notice::` line per outstanding retraction so they surface in
PR/CI logs.

Exit code is always 0 — this is informational, not a gate. Wire as
a notice-only CI step so retractions remain visible across every
build without blocking work.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WIRE_INVENTORY = REPO_ROOT / "custom_components" / "dreame_a2_mower" / "inventory.yaml"
ENTITY_INVENTORY = REPO_ROOT / "custom_components" / "dreame_a2_mower" / "entity-inventory.yaml"


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict node in a YAML-loaded structure."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _outstanding(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return the latest verification if its status is `retracted`, else None.

    "Latest" is by `date` (string-sortable ISO 8601). Entries with no
    verifications list are skipped.
    """
    verifications = entry.get("verifications")
    if not isinstance(verifications, list) or not verifications:
        return None
    by_date = sorted(verifications, key=lambda v: str(v.get("date", "")))
    latest = by_date[-1]
    if not isinstance(latest, dict):
        return None
    if latest.get("status") != "retracted":
        return None
    return latest


def _entry_id(entry: dict[str, Any]) -> str | None:
    """Best-effort identifier for the entry that owns a verifications list.

    inventory.yaml uses `id`, entity-inventory.yaml uses `id`, some
    inventory.yaml subsections use `name` or `cfg_key`. Return the
    first available; None if the entry has no clear identifier (in
    which case we skip it rather than print an opaque line).
    """
    for key in ("id", "name", "cfg_key", "setting_name"):
        v = entry.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def audit(path: Path) -> list[tuple[str, dict[str, Any]]]:
    """Return list of (id, latest_retraction_verification) tuples."""
    if not path.exists():
        return []
    with path.open() as f:
        data = yaml.safe_load(f)
    out: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for node in _walk(data):
        # Only consider nodes that have BOTH an identifier and a
        # verifications list. This avoids double-counting the
        # verification dicts themselves (which also pass through
        # _walk and have a `status` field).
        if "verifications" not in node:
            continue
        entry_id = _entry_id(node)
        if entry_id is None or entry_id in seen:
            continue
        seen.add(entry_id)
        ret = _outstanding(node)
        if ret is not None:
            out.append((entry_id, ret))
    return out


def main() -> int:
    wire = audit(WIRE_INVENTORY)
    entity = audit(ENTITY_INVENTORY)
    total = len(wire) + len(entity)

    if total == 0:
        print("No outstanding retractions. All claims have been re-verified.")
        return 0

    print(f"Outstanding retractions: {total} ({len(wire)} wire, {len(entity)} entity)")
    print()

    for src, label, items in (
        (WIRE_INVENTORY, "inventory.yaml", wire),
        (ENTITY_INVENTORY, "entity-inventory.yaml", entity),
    ):
        if not items:
            continue
        print(f"## {label}")
        for entry_id, ret in items:
            date = ret.get("date", "?")
            reason = (ret.get("reason") or ret.get("retracts") or "(no reason)").strip()
            # One-line reason for the GH Actions notice; the full text
            # stays in the inventory file for follow-up readers.
            reason_one_line = reason.replace("\n", " ").strip()
            if len(reason_one_line) > 140:
                reason_one_line = reason_one_line[:137] + "..."
            print(f"  - [{date}] {entry_id} — {reason_one_line}")
            # GitHub Actions surface (no-op outside CI):
            print(
                f"::notice file={src.relative_to(REPO_ROOT)},title=Outstanding retraction::"
                f"{entry_id} ({date}) — {reason_one_line}"
            )
        print()

    # Always exit 0 — notice-only, not a gate.
    return 0


if __name__ == "__main__":
    sys.exit(main())
