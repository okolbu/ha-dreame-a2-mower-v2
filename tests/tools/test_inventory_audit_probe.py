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


# ---------------------------------------------------------------------------
# Consistency-check tests (H1)
# ---------------------------------------------------------------------------

def test_consistency_not_on_g2408_fires_on_ok_response() -> None:
    """A cfg_individual row marked not_on_g2408:true that returns ok in ANY
    dump must be flagged as a contradiction."""
    import json
    import tempfile
    import yaml as yaml_mod

    with tempfile.TemporaryDirectory() as td:
        # Build an inventory with one cfg_individual endpoint marked not_on_g2408.
        inv_path = (Path(td) / "inv.yaml")
        inv_path.write_text(yaml_mod.safe_dump({
            "_sources": {},
            "properties": [], "events": [], "actions": [], "opcodes": [],
            "cfg_keys": [],
            "cfg_individual": [
                {
                    "id": "FAKE_EP",
                    "status": {
                        "seen_on_wire": False,
                        "decoded": "hypothesized",
                        "bt_only": False,
                        "not_on_g2408": True,  # claimed absent
                    },
                }
            ],
            "heartbeat_bytes": [], "telemetry_fields": [], "telemetry_variants": [],
            "s2p51_shapes": [], "state_codes": [], "mode_enum": [],
            "oss_map_keys": [], "session_summary_fields": [],
            "m_path_encoding": [], "lidar_pcd": [],
        }))
        # Build a dump where FAKE_EP returned ok — contradicts not_on_g2408.
        dump_path = Path(td) / "dump_x.json"
        dump_path.write_text(json.dumps({
            "cfg_full": {"ok": {}},
            "cfg_individual": {
                "FAKE_EP": {"ok": {"d": {"value": 1}, "m": "r", "q": 1, "r": 0}},
            },
            "candidates": {},
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
        assert result.returncode != 0, result.stdout
        assert "FAKE_EP" in result.stdout
        assert "not_on_g2408" in result.stdout.lower() or "contradiction" in result.stdout.lower() or "claimed" in result.stdout.lower()


def test_consistency_seen_on_wire_false_fires_when_observed() -> None:
    """A property row claiming seen_on_wire:false that appears in the probe
    log must be flagged as a contradiction."""
    import json
    import tempfile
    import yaml as yaml_mod

    with tempfile.TemporaryDirectory() as td:
        inv_path = Path(td) / "inv.yaml"
        inv_path.write_text(yaml_mod.safe_dump({
            "_sources": {},
            "properties": [
                {
                    "id": "s9p99",
                    "siid": 9,
                    "piid": 99,
                    "name": "mystery",
                    "category": "property",
                    "payload_shape": "int",
                    "status": {
                        "seen_on_wire": False,  # claimed not seen
                        "decoded": "hypothesized",
                        "bt_only": False,
                        "not_on_g2408": False,
                    },
                }
            ],
            "events": [], "actions": [], "opcodes": [], "cfg_keys": [],
            "cfg_individual": [],
            "heartbeat_bytes": [], "telemetry_fields": [], "telemetry_variants": [],
            "s2p51_shapes": [], "state_codes": [], "mode_enum": [],
            "oss_map_keys": [], "session_summary_fields": [],
            "m_path_encoding": [], "lidar_pcd": [],
        }))
        # Build a probe log with a properties_changed entry for s9p99.
        probe_path = Path(td) / "probe_log_test.jsonl"
        probe_path.write_text(json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-05 10:00:00",
            "parsed_data": {
                "method": "properties_changed",
                "params": [{"siid": 9, "piid": 99, "value": 42}],
            },
        }) + "\n")

        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                "--inventory", str(inv_path),
                "--probe-glob", str(probe_path),
                "--cloud-dump-glob", "/dev/null",
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0, result.stdout
        assert "s9p99" in result.stdout
        assert "seen_on_wire" in result.stdout


def test_consistency_value_catalog_gap_fires_on_novel_value() -> None:
    """A property with a value_catalog and seen_on_wire:true that has an
    observed probe-log value not in the catalog must be flagged."""
    import json
    import tempfile
    import yaml as yaml_mod

    with tempfile.TemporaryDirectory() as td:
        inv_path = Path(td) / "inv.yaml"
        inv_path.write_text(yaml_mod.safe_dump({
            "_sources": {},
            "properties": [
                {
                    "id": "s2p1",
                    "siid": 2,
                    "piid": 1,
                    "name": "mode",
                    "category": "property",
                    "payload_shape": "int (enum)",
                    "value_catalog": {1: "Mowing", 2: "Idle"},  # missing value 99
                    "status": {
                        "seen_on_wire": True,
                        "first_seen": "2026-05-05",
                        "last_seen": "2026-05-05",
                        "decoded": "confirmed",
                        "bt_only": False,
                        "not_on_g2408": False,
                    },
                }
            ],
            "events": [], "actions": [], "opcodes": [], "cfg_keys": [],
            "cfg_individual": [],
            "heartbeat_bytes": [], "telemetry_fields": [], "telemetry_variants": [],
            "s2p51_shapes": [], "state_codes": [], "mode_enum": [],
            "oss_map_keys": [], "session_summary_fields": [],
            "m_path_encoding": [], "lidar_pcd": [],
        }))
        # Probe log emits value 99 for s2p1 — not in the catalog.
        probe_path = Path(td) / "probe_log_test.jsonl"
        probe_path.write_text(json.dumps({
            "type": "mqtt_message",
            "timestamp": "2026-05-05 10:00:00",
            "parsed_data": {
                "method": "properties_changed",
                "params": [{"siid": 2, "piid": 1, "value": 99}],
            },
        }) + "\n")

        result = subprocess.run(
            [
                sys.executable, str(TOOL),
                "--inventory", str(inv_path),
                "--probe-glob", str(probe_path),
                "--cloud-dump-glob", "/dev/null",
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0, result.stdout
        assert "s2p1" in result.stdout
        assert "99" in result.stdout
        assert "catalog" in result.stdout.lower() or "novel" in result.stdout.lower()


def test_dump_properties_walker_finds_cloud_rpc_only_slot() -> None:
    """A slot that appears in dump.properties but not the inventory
    properties section is reported as a missing cloud-dump property.

    Models the s4p68 / s1p5 discoveries from 2026-05-06: cloud-RPC-only
    slots that never appear in the MQTT probe corpus.
    """
    import json
    import tempfile
    import yaml as yaml_mod
    with tempfile.TemporaryDirectory() as td:
        # Inventory has s2p1 in properties but NOT s4p68.
        inv_path = Path(td) / "inv.yaml"
        inv_path.write_text(yaml_mod.safe_dump({
            "_sources": {},
            "properties": [{
                "id": "s2p1", "siid": 2, "piid": 1, "name": "status",
                "category": "property", "payload_shape": "int",
                "status": {"seen_on_wire": True, "decoded": "confirmed",
                           "bt_only": False, "not_on_g2408": False},
                "references": {},
            }],
            "events": [], "actions": [], "opcodes": [], "cfg_keys": [],
            "cfg_individual": [], "heartbeat_bytes": [],
            "telemetry_fields": [], "telemetry_variants": [],
            "s2p51_shapes": [], "state_codes": [], "mode_enum": [],
            "oss_map_keys": [], "session_summary_fields": [],
            "m_path_encoding": [], "lidar_pcd": [],
        }))
        # Dump.properties has both s2p1 (known) and s4p68 (novel).
        dump_path = Path(td) / "dump_test.json"
        dump_path.write_text(json.dumps({
            "cfg_full": {"ok": {}},
            "cfg_individual": {},
            "candidates": {},
            "properties": {
                "s2p1": {"ok": [{"siid": 2, "piid": 1, "value": 13}]},
                "s4p68": {"ok": [{"siid": 4, "piid": 68, "value": []}]},
            },
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
        assert result.returncode != 0, result.stdout
        # Check the new "Cloud-dump properties not in inventory" section.
        section_idx = result.stdout.find("Cloud-dump properties not in inventory")
        assert section_idx != -1, "new section header missing"
        next_section = result.stdout.find("##", section_idx + 1)
        section_text = result.stdout[section_idx:next_section] if next_section != -1 else result.stdout[section_idx:]
        assert "s4p68" in section_text, f"s4p68 not flagged in: {section_text}"
        # s2p1 is in inventory; should NOT appear in the missing section.
        assert "`s2p1`" not in section_text


def test_dump_properties_walker_skips_error_responses() -> None:
    """A property with `_error` in its dump response is not flagged
    (firmware refused the get_properties; not a real protocol slot)."""
    import json
    import tempfile
    import yaml as yaml_mod
    with tempfile.TemporaryDirectory() as td:
        inv_path = Path(td) / "inv.yaml"
        inv_path.write_text(yaml_mod.safe_dump({
            "_sources": {},
            "properties": [], "events": [], "actions": [], "opcodes": [],
            "cfg_keys": [], "cfg_individual": [], "heartbeat_bytes": [],
            "telemetry_fields": [], "telemetry_variants": [],
            "s2p51_shapes": [], "state_codes": [], "mode_enum": [],
            "oss_map_keys": [], "session_summary_fields": [],
            "m_path_encoding": [], "lidar_pcd": [],
        }))
        dump_path = Path(td) / "dump_test.json"
        dump_path.write_text(json.dumps({
            "cfg_full": {"ok": {}},
            "cfg_individual": {},
            "candidates": {},
            "properties": {
                "s4p99": {"_error": "code -1 firmware refused"},
            },
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
        # Empty inventory, no observations → exit 0; s4p99 not flagged.
        assert "s4p99" not in result.stdout
        assert result.returncode == 0
