#!/usr/bin/env python3
"""Read-only Dreame-cloud probe for inventory verification.

Per spec §4.7: refuses to write anything; asks before each batch;
emits a delta JSON the reviewer merges into inventory.yaml by hand.

CLI:
    python tools/inventory_probe.py --dry-run     # plan-only, no network
    python tools/inventory_probe.py               # actually probe (asks first)

Credentials: read in situ from ../server-credentials.txt and
../ha-credentials.txt. Never copied to disk.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DELTA_OUT = REPO_ROOT / "tools" / "inventory_probe_delta.json"


@dataclass
class Batch:
    name: str
    description: str
    estimated_calls: int
    risk: str = "read-only"


_BATCHES: tuple[Batch, ...] = (
    Batch(
        name="getCFG",
        description="Re-read all-keys CFG; diff vs latest cloud dump",
        estimated_calls=1,
    ),
    Batch(
        name="cfg_individual sweep",
        description=(
            "Probe each cfg_individual target (DEV, DOCK, MIHIS, NET, LOCN, MAPL, "
            "PIN, PREI, RPET, IOT) plus apk-named candidates not yet tried"
        ),
        estimated_calls=20,
    ),
    Batch(
        name="get_properties for apk-known unseen piids",
        description=(
            "One get_properties call per apk-documented (siid,piid) absent "
            "from the probe corpus. Most return 80001 on g2408."
        ),
        estimated_calls=30,
    ),
    Batch(
        name="candidates list re-test",
        description=(
            "Walk dreame_cloud_dumps/*.json 'candidates' list and re-probe "
            "any target that returned non-error in the previous dump."
        ),
        estimated_calls=15,
    ),
)


def _ask_yes_no(prompt: str) -> bool:
    """Ask a single y/n on stdin. Defaults to 'no' on empty input."""
    print(prompt, end=" ", flush=True)
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        return False
    return line.strip().lower().startswith("y")


def _print_plan() -> None:
    print("Planned probe batches:")
    for i, b in enumerate(_BATCHES, 1):
        print(f"  {i}. {b.name}")
        print(f"     {b.description}")
        print(f"     ~{b.estimated_calls} {b.risk} calls")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="List planned batches; no network calls.")
    parser.add_argument("--delta-out", type=Path, default=DEFAULT_DELTA_OUT,
                        help="Where to write the delta JSON.")
    args = parser.parse_args(argv)

    _print_plan()
    print()
    print(
        "WARNING: probes run against the live mower. "
        "If a mowing run is in progress some configs are locked and reads may "
        "yield misleading conclusions. Continue? (y/N):",
    )
    if not _ask_yes_no(""):
        print("aborted by user")
        return 0

    if args.dry_run:
        print("dry-run: planned batches above; no network calls.")
        return 0

    # Real probe execution wiring is added in Task 17 once we know
    # which batches actually need to run for inventory completeness.
    print(
        "error: live-probe execution not yet implemented; run with --dry-run "
        "or use the dedicated probe scripts in Task 17.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
