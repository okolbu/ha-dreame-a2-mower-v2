"""Tests for inventory_audit.py's probe-log walker."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).parents[2] / "tools" / "inventory_audit.py"


def test_probe_walker_finds_unknown_slot() -> None:
    """If the inventory has no s2p99 row but the probe log carries one,
    the audit must report it."""
    result = subprocess.run(
        [
            sys.executable, str(TOOL),
            "--inventory", str(FIXTURES / "good_inventory.yaml"),
            "--probe-glob", str(FIXTURES / "mini_probe.jsonl"),
            "--cloud-dump-glob", "/dev/null",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "s2p99" in result.stdout
    assert "not in inventory" in result.stdout.lower()


def test_probe_walker_passes_when_all_slots_known() -> None:
    """If the inventory covers every slot in the corpus, exit 0."""
    result = subprocess.run(
        [
            sys.executable, str(TOOL),
            "--inventory", str(FIXTURES / "good_inventory.yaml"),
            "--probe-glob", str(FIXTURES / "mini_probe_known_only.jsonl"),
            "--cloud-dump-glob", "/dev/null",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
