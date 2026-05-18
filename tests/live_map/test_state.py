"""Tests for live_map/state.py."""
from __future__ import annotations

from custom_components.dreame_a2_mower.live_map.state import LiveMapState


def test_default_state_is_inactive():
    s = LiveMapState()
    assert not s.is_active()
    assert s.total_points() == 0


def test_begin_session_clears_state():
    s = LiveMapState()
    s.legs = [[(1.0, 2.0)]]  # residue
    s.begin_session(started_unix=1000)
    assert s.is_active()
    assert s.legs == [[]]


def test_append_point_records_first_point():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 2.0, ts_unix=1010)
    assert s.legs == [[(1.0, 2.0)]]
    assert s.total_points() == 1
    assert s.last_telemetry_unix == 1010


def test_append_point_dedupes_close():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 2.0, ts_unix=1010)
    s.append_point(1.05, 2.05, ts_unix=1015)  # within 20cm
    assert s.total_points() == 1


def test_append_point_pen_up_jump_creates_new_leg():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(10.0, 0.0, ts_unix=1015)  # 10m jump > 5m
    assert len(s.legs) == 2
    assert s.total_points() == 2


def test_begin_leg_after_recharge_pause():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 1.0, ts_unix=1010)
    s.begin_leg()
    s.append_point(1.5, 1.5, ts_unix=2000)
    assert len(s.legs) == 2
    assert s.legs[0] == [(1.0, 1.0)]
    assert s.legs[1] == [(1.5, 1.5)]


def test_end_session_clears():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(1.0, 1.0, ts_unix=1010)
    s.end_session()
    assert not s.is_active()
    assert s.legs == []


def test_total_distance_m_empty():
    s = LiveMapState()
    assert s.total_distance_m() == 0.0
    s.begin_session(started_unix=1000)
    assert s.total_distance_m() == 0.0


def test_total_distance_m_single_leg():
    """Three colinear points 1 m apart sum to 2 m total."""
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(1.0, 0.0, ts_unix=1011)
    s.append_point(2.0, 0.0, ts_unix=1012)
    assert abs(s.total_distance_m() - 2.0) < 1e-9


def test_total_distance_m_excludes_pen_up_gap():
    """A >5 m jump starts a fresh leg — the gap itself must NOT count
    toward session distance, otherwise recharge round-trips would
    inflate the number every cycle."""
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(1.0, 0.0, ts_unix=1011)   # leg 0: 1.0 m
    s.append_point(50.0, 0.0, ts_unix=1012)  # >5 m jump → new leg
    s.append_point(53.0, 0.0, ts_unix=1013)  # leg 1: 3.0 m
    assert len(s.legs) == 2
    assert abs(s.total_distance_m() - 4.0) < 1e-9


def test_total_distance_m_pythagorean():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(3.0, 4.0, ts_unix=1011)   # 5 m segment
    assert abs(s.total_distance_m() - 5.0) < 1e-9


# ----------------- wifi_samples (v1.0.10a6+) -----------------


def test_wifi_samples_default_empty():
    s = LiveMapState()
    assert s.wifi_samples == []


def test_append_wifi_sample_records():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    assert s.append_wifi_sample(1.0, 2.0, -55, ts_unix=1010) is True
    assert s.wifi_samples == [(1.0, 2.0, -55, 1010)]


def test_append_wifi_sample_dedupes_same_position_same_rssi():
    """Stationary mower: heartbeats 45s apart at identical position+RSSI
    should collapse to a single sample (debounce)."""
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_wifi_sample(1.0, 2.0, -55, ts_unix=1010)
    # Same RSSI, within 25 cm — debounced.
    assert s.append_wifi_sample(1.05, 2.05, -55, ts_unix=1055) is False
    assert len(s.wifi_samples) == 1


def test_append_wifi_sample_keeps_when_rssi_changes():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_wifi_sample(1.0, 2.0, -55, ts_unix=1010)
    # Same position but RSSI changed → keep, RSSI drift over time matters.
    assert s.append_wifi_sample(1.0, 2.0, -60, ts_unix=1055) is True
    assert len(s.wifi_samples) == 2


def test_append_wifi_sample_keeps_when_position_moves():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_wifi_sample(0.0, 0.0, -55, ts_unix=1010)
    # Moved >25 cm — keep, even at same RSSI.
    assert s.append_wifi_sample(0.5, 0.5, -55, ts_unix=1055) is True
    assert len(s.wifi_samples) == 2


def test_begin_session_clears_wifi_samples():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_wifi_sample(1.0, 2.0, -55, ts_unix=1010)
    s.begin_session(started_unix=2000)
    assert s.wifi_samples == []


def test_end_session_clears_wifi_samples():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_wifi_sample(1.0, 2.0, -55, ts_unix=1010)
    s.end_session()
    assert s.wifi_samples == []


def test_append_wifi_sample_rejects_garbage():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    assert s.append_wifi_sample(None, 2.0, -55, 1010) is False  # type: ignore[arg-type]
    assert s.append_wifi_sample(1.0, 2.0, "bad", 1010) is False  # type: ignore[arg-type]
    assert s.wifi_samples == []


# ----------------- settings_snapshot (v1.0.8+) -----------------


def test_begin_session_clears_settings_snapshot():
    state = LiveMapState()
    state.settings_snapshot = {"foo": 1}
    state.begin_session(123456)
    assert state.settings_snapshot is None


def test_end_session_clears_settings_snapshot():
    state = LiveMapState()
    state.begin_session(123456)
    state.settings_snapshot = {"foo": 1}
    state.end_session()
    assert state.settings_snapshot is None


def test_settings_snapshot_defaults_none():
    state = LiveMapState()
    assert state.settings_snapshot is None


# ----------------- mowing-vs-traversal split (v1.0.16a6+) -----------------


def test_default_legs_classified_mowing():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(0.5, 0.0, ts_unix=1011)
    assert s.mowing_legs == [[(0.0, 0.0), (0.5, 0.0)]]
    assert s.traversal_legs == []


def test_set_mowing_false_starts_new_traversal_leg():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.append_point(0.5, 0.0, ts_unix=1011)
    # Mower transitions away from MOWING (e.g. RETURNING to dock).
    s.set_mowing(False)
    s.append_point(1.0, 0.0, ts_unix=1012)
    s.append_point(1.5, 0.0, ts_unix=1013)
    assert s.mowing_legs == [[(0.0, 0.0), (0.5, 0.0)]]
    assert s.traversal_legs == [[(1.0, 0.0), (1.5, 0.0)]]


def test_set_mowing_round_trip_flips_legs_twice():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.set_mowing(False)
    s.append_point(1.0, 0.0, ts_unix=1011)
    s.set_mowing(True)
    s.append_point(2.0, 0.0, ts_unix=1012)
    assert s.mowing_legs == [[(0.0, 0.0)], [(2.0, 0.0)]]
    assert s.traversal_legs == [[(1.0, 0.0)]]


def test_set_mowing_idempotent_on_same_value():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.set_mowing(True)  # already mowing — should not split the leg
    s.append_point(0.5, 0.0, ts_unix=1011)
    assert s.mowing_legs == [[(0.0, 0.0), (0.5, 0.0)]]
    assert s.traversal_legs == []


def test_dump_and_hydrate_preserves_leg_is_mowing():
    s = LiveMapState()
    s.begin_session(started_unix=1000)
    s.append_point(0.0, 0.0, ts_unix=1010)
    s.set_mowing(False)
    s.append_point(1.0, 0.0, ts_unix=1011)
    payload = s.dump_to_payload()
    assert payload["leg_is_mowing"] == [True, False]
    restored = LiveMapState()
    restored.hydrate_from_payload(payload)
    assert restored.leg_is_mowing == [True, False]
    assert restored.mowing_legs == [[(0.0, 0.0)]]
    assert restored.traversal_legs == [[(1.0, 0.0)]]


def test_hydrate_pre_v1_0_16a6_payload_defaults_to_mowing():
    """In_progress.json from before v1.0.16a6 lacks leg_is_mowing —
    hydrate must default every restored leg to mowing=True so the
    restored trail renders correctly."""
    s = LiveMapState()
    legacy = {
        "session_start_ts": 1000,
        "legs": [[[0.0, 0.0]], [[1.0, 0.0]]],
        # no leg_is_mowing key — legacy payload
    }
    s.hydrate_from_payload(legacy)
    assert s.leg_is_mowing == [True, True]
    assert len(s.mowing_legs) == 2
    assert s.traversal_legs == []
