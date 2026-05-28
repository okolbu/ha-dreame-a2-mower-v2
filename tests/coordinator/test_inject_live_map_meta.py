"""Tests for _inject_live_map_into_raw_dict — writes the per-point track."""
from __future__ import annotations

import types

from custom_components.dreame_a2_mower.coordinator._lidar_oss import _LidarOssMixin
from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def _coord_with_track():
    lm = LiveMapState()
    lm.begin_session(started_unix=1000)
    lm.update_task_state(1000.0, 0)
    lm.append_point(1001.0, 0.0, 0.0, 0.0, 0.0)        # traversal
    lm.append_point(1002.0, 1.0, 0.0, 0.5, 0.0)        # mowing
    obj = types.SimpleNamespace(live_map=lm)
    obj._inject_live_map_into_raw_dict = types.MethodType(
        _LidarOssMixin._inject_live_map_into_raw_dict, obj
    )
    return obj


def test_inject_writes_track():
    obj = _coord_with_track()
    raw: dict = {}
    obj._inject_live_map_into_raw_dict(raw)
    assert "track" in raw
    assert len(raw["track"]) == 2
    first = raw["track"][0]
    # serialized as a list row [t, x, y, area, heading, task_state, role]
    assert first[6] == "traversal"
    assert raw["track"][1][6] == "mowing"
    for dead in ("_local_legs", "_mowing_legs", "_traversal_legs", "_legs_meta"):
        assert dead not in raw


from custom_components.dreame_a2_mower.coordinator._lidar_oss import (
    finalize_classify_raw_dict,
)


def test_finalize_stores_cloud_track_but_does_not_rescue():
    # cloud_track is stored verbatim, but roles are NOT upgraded by cloud
    # proximity — area-delta is authoritative (rescue removed). Two genuine
    # traversal points sitting on a cloud mowing segment must STAY traversal.
    raw = {
        "track": [
            [0, 0.0, 0.0, 0.0, None, 0, "traversal"],
            [1, 1.0, 0.0, 0.0, None, 0, "traversal"],  # on cloud path, area flat
        ],
    }
    cloud_segments = [[(0.0, 0.0), (1.0, 0.0)]]
    finalize_classify_raw_dict(raw, cloud_segments)
    assert raw["cloud_track"] == [[[0.0, 0.0], [1.0, 0.0]]]
    assert [row[6] for row in raw["track"]] == ["traversal", "traversal"]


def test_finalize_classify_handles_empty_track():
    raw = {"track": []}
    finalize_classify_raw_dict(raw, [])
    assert raw["cloud_track"] == []
    assert raw["track"] == []
