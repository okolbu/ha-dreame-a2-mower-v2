"""After a successful ALL_AREAS or ZONE finalize, last_all_area_mow_direction_deg
is updated for that map. Edge/spot finalizes do NOT touch it.

Adaptation notes vs. task plan:
- The cloud summary wire format uses map[{type:0, track:[[x_cm, y_cm],...]}].
  parse_session_summary reads from the `map` key, not a `track_segments` key.
  Tests here build real wire-format dicts so parse_session_summary produces a
  non-empty summary.track_segments.
- summary.track_segments returns metres; infer_mow_direction expects mm.
  The wiring code scales * 1000 before calling infer_mow_direction.
"""
import asyncio
import dataclasses
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_coordinator import _make_coordinator_for_finalize_tests  # noqa: E402

from custom_components.dreame_a2_mower.mower.state import ActionMode


def _make_summary_with_track_wire_format(angle_deg: int) -> dict:
    """Build a minimal cloud-summary wire dict with one long mow-track segment.

    Track points are in cm (wire format). A 20m segment clears the
    MIN_SEGMENT_M=0.5m threshold in infer_mow_direction.

    We use a single straight segment from (0,0) to (dx_cm, dy_cm) so the
    inferred angle should be exactly angle_deg (mod 180).
    """
    a = math.radians(angle_deg)
    # 20m = 2000 cm
    dx_cm = int(round(2000 * math.cos(a)))
    dy_cm = int(round(2000 * math.sin(a)))
    return {
        "start": 1_700_000_000,
        "end": 1_700_003_600,
        "time": 60,
        "mode": 0,
        "result": 0,
        "stop_reason": 0,
        "start_mode": 0,
        "pre_type": 0,
        "md5": "abc",
        "areas": 120.5,
        "map_area": 5000,
        "dock": None,
        "pref": [],
        "region_status": [],
        "faults": [],
        "spot": [],
        "ai_obstacle": [],
        "obstacle": [],
        "trajectory": [],
        "map": [
            {
                "id": 0,
                "type": 0,   # BoundaryLayer
                "name": "Main Lawn",
                "area": 120.5,
                "etime": 0,
                "time": 60,
                "data": [[0, 0], [2000, 0], [2000, 2000], [0, 2000], [0, 0]],
                "track": [[0, 0], [dx_cm, dy_cm]],
            }
        ],
    }


def test_finalize_all_areas_writes_last_direction():
    """ALL_AREAS finalize records inferred direction in last_all_area_mow_direction_deg."""
    raw = json.dumps(_make_summary_with_track_wire_format(90)).encode()
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/s.json",
        pending_first_attempt_unix=1_700_000_000,
        cloud_get_file_return=raw,
    )
    coord.data = dataclasses.replace(coord.data, action_mode=ActionMode.ALL_AREAS)
    coord._active_map_id = 0
    coord.session_archive.count = 1

    asyncio.run(coord._do_oss_fetch(1_700_000_900))

    assert 0 in coord.data.last_all_area_mow_direction_deg
    assert coord.data.last_all_area_mow_direction_deg[0] == 90


def test_finalize_zone_writes_last_direction():
    """ZONE finalize also records inferred direction."""
    raw = json.dumps(_make_summary_with_track_wire_format(45)).encode()
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/s.json",
        pending_first_attempt_unix=1_700_000_000,
        cloud_get_file_return=raw,
    )
    coord.data = dataclasses.replace(coord.data, action_mode=ActionMode.ZONE)
    coord._active_map_id = 0
    coord.session_archive.count = 1

    asyncio.run(coord._do_oss_fetch(1_700_000_900))

    assert 0 in coord.data.last_all_area_mow_direction_deg
    assert coord.data.last_all_area_mow_direction_deg[0] == 45


def test_finalize_edge_does_not_touch_last_direction():
    """EDGE finalize does NOT update last_all_area_mow_direction_deg."""
    raw = json.dumps(_make_summary_with_track_wire_format(45)).encode()
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/s.json",
        pending_first_attempt_unix=1_700_000_000,
        cloud_get_file_return=raw,
    )
    coord.data = dataclasses.replace(coord.data, action_mode=ActionMode.EDGE)
    coord._active_map_id = 0
    coord.session_archive.count = 1

    asyncio.run(coord._do_oss_fetch(1_700_000_900))

    assert 0 not in coord.data.last_all_area_mow_direction_deg


def test_finalize_spot_does_not_touch_last_direction():
    """SPOT finalize does NOT update last_all_area_mow_direction_deg."""
    raw = json.dumps(_make_summary_with_track_wire_format(45)).encode()
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/s.json",
        pending_first_attempt_unix=1_700_000_000,
        cloud_get_file_return=raw,
    )
    coord.data = dataclasses.replace(coord.data, action_mode=ActionMode.SPOT)
    coord._active_map_id = 0
    coord.session_archive.count = 1

    asyncio.run(coord._do_oss_fetch(1_700_000_900))

    assert 0 not in coord.data.last_all_area_mow_direction_deg


def test_finalize_no_active_map_id_does_not_write():
    """When _active_map_id is None, last_all_area_mow_direction_deg is not updated."""
    raw = json.dumps(_make_summary_with_track_wire_format(30)).encode()
    coord = _make_coordinator_for_finalize_tests(
        pending_object_name="d/s.json",
        pending_first_attempt_unix=1_700_000_000,
        cloud_get_file_return=raw,
    )
    coord.data = dataclasses.replace(coord.data, action_mode=ActionMode.ALL_AREAS)
    coord._active_map_id = None
    coord.session_archive.count = 1

    asyncio.run(coord._do_oss_fetch(1_700_000_900))

    assert coord.data.last_all_area_mow_direction_deg == {}
