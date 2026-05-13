"""State-machine audit verifier — main entry point.

Discovers entities, runs the three checks against each, prints a
per-entity status summary, and exits non-zero if any red rows exist.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.state_machine_audit_checks import (
    Result,
    check_idle,
    check_reboot,
    check_sourcing,
    find_orphan_fields,
    load_expectations,
)
from tools.state_machine_audit_discover import discover_entities

EXPECTATIONS_PATH = Path(__file__).resolve().parent / "state_machine_audit_expectations.yaml"


def _color(status: str) -> str:
    return {"green": "GREEN", "yellow": "YELLO", "red": "RED  "}.get(status, "?????")


def _summarise(results: list[Result]) -> tuple[int, int, int]:
    g = sum(1 for r in results if r.status == "green")
    y = sum(1 for r in results if r.status == "yellow")
    rd = sum(1 for r in results if r.status == "red")
    return g, y, rd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="state_machine_audit")
    parser.add_argument(
        "--quiet", action="store_true", help="Only print the final tally.",
    )
    args = parser.parse_args(argv)

    expectations = load_expectations(EXPECTATIONS_PATH)
    entities = discover_entities()
    results: list[Result] = []

    for ed in entities:
        key = f"{ed.platform}.{ed.key}"
        exp = expectations.get(key)
        # Sourcing always runs (doesn't need expectation).
        results.append(check_sourcing(ed))
        if exp is None:
            results.append(Result(
                entity_key=key, check="idle", status="yellow",
                detail="no expectation declared — add to expectations.yaml",
            ))
            results.append(Result(
                entity_key=key, check="reboot", status="yellow",
                detail="no expectation declared",
            ))
            continue
        results.append(check_idle(ed, exp))
        results.append(check_reboot(ed, exp))

    # Orphan fields (informational; reported separately).
    orphans = find_orphan_fields(entities)

    if not args.quiet:
        print("=" * 72)
        print(" state_machine_audit — per-entity results")
        print("=" * 72)
        for r in sorted(results, key=lambda x: (x.entity_key, x.check)):
            print(f"  [{_color(r.status)}] {r.entity_key:50s} {r.check:8s} {r.detail}")
        print()
        if orphans:
            print(f"Orphan MowerState fields ({len(orphans)}):")
            for f in sorted(orphans):
                print(f"  - {f}")
            print()

    g, y, rd = _summarise(results)
    print(f"Summary: {g} green / {y} yellow / {rd} red")
    if orphans:
        print(f"         + {len(orphans)} orphan MowerState fields")
    return 0 if rd == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
