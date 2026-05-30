from unittest.mock import MagicMock
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.coordinator._lidar_oss import (
    _LidarOssMixin,
)


def _coord_with(lm):
    c = MagicMock(spec=_LidarOssMixin)
    c.live_map = lm
    return c


def test_inject_writes_maintenance_run_fields():
    lm = LiveMapState()
    lm.begin_session(1000)
    lm.target_ids = [2]
    lm.error_samples = [(1001, 75)]  # arrived at maintenance point, no 50/53
    raw: dict = {}
    _LidarOssMixin._inject_live_map_into_raw_dict(_coord_with(lm), raw)
    assert raw["session_type"] == "maintenance_run"
    assert raw["outcome"] == "arrived"
    assert raw["target_ids"] == [2]


def test_inject_writes_mow_fields():
    lm = LiveMapState()
    lm.begin_session(1000)
    lm.error_samples = [(1001, 50), (1100, 48)]  # mow start + complete
    raw: dict = {}
    _LidarOssMixin._inject_live_map_into_raw_dict(_coord_with(lm), raw)
    assert raw["session_type"] == "mow"
