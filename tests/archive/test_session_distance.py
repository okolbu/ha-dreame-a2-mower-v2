"""ArchivedSession persists session_distance_m across to_dict/from_dict."""
from __future__ import annotations


def test_archived_session_carries_distance():
    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    entry = ArchivedSession(
        filename="s.json", start_ts=1, end_ts=2, duration_min=3,
        area_mowed_m2=4.0, map_area_m2=5, md5="a",
        session_distance_m=42.5,
    )
    d = entry.to_dict()
    assert d["session_distance_m"] == 42.5
    roundtrip = ArchivedSession.from_dict(d)
    assert roundtrip.session_distance_m == 42.5


def test_archived_session_legacy_entry_defaults_to_zero():
    """Legacy index.json entries without session_distance_m parse cleanly."""
    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    legacy = {
        "filename": "s.json", "start_ts": 1, "end_ts": 2, "duration_min": 3,
        "area_mowed_m2": 4.0, "map_area_m2": 5, "md5": "a", "map_id": 0,
    }
    entry = ArchivedSession.from_dict(legacy)
    assert entry.session_distance_m == 0.0


def test_from_summary_pulls_distance():
    """ArchivedSession.from_summary reads session_distance_m off the summary."""
    from types import SimpleNamespace
    from custom_components.dreame_a2_mower.archive.session import ArchivedSession
    summary = SimpleNamespace(
        start_ts=1, end_ts=2, duration_min=3, area_mowed_m2=4.0,
        map_area_m2=5, md5="a", session_distance_m=99.9,
    )
    e = ArchivedSession.from_summary("s.json", summary, map_id=0)
    assert e.session_distance_m == 99.9
