"""Tests for the cloud `paths` key (gray nav-paths between maps)."""
from __future__ import annotations

from custom_components.dreame_a2_mower.map_decoder import (
    MapData,
    NavPath,
    parse_cloud_map,
)


def _make_minimal_cloud_response_with_paths():
    """Minimal cloud response with a single boundary + one nav path."""
    return {
        "boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000},
        "mowingAreas": {},
        "paths": {
            "0": {
                "path": [
                    {"x": 1000, "y": 1000},
                    {"x": 2000, "y": 1500},
                    {"x": 3000, "y": 2000},
                ],
                "type": 0,
            },
        },
        "totalArea": 100,
    }


def test_parse_cloud_map_decodes_nav_paths():
    """A `paths` entry produces a NavPath with cloud-mm coords intact."""
    response = _make_minimal_cloud_response_with_paths()
    map_data = parse_cloud_map(response)

    assert map_data is not None
    assert len(map_data.nav_paths) == 1
    nav = map_data.nav_paths[0]
    assert isinstance(nav, NavPath)
    assert nav.path_id == 0
    assert nav.path_type == 0
    assert nav.path == ((1000.0, 1000.0), (2000.0, 1500.0), (3000.0, 2000.0))


def test_parse_cloud_map_with_no_paths_key_yields_empty_tuple():
    """No `paths` key → `nav_paths == ()`, not None."""
    response = {
        "boundary": {"x1": 0, "y1": 0, "x2": 10000, "y2": 10000},
        "mowingAreas": {},
        "totalArea": 100,
    }
    map_data = parse_cloud_map(response)
    assert map_data is not None
    assert map_data.nav_paths == ()
