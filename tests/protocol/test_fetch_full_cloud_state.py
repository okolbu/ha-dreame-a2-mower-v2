"""Tests for the new fetch_full_cloud_state orchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient
from custom_components.dreame_a2_mower.cloud_state import CloudState

# Real raw batch from the user's account (preserved in research artifact).
REAL_BATCH = json.loads(
    Path(__file__).parent.parent.parent.joinpath(
        "docs/research/cloud-discovery/2026-05-08-empty-list-batch-dump.json"
    ).read_text()
)


def _make_client(batch_response, cfg_response, locn=None, dock=None, mapl=None, mihis=None):
    client = object.__new__(DreameA2CloudClient)
    client.get_batch_device_datas = MagicMock(return_value=batch_response)
    client.fetch_cfg = MagicMock(return_value=cfg_response or {})
    client.fetch_locn = MagicMock(return_value=locn)
    client.fetch_dock = MagicMock(return_value=dock or {})
    client.fetch_mapl = MagicMock(return_value=mapl)
    client.fetch_mihis = MagicMock(return_value=mihis or {})
    return client


def test_fetch_full_cloud_state_returns_cloud_state():
    client = _make_client(REAL_BATCH, {"VER": 461, "TIME": "Europe/Oslo"})
    cs = client.fetch_full_cloud_state()
    assert isinstance(cs, CloudState)
    # Real batch has 2 maps
    assert set(cs.maps_by_id.keys()) == {0, 1}
    # SETTINGS preserved both top-level entries
    assert len(cs.settings.raw) == 2
    # SETTINGS canonical dict has both map_ids — sourced from entry 0
    # (user-saved settings, see protocol/settings.py docstring).
    # mowingDirection differs per map (0 vs 180).
    assert set(cs.settings.by_map_id_canonical.keys()) == {0, 1}
    assert cs.settings.by_map_id_canonical[0]["mowingDirection"] == 0
    assert cs.settings.by_map_id_canonical[1]["mowingDirection"] == 180
    # Schedule has 2 slots
    assert len(cs.schedule.slots) == 2
    assert cs.schedule.slots[0].name.startswith("Spr")
    # M_PATH split — Map 0 empty, Map 1 has segments
    assert cs.mow_paths_by_map_id[0].segments == ()
    assert len(cs.mow_paths_by_map_id[1].segments) > 0
    # AI_HUMAN
    assert cs.ai_human_enabled is True
    # OTA_INFO
    assert cs.ota_status == (2, 100)
    # TASK_ID
    assert cs.task_id == 0
    # FBD_NTYPE per-map
    assert cs.forbidden_node_types_by_map[0] == {"101": 9}
    # CFG passed through
    assert cs.cfg["VER"] == 461


def test_fetch_full_cloud_state_handles_empty_batch():
    """If the cloud returns an empty batch, CloudState still constructs."""
    client = _make_client({}, {})
    cs = client.fetch_full_cloud_state()
    assert isinstance(cs, CloudState)
    assert cs.maps_by_id == {}
    assert cs.settings.raw == []
    assert cs.task_id == 0


def test_fetch_full_cloud_state_returns_none_on_total_failure():
    """If get_batch_device_datas raises, fetch_full_cloud_state returns None."""
    client = _make_client(None, None)
    client.get_batch_device_datas = MagicMock(side_effect=Exception("network"))
    cs = client.fetch_full_cloud_state()
    assert cs is None
