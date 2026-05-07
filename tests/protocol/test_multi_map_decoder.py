"""Tests for parse_cloud_maps (multi-map cloud response)."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.map_decoder import (
    MapData,
    parse_cloud_maps,
)

FIXTURE = Path(__file__).parent / "fixtures" / "multi_map_response.json"


def test_parse_cloud_maps_returns_dict_by_id():
    fixture = json.loads(FIXTURE.read_text())
    by_id = {int(k): v for k, v in fixture["by_id"].items()}

    parsed = parse_cloud_maps(by_id)

    assert set(parsed.keys()) == {0, 1}
    assert all(isinstance(m, MapData) for m in parsed.values())


def test_parse_cloud_maps_stamps_map_id_and_name():
    fixture = json.loads(FIXTURE.read_text())
    by_id = {int(k): v for k, v in fixture["by_id"].items()}

    parsed = parse_cloud_maps(by_id)

    assert parsed[0].map_id == 0
    assert parsed[0].name == "Map 1"
    assert parsed[1].map_id == 1
    assert parsed[1].name == "Map 2"


def test_parse_cloud_maps_decodes_nav_paths_per_map():
    fixture = json.loads(FIXTURE.read_text())
    by_id = {int(k): v for k, v in fixture["by_id"].items()}

    parsed = parse_cloud_maps(by_id)

    assert parsed[0].nav_paths == ()  # Map 1 has no paths
    assert len(parsed[1].nav_paths) == 1  # Map 2 has one connecting path
    assert parsed[1].nav_paths[0].path_id == 0


def test_parse_cloud_maps_skips_invalid_entries():
    """Entries that fail parse_cloud_map are dropped, not raised."""
    by_id = {
        0: {"boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000}, "mowingAreas": {}, "totalArea": 100, "mapIndex": 0},
        1: {"this_is_not_a_valid_map_response": True},  # bad
    }

    parsed = parse_cloud_maps(by_id)

    assert 0 in parsed
    assert 1 not in parsed
