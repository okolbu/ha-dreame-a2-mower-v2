"""Tests for cloud_client.list_wifi_candidates positional fallback.

The cloud returns one wifimap OSS object per map but in a
newest-first global array — geometry matching is primary, but when
candidate bboxes don't fall inside any provided map_extent (e.g.,
overlapping or co-located map frames), positional assignment by
array order is the tier-2 fallback.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def _make_client(obj_names: list[str], decoded_bodies: dict[str, dict]):
    client = object.__new__(DreameA2CloudClient)
    client.action = MagicMock(
        return_value={"out": [{"d": {"name": list(obj_names)}}]}
    )
    client.get_interim_file_url = MagicMock(
        side_effect=lambda name: f"https://oss.example.com/{name}"
    )
    client.get_file = MagicMock(
        side_effect=lambda url: json.dumps(
            decoded_bodies[url.rsplit("/", 1)[-1]]
        ).encode()
    )
    return client


def _wifi_body(start_x: float, start_y: float, w: int, h: int, res: int = 2) -> dict:
    return {
        "data": [-50] * (w * h),
        "width": w,
        "height": h,
        "resolution": res,
        "startX": start_x,
        "startY": start_y,
    }


def test_geometry_match_assigns_map_ids():
    """When candidate bbox centers fall inside their map's extent,
    map_id is assigned via geometry (_assigned_by='geometry')."""
    bodies = {
        "wifimap_1700000001.json": _wifi_body(-1100, -1500, 16, 18),  # center 60, -1320
        "wifimap_1700000002.json": _wifi_body(0, 0, 8, 8),            # center 80, 80
    }
    client = _make_client(list(bodies.keys()), bodies)
    extents = {
        0: (-2000.0, -2000.0, 200.0, 0.0),    # contains (60, -1320)
        1: (0.0, 0.0, 1000.0, 1000.0),        # contains (80, 80)
    }
    out = client.list_wifi_candidates(map_extents=extents)
    by_name = {r["object_name"]: r for r in out}
    assert by_name["wifimap_1700000001.json"]["map_id"] == 0
    assert by_name["wifimap_1700000001.json"]["_assigned_by"] == "geometry"
    assert by_name["wifimap_1700000002.json"]["map_id"] == 1
    assert by_name["wifimap_1700000002.json"]["_assigned_by"] == "geometry"


def test_positional_fallback_when_geometry_misses_all():
    """When neither candidate's bbox center falls inside any map's
    extent, but the candidate count equals the map count, assign
    by array position (sorted map_id) and stamp _assigned_by='positional'."""
    # Both candidates' geometry centers fall far outside both map extents.
    bodies = {
        "wifimap_1700000001.json": _wifi_body(50000, 50000, 8, 8),
        "wifimap_1700000002.json": _wifi_body(60000, 60000, 8, 8),
    }
    client = _make_client(list(bodies.keys()), bodies)
    extents = {
        0: (-100.0, -100.0, 100.0, 100.0),
        1: (200.0, 200.0, 400.0, 400.0),
    }
    out = client.list_wifi_candidates(map_extents=extents)
    by_name = {r["object_name"]: r for r in out}
    # API array order: name1 first, name2 second.
    # Unmatched map_ids sorted: [0, 1].
    # → name1 → map_id 0, name2 → map_id 1.
    assert by_name["wifimap_1700000001.json"]["map_id"] == 0
    assert by_name["wifimap_1700000001.json"]["_assigned_by"] == "positional"
    assert by_name["wifimap_1700000002.json"]["map_id"] == 1
    assert by_name["wifimap_1700000002.json"]["_assigned_by"] == "positional"


def test_positional_fallback_mixed_with_geometry():
    """One candidate geometry-matches; the leftover candidate is
    assigned to the leftover map via positional fallback."""
    bodies = {
        "wifimap_1700000001.json": _wifi_body(50, 50, 8, 8),  # center 130, 130 — inside map 0
        "wifimap_1700000002.json": _wifi_body(99999, 99999, 8, 8),  # nowhere
    }
    client = _make_client(list(bodies.keys()), bodies)
    extents = {
        0: (0.0, 0.0, 500.0, 500.0),
        1: (1000.0, 1000.0, 2000.0, 2000.0),
    }
    out = client.list_wifi_candidates(map_extents=extents)
    by_name = {r["object_name"]: r for r in out}
    assert by_name["wifimap_1700000001.json"]["map_id"] == 0
    assert by_name["wifimap_1700000001.json"]["_assigned_by"] == "geometry"
    # name2 left unmatched by geometry; the only unmatched map is 1.
    assert by_name["wifimap_1700000002.json"]["map_id"] == 1
    assert by_name["wifimap_1700000002.json"]["_assigned_by"] == "positional"


def test_no_fallback_when_count_mismatch():
    """If unmatched candidate count != unmatched map count, no
    positional assignment happens (avoids guessing under ambiguity)."""
    # 3 candidates, all geometry-miss; only 2 maps. Don't guess.
    bodies = {
        f"wifimap_170000000{i}.json": _wifi_body(99999, 99999, 8, 8)
        for i in (1, 2, 3)
    }
    client = _make_client(list(bodies.keys()), bodies)
    extents = {0: (0.0, 0.0, 100.0, 100.0), 1: (200.0, 200.0, 300.0, 300.0)}
    out = client.list_wifi_candidates(map_extents=extents)
    for r in out:
        assert r["map_id"] is None
        assert r["_assigned_by"] is None
