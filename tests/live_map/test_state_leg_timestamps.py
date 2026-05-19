from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_begin_session_initializes_leg_timestamps():
    s = LiveMapState()
    s.begin_session(1000)
    assert s.leg_start_ts == [1000]
    assert s.leg_end_ts == [1000]


def test_append_point_advances_leg_end_ts_only():
    s = LiveMapState()
    s.begin_session(1000)
    s.append_point(0.0, 0.0, 1001)
    s.append_point(1.0, 0.0, 1005)
    assert s.leg_start_ts == [1000]
    assert s.leg_end_ts == [1005]


def test_set_mowing_split_records_boundary_ts():
    s = LiveMapState()
    s.begin_session(1000)
    s.append_point(0.0, 0.0, 1001)
    s.append_point(1.0, 0.0, 1005)
    s.set_mowing(False)            # current leg ends here
    s.append_point(2.0, 0.0, 1008) # new leg starts here
    assert s.leg_start_ts == [1000, 1005]
    assert s.leg_end_ts   == [1005, 1008]
    assert s.leg_is_mowing == [True, False]


def test_begin_leg_records_boundary_ts():
    s = LiveMapState()
    s.begin_session(1000)
    s.append_point(0.0, 0.0, 1001)
    s.last_telemetry_unix = 1010   # last seen telemetry before pause
    s.begin_leg()
    assert s.leg_start_ts == [1000, 1010]
    assert s.leg_end_ts   == [1010, 1010]


def test_dump_and_hydrate_roundtrip():
    s = LiveMapState()
    s.begin_session(1000)
    s.append_point(0.0, 0.0, 1001)
    s.set_mowing(False)
    s.append_point(2.0, 0.0, 1008)
    payload = s.dump_to_payload()
    assert payload["leg_start_ts"] == [1000, 1001]
    assert payload["leg_end_ts"]   == [1001, 1008]

    s2 = LiveMapState()
    s2.hydrate_from_payload(payload)
    assert s2.leg_start_ts == [1000, 1001]
    assert s2.leg_end_ts   == [1001, 1008]
