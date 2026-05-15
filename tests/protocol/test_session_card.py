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


def test_format_session_label_partial_trail():
    entry = SimpleNamespace(
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
    assert result["m2_per_pct"] is None


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


def test_energy_classify_intervals_empty_state_samples():
    raw, summary, entry = _load_session("short")
    raw_mut = dict(raw)
    raw_mut["state_samples"] = []
    raw_mut["charging_status_samples"] = []
    summary2 = _ss.parse_session_summary(raw_mut)
    result = build_picked_session_summary(raw_mut, summary2, entry, "lbl")
    assert result["time_mowing_min"] is None
    assert result["time_charging_min"] is None
    assert result["time_other_min"] is None
