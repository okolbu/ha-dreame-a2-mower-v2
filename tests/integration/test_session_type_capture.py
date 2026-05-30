from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.coordinator import _mqtt_handlers as MH


def test_capture_helpers_update_live_map():
    lm = LiveMapState()
    lm.begin_session(1000)
    MH.capture_session_type_signals(
        lm, s2p56_status=[[1, 0], [2, -1]], s2p50_op=None, area_m2=0.0,
    )
    assert lm.target_ids == [1, 2]
    MH.capture_session_type_signals(
        lm, s2p56_status=None, s2p50_op=103, area_m2=0.0,
    )
    assert lm.last_task_op == 103
    MH.capture_session_type_signals(
        lm, s2p56_status=None, s2p50_op=None, area_m2=1.4,
    )
    assert lm.area_ever_positive is True
    MH.capture_session_type_signals(
        lm, s2p56_status=[[2, 0]], s2p50_op=None, area_m2=0.0,
    )
    assert lm.target_ids == [1, 2]  # 2 already last -> no duplicate
