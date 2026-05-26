"""Integration tests for sensor.dreame_a2_mower_picked_session wiring."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.session_card import (
    build_picked_session_summary,
    format_session_label,
)

FIXTURE_DIR = Path("tests/protocol/data/sessions")


def _make_entry_from_raw(raw: dict) -> SimpleNamespace:
    """Build an ArchivedSession-like namespace from fixture JSON."""
    return SimpleNamespace(
        md5=raw["md5"],
        filename="short.json",
        map_id=0,
        end_ts=raw["end"],
        start_ts=raw["start"],
        duration_min=raw["time"],
        area_mowed_m2=raw["areas"],
        local_trail_complete=True,
        still_running=False,
    )


# ---------------------------------------------------------------------------
# Unit-level wiring test: call build_picked_session_summary directly so we
# verify the builder + format_session_label contract without HA/PIL deps.
# ---------------------------------------------------------------------------

def test_build_picked_session_summary_populates_all_required_keys():
    """build_picked_session_summary returns a dict with the expected keys."""
    raw = json.loads((FIXTURE_DIR / "short.json").read_text())
    entry = _make_entry_from_raw(raw)

    from custom_components.dreame_a2_mower.protocol.session_summary import (
        parse_session_summary,
    )

    summary = parse_session_summary(raw)
    picker_label = format_session_label(entry)

    result = build_picked_session_summary(
        raw_dict=raw,
        summary=summary,
        entry=entry,
        picker_label=picker_label,
    )

    assert result["filename"] == "short.json"
    assert result["label"].startswith("[Mowing]")
    assert "duration_min" in result
    assert "area_mowed_m2" in result
    assert result["md5"] == raw["md5"]


# ---------------------------------------------------------------------------
# Coordinator-wiring test: call render_work_log_session and verify that
# _picked_session_summary is set on the coordinator.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_render_work_log_session_populates_picked_summary():
    """render_work_log_session populates coord._picked_session_summary."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from custom_components.dreame_a2_mower.observability import (
        FreshnessTracker,
        NovelObservationRegistry,
    )

    raw = json.loads((FIXTURE_DIR / "short.json").read_text())
    entry = _make_entry_from_raw(raw)

    # Build a minimal coordinator via object.__new__ (same pattern as
    # _make_coordinator_for_session_tests in test_coordinator.py).
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._picked_session_summary = None
    coord.cloud_state = MagicMock()
    coord.cloud_state.maps_by_id = {0: SimpleNamespace()}
    coord._active_map_id = 0

    # Stub the session_archive so list_sessions + load return our fixture.
    coord.session_archive = MagicMock()
    coord.session_archive.list_sessions = MagicMock(return_value=[entry])
    coord.session_archive.load = MagicMock(return_value=raw)

    # Stub hass.async_add_executor_job so sync callables run inline.
    async def _exec_job(fn, *args):
        return fn(*args)

    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = _exec_job

    # Stub render_work_log so we don't need PIL in this test.
    import custom_components.dreame_a2_mower.coordinator._session as sess_mod

    _original_render_work_log = None
    import custom_components.dreame_a2_mower.map_render as map_render_mod

    _original = map_render_mod.render_work_log
    map_render_mod.render_work_log = lambda *a, **k: b"png"

    try:
        await coord.render_work_log_session("short.json")
    finally:
        map_render_mod.render_work_log = _original

    assert coord._picked_session_summary is not None, (
        "_picked_session_summary should be set after render_work_log_session"
    )
    assert coord._picked_session_summary["filename"] == "short.json"
    assert coord._picked_session_summary["label"].startswith("[Mowing]")
    assert "duration_min" in coord._picked_session_summary


@pytest.mark.asyncio
async def test_placeholder_pick_clears_picked_summary():
    """Picking the placeholder clears both _work_log_png and _picked_session_summary."""
    from custom_components.dreame_a2_mower.const import WORK_LOG_PLACEHOLDER

    # Build a minimal coordinator with the required state.
    coord = MagicMock()
    coord._work_log_png = b"old png"
    coord._picked_session_summary = {"label": "old", "md5": "abc"}
    coord.async_update_listeners = MagicMock()

    # Manually create and configure the select entity to avoid __init__ complexity.
    from custom_components.dreame_a2_mower.select import DreameA2WorkLogSelect
    sel = object.__new__(DreameA2WorkLogSelect)
    sel.coordinator = coord
    sel._placeholder = WORK_LOG_PLACEHOLDER
    sel._attr_current_option = "some_session"
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option(WORK_LOG_PLACEHOLDER)

    assert coord._work_log_png is None
    assert coord._picked_session_summary is None


def test_picked_session_sensor_reflects_coordinator_summary():
    from custom_components.dreame_a2_mower.sensor import DreameA2PickedSessionSensor
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._picked_session_summary = None

    sensor = object.__new__(DreameA2PickedSessionSensor)
    sensor.coordinator = coord

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}

    coord._picked_session_summary = {
        "label": "[Mowing] [Map 1] 2026-05-13 14:00 — 285.3 m² / 278min",
        "duration_min": 278,
    }
    assert sensor.native_value == coord._picked_session_summary["label"]
    assert sensor.extra_state_attributes["duration_min"] == 278


@pytest.mark.asyncio
async def test_render_work_log_session_hydrate_writes_cloud_state():
    """When the map cache is empty, the last-resort live fetch must hydrate
    cloud_state.maps_by_id (not a private shadow) so later replays reuse it."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.mower.state import MowerState
    from custom_components.dreame_a2_mower.live_map.state import LiveMapState
    from tests.integration.conftest import make_empty_cloud_state
    import custom_components.dreame_a2_mower.map_render as map_render_mod
    import custom_components.dreame_a2_mower.map_decoder as map_decoder_mod

    raw = json.loads((FIXTURE_DIR / "short.json").read_text())
    entry = _make_entry_from_raw(raw)

    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState()
    coord.live_map = LiveMapState()
    coord._picked_session_summary = None
    coord.cloud_state = make_empty_cloud_state()  # maps_by_id == {}
    coord._active_map_id = 0

    coord._cloud = MagicMock()
    coord._cloud.fetch_map.return_value = {0: {"mapIndex": 0}}  # non-None
    coord.session_archive = MagicMock()
    coord.session_archive.list_sessions = MagicMock(return_value=[entry])
    coord.session_archive.load = MagicMock(return_value=raw)

    async def _exec(fn, *a):
        return fn(*a)

    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = _exec

    fetched_map = SimpleNamespace()  # stand-in MapData; identity-checked below
    orig_render = map_render_mod.render_work_log
    orig_parse = map_decoder_mod.parse_cloud_map
    map_render_mod.render_work_log = lambda *a, **k: b"png"
    map_decoder_mod.parse_cloud_map = lambda *a, **k: fetched_map
    try:
        await coord.render_work_log_session("short.json")
    finally:
        map_render_mod.render_work_log = orig_render
        map_decoder_mod.parse_cloud_map = orig_parse

    assert coord.cloud_state.maps_by_id.get(0) is fetched_map


# ---------------------------------------------------------------------------
# Characterization test — pins the FULL output of build_picked_session_summary
# against short.json BEFORE the T3 refactor.  Any behaviour change in any
# section will cause this test to fail.
# ---------------------------------------------------------------------------

def test_build_picked_session_summary_characterization():
    """Characterization: pin every output key + value of build_picked_session_summary.

    Uses the scalar+structure form (preferred when list fields are large):
      (a) full key set matches exactly,
      (b) every scalar / derived key equals its captured value,
      (c) len() + first & last element checked for every list field.

    T3 (split refactor) must keep this test passing byte-for-byte.
    """
    from custom_components.dreame_a2_mower.protocol.session_summary import (
        parse_session_summary,
    )

    raw = json.loads((FIXTURE_DIR / "short.json").read_text())
    entry = _make_entry_from_raw(raw)
    summary = parse_session_summary(raw)
    result = build_picked_session_summary(
        raw_dict=raw,
        summary=summary,
        entry=entry,
        picker_label=format_session_label(entry),
    )

    # ------------------------------------------------------------------ (a)
    assert set(result) == {
        "ai_obstacle_count",
        "area_mowed_m2",
        "base_map_image_url",
        "base_map_image_url_no_trail",
        "battery_samples",
        "charge_at_end_pct",
        "charge_at_start_pct",
        "charge_min_pct",
        "charge_net_delta_pct",
        "charge_recovered_pct",
        "charge_used_pct",
        "completed",
        "coverage_pct",
        "distance_m",
        "duration_min",
        "elapsed_min",
        "ended_at",
        "ended_at_unix",
        "error_codes_seen",
        "error_event_count",
        "fault_count",
        "faults_compact",
        "filename",
        "label",
        "legs",
        "legs_timeline",
        "local_leg_count",
        "m2_per_min",
        "m2_per_pct",
        "map_area_m2",
        "map_id",
        "map_projection",
        "md5",
        "mode_label",
        "mode_raw",
        "mowing_efficiency_label",
        "mowing_efficiency_raw",
        "mowing_height_mm",
        "mowing_legs",
        "obstacle_count",
        "pre_type_label",
        "pre_type_raw",
        "recharge_count",
        "result_label",
        "result_raw",
        "settings_snapshot",
        "start_mode_label",
        "start_mode_raw",
        "started_at",
        "started_at_unix",
        "state_samples",
        "state_transition_count",
        "stop_reason_label",
        "stop_reason_raw",
        "time_charging_min",
        "time_mowing_min",
        "time_other_min",
        "time_rain_protection_min",
        "traversal_legs",
        "wifi_rssi_avg_dbm",
        "wifi_rssi_max_dbm",
        "wifi_rssi_min_dbm",
        "wifi_sample_count",
        "wifi_samples",
    }

    # ------------------------------------------------------------------ (b)  scalar / derived keys
    assert result["filename"] == "short.json"
    assert result["md5"] == "7bff1b022fca3862c92183f7e9028d25"
    assert result["map_id"] == 0
    assert result["label"] == "[Mowing] [Map 1] 2026-04-26 21:49 — 8.9 m² / 8min"
    assert result["started_at_unix"] == 1777232958
    assert result["ended_at_unix"] == 1777233426
    assert result["started_at"] == "2026-04-26 21:49"
    assert result["ended_at"] == "2026-04-26 21:57"
    assert result["duration_min"] == 8
    assert result["elapsed_min"] == 7
    assert result["mode_raw"] == 103
    assert result["mode_label"] == "raw=103"
    assert result["pre_type_raw"] == 0
    assert result["pre_type_label"] == "Default"
    assert result["start_mode_raw"] == 0
    assert result["start_mode_label"] == "Schedule"
    assert result["result_raw"] == 1
    assert result["result_label"] == "Completed"
    assert result["stop_reason_raw"] == -1
    assert result["stop_reason_label"] == "Natural end"
    assert result["completed"] is True

    assert result["area_mowed_m2"] == 8.91
    assert result["map_area_m2"] == 383
    assert abs(result["coverage_pct"] - 2.3263707571801566) < 1e-9
    assert result["mowing_height_mm"] == 70
    assert result["mowing_efficiency_raw"] == 0
    assert result["mowing_efficiency_label"] == "Eco"
    assert abs(result["distance_m"] - 57.40388569677329) < 1e-9
    assert abs(result["m2_per_min"] - 1.11375) < 1e-9
    assert abs(result["m2_per_pct"] - 1.11375) < 1e-9

    assert result["charge_at_start_pct"] == 100
    assert result["charge_at_end_pct"] == 91
    assert result["charge_min_pct"] == 91
    assert result["charge_used_pct"] == 8
    assert result["charge_recovered_pct"] == 0
    assert result["charge_net_delta_pct"] == 9
    assert result["recharge_count"] == 0

    assert result["time_mowing_min"] == 7
    assert result["time_charging_min"] == 0
    assert result["time_rain_protection_min"] == 0
    assert result["time_other_min"] == 0

    assert result["fault_count"] == 0
    assert result["obstacle_count"] == 0
    assert result["ai_obstacle_count"] == 0
    assert result["state_transition_count"] == 1
    assert result["error_event_count"] == 1

    assert result["wifi_rssi_min_dbm"] == -70
    assert result["wifi_rssi_max_dbm"] == -58
    assert result["wifi_rssi_avg_dbm"] == -66
    assert result["wifi_sample_count"] == 54

    assert result["local_leg_count"] == 1
    # legs_timeline (v1.0.19a5+ diff-derived chronological order): the
    # spot mow walks dock-out (traversal) → spot mowing (mowing) in real
    # time order, with the boundary point repeated so the polylines touch
    # without a gap. 2 records total. Pre-v1.0.19a5 this archive (no
    # _legs_meta) reported None.
    assert isinstance(result["legs_timeline"], list)
    assert len(result["legs_timeline"]) == 2
    assert result["legs_timeline"][0]["role"] == "traversal"
    assert result["legs_timeline"][0]["pts"][0] == [0.18, -0.07]  # at the dock
    assert result["legs_timeline"][1]["role"] == "mowing"
    assert result["legs_timeline"][1]["pts"][-1] == [-3.47, -5.06]  # last point in spot
    assert result["map_projection"] is None
    assert result["base_map_image_url"] == "/api/dreame_a2_mower/work_log.png?ts=1777232958"
    assert result["base_map_image_url_no_trail"] == (
        "/api/dreame_a2_mower/work_log.png?ts=1777232958&trail=false"
    )

    assert result["settings_snapshot"] == {
        "version": 0,
        "per_map": {},
        "device_wide": {},
        "peripheral": {},
        "forensic": {},
    }

    # ------------------------------------------------------------------ (c)  list fields
    # battery_samples
    assert len(result["battery_samples"]) == 9
    assert result["battery_samples"][0] == [1777233012, 99]
    assert result["battery_samples"][-1] == [1777233391, 91]

    # state_samples
    assert len(result["state_samples"]) == 1
    assert result["state_samples"][0] == [1777232960, 1]

    # wifi_samples
    assert len(result["wifi_samples"]) == 54
    assert result["wifi_samples"][0] == [0.2, -0.05, -65, 1777232959]
    assert result["wifi_samples"][-1] == [-2.62, -5.2, -63, 1777233391]

    # error_codes_seen
    assert len(result["error_codes_seen"]) == 1
    assert result["error_codes_seen"][0] == 50

    # faults_compact
    assert len(result["faults_compact"]) == 0

    # legs: union of local+cloud. short.json is a spot mow (mode 103) with
    # 1 local leg + 1 cloud leg from spot[0].track. The spot-track surfacing
    # was added 2026-05-26 (SpotLayer + track_segments spot-mode fallback —
    # see protocol.session_summary). Pre-fix this archive showed 1/0.
    assert len(result["legs"]) == 2
    assert result["local_leg_count"] == 1
    assert result["legs"][0][0] == [0.18, -0.07]   # local leg, first point
    assert result["legs"][0][-1] == [-3.47, -5.06]  # local leg, last point
    assert result["legs"][1][0] == [-0.73, -2.86]   # cloud spot[0].track, first
    assert result["legs"][1][-1] == [-3.54, -4.97]  # cloud spot[0].track, last

    # mowing_legs / traversal_legs (v1.0.19a4+ OSS-diff path):
    #   - mowing_legs = cloud's spot[N].track (canonical blades-down path)
    #   - traversal_legs = local points NOT covered by cloud polyline,
    #     here just the 3-point dock-out cruise. The dock-return arc isn't
    #     in this fixture (the local capture ends inside the mow area).
    # Pre-fix this archive (no _mowing_legs / no cloud spot.track) reported
    # 0/0 for both, leaving the JS card to paint the union in one colour.
    assert len(result["mowing_legs"]) == 1  # cloud spot.track surfaced
    assert len(result["traversal_legs"]) == 1  # dock-out cruise
    # Spot-check the traversal segment's endpoints: starts near the dock
    # (~0.2, -0.1) and walks south toward the spot area at (~-3, -4).
    assert result["traversal_legs"][0][0] == [0.18, -0.07]
    assert result["traversal_legs"][0][-1] == [-0.23, -2.22]
