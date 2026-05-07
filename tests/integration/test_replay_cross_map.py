"""Replay test: picking a session from inactive map renders against session.map_id.

Tests:
  - cached_map_png defaults to the active map's PNG.
  - Setting _render_map_id to another map serves that map's PNG instead.
  - _resolve_finalize_map_id resolves correctly in all three cases.
  - ArchivedSession.map_id round-trips through to_dict/from_dict.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.archive.session import ArchivedSession
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.live_map.state import LiveMapState
from custom_components.dreame_a2_mower.observability import (
    FreshnessTracker,
    NovelObservationRegistry,
)


def _make_coord_with_two_maps():
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._prev_task_state = None
    coord._prev_in_dock = None
    coord.novel_registry = NovelObservationRegistry()
    coord.freshness = FreshnessTracker()
    map0, map1 = MagicMock(map_id=0, md5="aaa"), MagicMock(map_id=1, md5="bbb")
    coord._cached_maps_by_id = {0: map0, 1: map1}
    coord._cached_pngs_by_id = {0: b"png-map-0", 1: b"png-map-1"}
    coord._last_map_md5_by_id = {0: "aaa", 1: "bbb"}
    coord._active_map_id = 0
    coord._render_map_id = None
    coord._lifecycle_event = None
    coord._alert_event = None
    return coord


def test_render_map_id_defaults_to_active():
    """Without a replay override, cached_map_png serves the active map."""
    coord = _make_coord_with_two_maps()
    assert coord.cached_map_png == b"png-map-0"


def test_render_map_id_override_serves_other_map_png():
    """Setting _render_map_id to 1 makes cached_map_png serve map 1's PNG."""
    coord = _make_coord_with_two_maps()
    coord._render_map_id = 1
    assert coord.cached_map_png == b"png-map-1"


def test_resolve_finalize_map_id_uses_active_map():
    """_resolve_finalize_map_id returns _active_map_id when set."""
    coord = _make_coord_with_two_maps()
    coord._active_map_id = 1
    assert coord._resolve_finalize_map_id() == 1


def test_resolve_finalize_map_id_falls_back_to_lowest_cached():
    """When _active_map_id is None, returns the lowest cached map id."""
    coord = _make_coord_with_two_maps()
    coord._active_map_id = None
    assert coord._resolve_finalize_map_id() == 0


def test_resolve_finalize_map_id_sentinel_when_empty():
    """When no maps are cached and _active_map_id is None, returns -1."""
    coord = _make_coord_with_two_maps()
    coord._active_map_id = None
    coord._cached_maps_by_id = {}
    assert coord._resolve_finalize_map_id() == -1


def test_archived_session_map_id_round_trips():
    """map_id is preserved through to_dict / from_dict."""
    s = ArchivedSession(
        filename="session.json",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
        md5="abc123",
        map_id=1,
    )
    d = s.to_dict()
    assert d["map_id"] == 1
    s2 = ArchivedSession.from_dict(d)
    assert s2.map_id == 1


def test_archived_session_legacy_map_id_defaults_to_minus_one():
    """Legacy index.json entries without map_id default to -1."""
    s = ArchivedSession.from_dict({
        "filename": "old.json",
        "start_ts": 1_700_000_000,
        "end_ts": 1_700_003_600,
        "duration_min": 60,
        "area_mowed_m2": 80.0,
        "map_area_m2": 4000,
        "md5": "abc123",
        # no map_id key
    })
    assert s.map_id == -1


def test_from_summary_accepts_map_id():
    """from_summary() stamps the supplied map_id on the entry."""
    import types
    summary = types.SimpleNamespace(
        md5="sum123",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
    )
    s = ArchivedSession.from_summary("x.json", summary, map_id=2)
    assert s.map_id == 2


def test_from_summary_defaults_map_id_to_minus_one():
    """from_summary() defaults map_id to -1 when not supplied."""
    import types
    summary = types.SimpleNamespace(
        md5="sum456",
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duration_min=60,
        area_mowed_m2=80.0,
        map_area_m2=4000,
    )
    s = ArchivedSession.from_summary("y.json", summary)
    assert s.map_id == -1
