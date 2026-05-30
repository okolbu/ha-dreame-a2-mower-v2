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


def test_inject_writes_patrol_fields_via_op_108():
    """op=108 (cruise/patrol) -> session_type=patrol. No mow-start, no area."""
    lm = LiveMapState()
    lm.begin_session(1000)
    lm.last_task_op = 108
    raw: dict = {}
    _LidarOssMixin._inject_live_map_into_raw_dict(_coord_with(lm), raw)
    assert raw["session_type"] == "patrol"
    assert "outcome" not in raw  # patrol has no maintenance-run outcome


def test_inject_writes_patrol_fields_via_s2p2_51():
    """s2p2=51 (patrol started) -> session_type=patrol even without op echo."""
    lm = LiveMapState()
    lm.begin_session(1000)
    lm.error_samples = [(1001, 51), (1100, 74)]  # patrol start + end
    raw: dict = {}
    _LidarOssMixin._inject_live_map_into_raw_dict(_coord_with(lm), raw)
    assert raw["session_type"] == "patrol"
