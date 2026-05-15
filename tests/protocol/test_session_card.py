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
