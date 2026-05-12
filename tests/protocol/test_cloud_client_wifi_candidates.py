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
    map_id is assigned via geometry (_assigned_by='geometry').

    Coords are in cm; resolution=2 means 2 m/cell = 200 cm/cell.
    """
    # 16×18 cells × 200 cm = 3200×3600 cm spanning (-1100..2100, -1500..2100);
    # centre at (500, 300).
    # 8×8 cells × 200 cm = 1600×1600 cm spanning (5000..6600, 5000..6600);
    # centre at (5800, 5800).
    bodies = {
        "wifimap_1700000001.json": _wifi_body(-1100, -1500, 16, 18),
        "wifimap_1700000002.json": _wifi_body(5000, 5000, 8, 8),
    }
    client = _make_client(list(bodies.keys()), bodies)
    extents = {
        0: (-2000.0, -2000.0, 2500.0, 2500.0),   # contains (500, 300)
        1: (5000.0, 5000.0, 10000.0, 10000.0),   # contains (5800, 5800)
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
        "wifimap_1700000001.json": _wifi_body(500000, 500000, 8, 8),
        "wifimap_1700000002.json": _wifi_body(600000, 600000, 8, 8),
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
    assigned to the leftover map via positional fallback.

    Heatmap A: startX=startY=0, 8×8 res=2 → centre (800, 800) cm.
    Heatmap B: startX=startY=999999, way outside.
    """
    bodies = {
        "wifimap_1700000001.json": _wifi_body(0, 0, 8, 8),
        "wifimap_1700000002.json": _wifi_body(999999, 999999, 8, 8),
    }
    client = _make_client(list(bodies.keys()), bodies)
    extents = {
        0: (0.0, 0.0, 2000.0, 2000.0),       # contains (800, 800)
        1: (3000.0, 3000.0, 5000.0, 5000.0), # nothing matches
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
        f"wifimap_170000000{i}.json": _wifi_body(999999, 999999, 8, 8)
        for i in (1, 2, 3)
    }
    client = _make_client(list(bodies.keys()), bodies)
    extents = {0: (0.0, 0.0, 100.0, 100.0), 1: (200.0, 200.0, 300.0, 300.0)}
    out = client.list_wifi_candidates(map_extents=extents)
    for r in out:
        assert r["map_id"] is None
        assert r["_assigned_by"] is None


def test_resolution_unit_is_metres_per_cell():
    """`resolution=2` means 2 m/cell, NOT 2 dm/cell.

    User-confirmed 2026-05-12 against actual lawn dimensions: a 16×18
    grid at res=2 covers 32×36 m of garden, not 3.2×3.6 m. The earlier
    decimeter interpretation was off by 10× and made the geometry
    matching reject every real-world candidate centre. Regression test.
    """
    # If treated as dm (× 10):    16 × 2 × 10 = 320 cm; centre (-1100 + 160, ...) = (-940, ...)
    # If treated as m  (× 100):   16 × 2 × 100 = 3200 cm; centre (-1100 + 1600, ...) = (500, ...)
    # Real-world: heatmap covers tens of metres → metres interpretation.
    bodies = {
        "wifimap_1700000001.json": _wifi_body(-1100, -1500, 16, 18),
    }
    client = _make_client(list(bodies.keys()), bodies)
    # Extent only catches the candidate under the metres interpretation.
    extents = {0: (-2000.0, -2000.0, 2500.0, 2500.0)}
    out = client.list_wifi_candidates(map_extents=extents)
    assert out[0]["map_id"] == 0
    assert out[0]["_assigned_by"] == "geometry"
