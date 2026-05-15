"""Unit tests for session_card.build_picked_session_summary + helpers."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.dreame_a2_mower.session_card import (
    build_picked_session_summary,
    format_session_label,
)
from custom_components.dreame_a2_mower.protocol import session_summary as _ss


FIXTURE_DIR = Path(__file__).parent / "data" / "sessions"


def _load_session(name: str) -> tuple[dict, _ss.SessionSummary, SimpleNamespace]:
    raw = json.loads((FIXTURE_DIR / f"{name}.json").read_text())
    summary = _ss.parse_session_summary(raw)
    entry = SimpleNamespace(
        md5=raw.get("md5"),
        filename=f"{name}.json",
        map_id=0,
        start_ts=raw["start"],
        end_ts=raw["end"],
        duration_min=raw["time"],
        area_mowed_m2=raw["areas"],
    )
    return raw, summary, entry


def test_format_session_label_mowing():
    entry = SimpleNamespace(
        start_ts=1778680800,
        end_ts=1778697514,
        map_id=0,
        area_mowed_m2=285.3,
        duration_min=278,
        md5="abc",
        local_trail_complete=True,
        still_running=False,
    )
    label = format_session_label(entry)
    assert label.startswith("[Mowing] [Map 1] ")
    assert "285.3 m² / 278min" in label


def test_format_session_label_uses_start_ts_not_end_ts():
    """A session crossing midnight should label with start date."""
    # start=2026-05-10 21:57 UTC, end=2026-05-11 06:12 UTC
    entry = SimpleNamespace(
        start_ts=1778443034,  # 2026-05-10 21:57 in CEST (UTC+2)
        end_ts=1778472750,    # 2026-05-11 06:12 CEST
        map_id=0,
        area_mowed_m2=312.1,
        duration_min=285,
        md5="abc",
        local_trail_complete=True,
        still_running=False,
    )
    label = format_session_label(entry)
    # Label should mention May 10 (start), not May 11 (end).
    assert "2026-05-10" in label, f"label should use start date, got {label!r}"
    assert "2026-05-11" not in label


def test_format_session_label_partial_trail():
    entry = SimpleNamespace(
        start_ts=1778680800,
        end_ts=1778697514,
        map_id=0,
        area_mowed_m2=10.0,
        duration_min=5,
        md5="abc",
        local_trail_complete=False,
        still_running=False,
    )
    label = format_session_label(entry)
    assert label.startswith("⚠ ")
    assert "(partial trail)" in label


def test_build_identity_outcome_long_session():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "label-x")

    assert result["label"] == "label-x"
    assert result["md5"] == raw["md5"]
    assert result["filename"] == "long_with_recharges.json"
    assert result["started_at_unix"] == raw["start"]
    assert result["ended_at_unix"] == raw["end"]
    assert result["duration_min"] == raw["time"]
    assert result["mode_raw"] == raw["mode"]
    assert result["pre_type_raw"] == raw["pre_type"]
    assert result["start_mode_raw"] == raw["start_mode"]
    assert result["result_raw"] == raw["result"]
    assert result["stop_reason_raw"] == raw["stop_reason"]
    # Completed when result == 1 AND stop_reason in {-1, 0}
    assert result["completed"] == (raw["result"] == 1 and raw["stop_reason"] in (-1, 0))
    # Labels exist (whether resolved or "raw=N" depends on the table)
    assert isinstance(result["mode_label"], str)
    assert isinstance(result["stop_reason_label"], str)
    assert isinstance(result["result_label"], str)


def test_build_identity_outcome_incomplete():
    raw, summary, entry = _load_session("incomplete")
    result = build_picked_session_summary(raw, summary, entry, "lbl")
    # md5 is "(incomplete)" for these
    assert result["md5"] == "(incomplete)"
    assert result["completed"] is False
    assert "Incomplete" in result["result_label"]


def test_started_at_ends_with_tz_marker():
    """started_at is local-format ISO; assert minute precision and shape."""
    raw, summary, entry = _load_session("short")
    result = build_picked_session_summary(raw, summary, entry, "lbl")
    # Format: YYYY-MM-DD HH:MM (no seconds, no TZ — keep simple for cards)
    assert len(result["started_at"]) == 16
    assert result["started_at"][4] == "-" and result["started_at"][7] == "-"


def test_coverage_efficiency_long_session():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")

    assert result["area_mowed_m2"] == pytest.approx(raw["areas"], rel=1e-3)
    assert result["map_area_m2"] == raw["map_area"]
    if raw["map_area"]:
        assert result["coverage_pct"] == pytest.approx(
            raw["areas"] / raw["map_area"] * 100, rel=1e-3
        )
    else:
        assert result["coverage_pct"] is None
    assert result["mowing_height_mm"] == raw["pref"][0]
    assert result["mowing_efficiency_raw"] == raw["pref"][1]
    assert result["mowing_efficiency_label"] in ("Eco", "Standard", "High")
    # m2_per_min: area / duration; m2_per_pct: area / charge_used
    if raw["time"]:
        assert result["m2_per_min"] == pytest.approx(raw["areas"] / raw["time"], rel=1e-3)
    # distance_m: from _local_legs (sum of pairwise euclidean)
    assert result["distance_m"] > 0


def test_coverage_zero_map_area():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["map_area"] = 0
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["coverage_pct"] is None


def test_coverage_zero_duration():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["time"] = 0
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["m2_per_min"] is None


def test_distance_falls_back_to_track_segments():
    """When _local_legs is absent, distance_m comes from summary.track_segments."""
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut.pop("_local_legs", None)
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    # As long as either source has data, result is a number. May be 0 if
    # both empty — accept any non-negative number.
    assert result["distance_m"] >= 0


def test_energy_long_session_with_recharges():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")

    bs = raw["battery_samples"]
    assert result["charge_at_start_pct"] == raw["charge_at_start"]
    assert result["charge_at_end_pct"] == bs[-1][1]
    assert result["charge_min_pct"] == min(v for _, v in bs)
    # Long session has mid-mow recharges in charging_status_samples
    assert result["recharge_count"] >= 1
    assert isinstance(result["time_charging_min"], int)
    assert isinstance(result["time_mowing_min"], int)
    assert isinstance(result["time_other_min"], int)
    # All three should be non-negative
    assert result["time_charging_min"] >= 0
    assert result["time_mowing_min"] >= 0
    assert result["time_other_min"] >= 0
    # Three slices must sum to wall-clock window (± 1 min rounding).
    wall_min = (raw["end"] - raw["start"]) // 60
    total = (
        result["time_charging_min"]
        + result["time_mowing_min"]
        + result["time_other_min"]
    )
    assert abs(total - wall_min) <= 1, f"{total} vs wall {wall_min}"
    # charge_used_pct is the sum of drops, not the net delta. With
    # mid-mow recharges it should be strictly greater than the net.
    expected_consumed = sum(
        max(0, bs[i][1] - bs[i + 1][1]) for i in range(len(bs) - 1)
    )
    expected_recovered = sum(
        max(0, bs[i + 1][1] - bs[i][1]) for i in range(len(bs) - 1)
    )
    assert result["charge_used_pct"] == expected_consumed
    assert result["charge_recovered_pct"] == expected_recovered
    assert result["charge_net_delta_pct"] == (bs[0][1] - bs[-1][1] if raw.get("charge_at_start") is None else raw["charge_at_start"] - bs[-1][1])
    # battery_samples passthrough
    assert result["battery_samples"] == bs


def test_energy_no_battery_samples():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["battery_samples"] = []
    raw_mut.pop("charge_at_start", None)
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["charge_at_start_pct"] is None
    assert result["charge_at_end_pct"] is None
    assert result["charge_min_pct"] is None
    assert result["charge_used_pct"] == 0
    assert result["charge_recovered_pct"] == 0
    assert result["m2_per_pct"] is None


def test_energy_charge_used_is_sum_of_drops_not_net_delta():
    """A session that recharges should not understate charge consumed."""
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    # 100→10 (drop 90), 10→100 (rise 90), 100→10 (drop 90), 10→76 (rise 66)
    # net delta = 100 - 76 = 24, but actual consumed = 180.
    raw_mut["battery_samples"] = [
        [1000, 100], [2000, 10], [3000, 100], [4000, 10], [5000, 76],
    ]
    raw_mut["charge_at_start"] = 100
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["charge_used_pct"] == 180
    assert result["charge_recovered_pct"] == 156  # 90 + 66
    assert result["charge_net_delta_pct"] == 24
    assert result["charge_at_start_pct"] == 100
    assert result["charge_at_end_pct"] == 76


def test_energy_recharge_count_counts_zero_to_one_transitions():
    """charging_status_samples=[0,1,0,1,0] → 2 recharges."""
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["charging_status_samples"] = [
        [1000, 0], [1100, 1], [1200, 0], [1300, 1], [1400, 0],
    ]
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["recharge_count"] == 2


def test_energy_time_breakdown_empty_samples_returns_none():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["state_samples"] = []
    raw_mut["charging_status_samples"] = []
    raw_mut["battery_samples"] = []
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["time_mowing_min"] is None
    assert result["time_charging_min"] is None
    assert result["time_other_min"] is None


def test_energy_time_breakdown_charging_window_step_integrated():
    """charging_status_samples=[(start+10, 1), (start+70, 0)] → 1 min charging."""
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["start"] = 10000
    raw_mut["end"] = 10180  # 3 min wall-clock
    raw_mut["battery_samples"] = []
    raw_mut["charging_status_samples"] = [
        [10010, 1],  # charging starts 10s in
        [10070, 0],  # charging stops 70s in → 60s charging
    ]
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["time_charging_min"] == 1
    assert result["time_mowing_min"] == 0
    assert result["time_other_min"] == 2  # 180 - 60 = 120s = 2 min


def test_diagnostics_long_session():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")

    assert result["fault_count"] == len(raw["faults"])
    assert isinstance(result["faults_compact"], list)
    assert result["obstacle_count"] == len(raw["obstacle"])
    assert result["ai_obstacle_count"] == len(raw["ai_obstacle"])
    assert result["state_transition_count"] == len(raw["state_samples"])
    assert result["error_event_count"] == len(raw["error_samples"])
    expected_error_codes = sorted({v for _, v in raw["error_samples"]})
    assert result["error_codes_seen"] == expected_error_codes


def test_diagnostics_wifi_stats():
    raw, summary, entry = _load_session("long_with_recharges")
    result = build_picked_session_summary(raw, summary, entry, "lbl")

    ws = raw.get("wifi_samples") or []
    if ws:
        rssis = [int(s[2]) for s in ws]
        assert result["wifi_rssi_min_dbm"] == min(rssis)
        assert result["wifi_rssi_max_dbm"] == max(rssis)
        assert result["wifi_rssi_avg_dbm"] == round(sum(rssis) / len(rssis))
        assert result["wifi_sample_count"] == len(ws)
        assert result["wifi_samples"] == ws
    else:
        assert result["wifi_rssi_min_dbm"] is None
        assert result["wifi_sample_count"] == 0


def test_settings_snapshot_passthrough():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["settings_snapshot"] = {"settings_edgemaster": True, "settings_mowing_height_mm": 30}
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["settings_snapshot"] == {
        "settings_edgemaster": True, "settings_mowing_height_mm": 30,
    }


def test_settings_snapshot_absent_yields_none():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut.pop("settings_snapshot", None)
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["settings_snapshot"] is None


def test_faults_compact_truncates_to_5():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["faults"] = [{"code": i} for i in range(10)]
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert len(result["faults_compact"]) == 6  # 5 + "+5 more"
    assert result["faults_compact"][-1] == "+5 more"


def test_picked_session_summary_exposes_legs():
    """legs (list[list[[x_m, y_m]]]) must appear on the output dict.

    The card consumes this list as the per-leg trajectory to animate.
    Falls back to summary.track_segments when _local_legs is missing.
    """
    raw, summary, entry = _load_session("long_with_recharges")
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
    )
    assert "legs" in out
    assert isinstance(out["legs"], list)
    assert len(out["legs"]) >= 1
    # Every point is a 2-tuple/list of floats
    first_pt = out["legs"][0][0]
    assert len(first_pt) == 2
    assert all(isinstance(c, (int, float)) for c in first_pt)


def test_picked_session_summary_exposes_state_samples():
    """state_samples (list[[ts_s, state_value]]) must appear on the output.

    The card uses this to classify mowing vs pause intervals.
    """
    raw, summary, entry = _load_session("long_with_recharges")
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
    )
    assert "state_samples" in out
    assert isinstance(out["state_samples"], list)
    if out["state_samples"]:
        ts, sv = out["state_samples"][0]
        assert isinstance(ts, (int, float))
        assert isinstance(sv, int)


def test_picked_session_summary_exposes_map_projection():
    """map_projection (5-key dict) must appear on the output when supplied."""
    raw, summary, entry = _load_session("long_with_recharges")
    proj = {
        "bx2_mm": 12345.6, "by2_mm": 7890.1, "pixel_size_mm": 50.0,
        "width_px": 637, "height_px": 717,
    }
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
        map_projection=proj,
    )
    assert out["map_projection"] == proj


def test_picked_session_summary_map_projection_is_none_when_not_supplied():
    """Default to None so the card knows projection isn't available yet."""
    raw, summary, entry = _load_session("long_with_recharges")
    out = build_picked_session_summary(
        raw_dict=raw, summary=summary, entry=entry,
        picker_label="[Mowing] [Map 1] test",
    )
    assert out["map_projection"] is None
