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


def test_cloud_dump_walker_filters_error_candidates() -> None:
    """Candidates with _error in their response are confirmed-not-supported,
    not new protocol surface — exclude them from the missing list."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        dump_path = Path(td) / "dump_test_err.json"
        dump_path.write_text(json.dumps({
            "cfg_full": {"ok": {}},
            "cfg_individual": {},
            "candidates": {
                "FAKE_OK": {"d": {"value": 1}, "m": "r", "q": 1, "r": 0},
                "FAKE_ERR": {"_error": "endpoint returned r=-3"},
            },
        }))
        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                "--inventory", str(FIXTURES / "good_inventory.yaml"),
                "--probe-glob", "/dev/null",
                "--cloud-dump-glob", str(dump_path),
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0  # FAKE_OK still flagged as missing
        assert "FAKE_OK" in result.stdout
        # FAKE_ERR should NOT appear because it carried an _error.
        assert "FAKE_ERR" not in result.stdout


def test_cloud_dump_walker_skips_candidates_in_cfg_keys() -> None:
    """A candidate that's already a known CFG key is just a confirmed
    alternate-access-path, not a missing endpoint."""
    import json
    import tempfile
    import yaml as yaml_mod
    with tempfile.TemporaryDirectory() as td:
        dump_path = Path(td) / "dump_test_cfg.json"
        dump_path.write_text(json.dumps({
            "cfg_full": {"ok": {"WRP": [1, 8]}},  # WRP in cfg_keys
            "cfg_individual": {},
            "candidates": {
                "WRP": {"d": {"value": [1, 8]}, "m": "r", "q": 1, "r": 0},
            },
        }))
        # Build a fixture inventory that has WRP in cfg_keys.
        inv_path = Path(td) / "inv.yaml"
        inv_path.write_text(yaml_mod.safe_dump({
            "_sources": {},
            "properties": [],
            "events": [],
            "actions": [],
            "opcodes": [],
            "cfg_keys": [{"id": "WRP"}],
            "cfg_individual": [],
            "heartbeat_bytes": [],
            "telemetry_fields": [],
            "telemetry_variants": [],
            "s2p51_shapes": [],
            "state_codes": [],
            "mode_enum": [],
            "oss_map_keys": [],
            "session_summary_fields": [],
            "m_path_encoding": [],
            "lidar_pcd": [],
        }))
        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                "--inventory", str(inv_path),
                "--probe-glob", "/dev/null",
                "--cloud-dump-glob", str(dump_path),
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stdout  # Nothing missing.
        # Candidates section should be empty since WRP is in cfg_keys.
        cand_idx = result.stdout.find("Cloud-dump 'candidates' probes")
        assert cand_idx != -1
        next_section = result.stdout.find("##", cand_idx + 1)
        cand_section = result.stdout[cand_idx:next_section] if next_section != -1 else result.stdout[cand_idx:]
        assert "_(empty" in cand_section
