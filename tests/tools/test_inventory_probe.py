"""Tests for inventory_probe.py — primarily the safety-gate behavior."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).parents[2] / "tools" / "inventory_probe.py"


def test_probe_refuses_without_yes() -> None:
    """Refuses to run when stdin says 'n'."""
    result = subprocess.run(
        [sys.executable, str(TOOL), "--dry-run"],
        input="n\n",
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0  # Graceful no-op, not an error.
    assert "aborted" in result.stdout.lower()


def test_probe_dry_run_lists_planned_batches() -> None:
    """In dry-run with 'y', lists the planned read-only batches."""
    result = subprocess.run(
        [sys.executable, str(TOOL), "--dry-run"],
        input="y\n",
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for batch in ("getCFG", "cfg_individual sweep", "get_properties for apk-known"):
        assert batch in result.stdout
