from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_begin_session_resets_type_tracking_fields():
    lm = LiveMapState()
    lm.target_ids = [9]
    lm.last_task_op = 103
    lm.area_ever_positive = True
    lm.begin_session(1000)
    assert lm.target_ids == []
    assert lm.last_task_op is None
    assert lm.area_ever_positive is False
