"""Tests for _inject_live_map_into_raw_dict — _legs_meta emission."""
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_inject_writes_legs_meta():
    from custom_components.dreame_a2_mower.coordinator import _lidar_oss

    coord = MagicMock()
    coord.live_map = LiveMapState()
    coord.live_map.begin_session(1000)
    coord.live_map.append_point(0.0, 0.0, 1001)
    coord.live_map.set_mowing(False)
    coord.live_map.append_point(2.0, 0.0, 1008)

    raw: dict = {}
    _lidar_oss._LidarOssMixin._inject_live_map_into_raw_dict(coord, raw)
    assert raw["_legs_meta"] == [
        {"role": "mowing",    "start_ts": 1000, "end_ts": 1001},
        {"role": "traversal", "start_ts": 1001, "end_ts": 1008},
    ]
