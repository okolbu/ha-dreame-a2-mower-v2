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


def test_cloud_dump_walker_unwraps_cfg_full_ok() -> None:
    """cfg_full is wrapped as {ok: {<real keys>}}; walker must look inside."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        dump_path = Path(td) / "dump_test.json"
        dump_path.write_text(json.dumps({
            "cfg_full": {
                "ok": {"WRP": [1, 8], "DND": [0, 1200, 480]},
            },
            "cfg_individual": {},
            "candidates": {},
        }))
        # Use an inventory with neither WRP nor DND in cfg_keys.
        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                "--inventory", str(FIXTURES / "good_inventory.yaml"),
                "--probe-glob", "/dev/null",
                "--cloud-dump-glob", str(dump_path),
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0, result.stdout
        # The audit must report WRP and DND as missing CFG keys, NOT 'ok'.
        assert "WRP" in result.stdout
        assert "DND" in result.stdout
        # Negative: 'ok' should not appear as a missing CFG key.
        # Search the relevant section to avoid matching banner text.
        cfg_section_start = result.stdout.find("Cloud-dump CFG keys not in inventory")
        assert cfg_section_start != -1
        next_section = result.stdout.find("##", cfg_section_start + 1)
        cfg_section = result.stdout[cfg_section_start:next_section]
        assert "`ok`" not in cfg_section
