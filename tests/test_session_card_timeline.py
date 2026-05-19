# tests/test_session_card_timeline.py
from custom_components.dreame_a2_mower.session_card import build_picked_session_summary
from types import SimpleNamespace


def _make_summary(track_segments=()):
    return SimpleNamespace(
        start_ts=1000, end_ts=2000, duration_min=10, mode=0, result=1,
        stop_reason=0, start_mode=0, pre_type=0, md5="abc",
        area_mowed_m2=1.0, map_area_m2=100, dock=None, pref=(), region_status=(),
        faults=(), spot=(), ai_obstacle=(), obstacles=(), boundary=None,
        exclusions=(), trajectories=(), battery_samples=(), charging_status_samples=(),
        state_samples=(), error_samples=(), wifi_samples=(), charge_at_start=None,
        track_segments=track_segments, lawn_polygon=(),
    )


def test_legs_timeline_built_from_legs_meta():
    raw = {
        "_local_legs": [[[0.0, 0.0], [1.0, 0.0]], [[2.0, 0.0], [3.0, 0.0]]],
        "_legs_meta": [
            {"role": "mowing", "start_ts": 1000, "end_ts": 1100},
            {"role": "traversal", "start_ts": 1100, "end_ts": 1200},
        ],
    }
    entry = SimpleNamespace(md5="abc", filename="x.json", map_id=0)
    out = build_picked_session_summary(
        raw_dict=raw, summary=_make_summary(),
        entry=entry, picker_label="label",
    )
    assert out["legs_timeline"] == [
        {"role": "mowing",    "start_ts": 1000, "end_ts": 1100,
         "pts": [[0.0, 0.0], [1.0, 0.0]]},
        {"role": "traversal", "start_ts": 1100, "end_ts": 1200,
         "pts": [[2.0, 0.0], [3.0, 0.0]]},
    ]


def test_legs_timeline_omitted_for_legacy_archive():
    raw = {"_local_legs": [[[0.0, 0.0], [1.0, 0.0]]]}  # no _legs_meta
    entry = SimpleNamespace(md5="abc", filename="x.json", map_id=0)
    out = build_picked_session_summary(
        raw_dict=raw, summary=_make_summary(),
        entry=entry, picker_label="label",
    )
    assert out.get("legs_timeline") is None
