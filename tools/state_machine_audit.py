"""State-machine audit verifier.

Walks every HA entity description, classifies its state holder, and verifies:

  1. Sourcing       — snapshot-owned fields are read from the snapshot.
  2. Idle value     — entity returns the expected value at cold start.
  3. Reboot survival — values that should survive reboot are wired to a
                       persisted source.

Exits non-zero while any red rows exist. Spec:
docs/superpowers/specs/2026-05-13-state-machine-audit-design.md.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="state_machine_audit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip discovery, just print the banner and exit.",
    )
    args = parser.parse_args(argv)
    print("state_machine_audit — verifier skeleton (no checks wired yet)")
    if args.dry_run:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
