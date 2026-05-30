"""Tests for non-mow session card handling.

Verifies that maintenance_run / manual_drive sessions suppress misleading
mow-stat fields and expose session_type / outcome / target_ids instead.
The mow path must remain unchanged (regression guard).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.dreame_a2_mower.session_card import (
    build_picked_session_summary,
    format_session_label,
)

FIXTURE_DIR = Path("tests/protocol/data/sessions")


def _make_entry(
    *,
    start_ts: int = 1717081740,
    end_ts: int = 1717083000,
    map_id: int = 0,
    area_mowed_m2: float = 0.0,
    duration_min: int = 21,
    local_trail_complete: bool = True,
    still_running: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        md5="abc123",
        filename="maint.json",
        map_id=map_id,
        start_ts=start_ts,
        end_ts=end_ts,
        duration_min=duration_min,
        area_mowed_m2=area_mowed_m2,
        local_trail_complete=local_trail_complete,
        still_running=still_running,
    )


def _make_raw(
    start_ts: int = 1717081740,
    end_ts: int = 1717083000,
    session_type: str = "maintenance_run",
    outcome: str | None = "arrived",
    target_ids: list | None = None,
    area_mowed_m2: float = 0.0,
) -> dict:
    """Build a minimal raw_dict that mimics what _inject_live_map_into_raw_dict writes."""
    raw: dict = {
        "start": start_ts,
        "end": end_ts,
        "time": 21,
        "areas": area_mowed_m2,
        "mapArea": 383,
        "md5": "abc123",
        "mode": 102,
        "preType": 0,
        "startMode": 0,
        "result": 1,
        "stop_reason": 0,
        "pref": [70, 0],
        "faults": [],
        "obstacles": [],
        "aiObstacle": [],
        "battery_samples": [],
        "charging_status_samples": [],
        "state_samples": [],
        "error_samples": [],
        "wifi_samples": [],
        "track": [],
        "session_type": session_type,
    }
    if outcome is not None:
        raw["outcome"] = outcome
    if target_ids is not None:
        raw["target_ids"] = target_ids
    return raw


# ---------------------------------------------------------------------------
# SessionSummary stub compatible with parse_session_summary
# ---------------------------------------------------------------------------

def _make_summary(
    start_ts: int = 1717081740,
    end_ts: int = 1717083000,
    area_mowed_m2: float = 0.0,
) -> SimpleNamespace:
    """Build a minimal SessionSummary-compatible namespace."""
    return SimpleNamespace(
        start_ts=start_ts,
        end_ts=end_ts,
        duration_min=21,
        area_mowed_m2=area_mowed_m2,
        map_area_m2=383,
        pref=[70, 0],
        mode=102,
        pre_type=0,
        start_mode=0,
        result=1,
        stop_reason=0,
        faults=[],
        obstacles=[],
        ai_obstacle=[],
        md5="abc123",
    )


# ===========================================================================
# FAILING TEST: non-mow card must carry type/outcome/targets and suppress stats
# ===========================================================================

class TestMaintenanceRunCard:
    """build_picked_session_summary for a maintenance_run entry."""

    def _build(self, outcome="arrived", target_ids=None):
        target_ids = target_ids or [2]
        raw = _make_raw(
            session_type="maintenance_run",
            outcome=outcome,
            target_ids=target_ids,
        )
        entry = _make_entry()
        summary = _make_summary()
        label = format_session_label(
            SimpleNamespace(
                start_ts=entry.start_ts,
                end_ts=entry.end_ts,
                map_id=entry.map_id,
                area_mowed_m2=0.0,
                duration_min=21,
                local_trail_complete=True,
                session_type="maintenance_run",
                outcome=outcome,
            )
        )
        return build_picked_session_summary(
            raw_dict=raw,
            summary=summary,
            entry=entry,
            picker_label=label,
        )

    def test_session_type_present(self):
        result = self._build()
        assert result["session_type"] == "maintenance_run"

    def test_outcome_present(self):
        result = self._build(outcome="arrived")
        assert result["outcome"] == "arrived"

    def test_outcome_could_not_reach(self):
        result = self._build(outcome="could_not_reach")
        assert result["outcome"] == "could_not_reach"

    def test_target_ids_present(self):
        result = self._build(target_ids=[2, 5])
        assert result["target_ids"] == [2, 5]

    def test_area_mowed_is_none_not_zero(self):
        """area_mowed_m2 must be None (not 0.0) so the card doesn't claim '0.0 m² mowed'."""
        result = self._build()
        assert result["area_mowed_m2"] is None, (
            f"Expected area_mowed_m2=None for maintenance_run, got {result['area_mowed_m2']!r}"
        )

    def test_coverage_pct_is_none(self):
        result = self._build()
        assert result["coverage_pct"] is None

    def test_m2_per_min_is_none(self):
        result = self._build()
        assert result["m2_per_min"] is None

    def test_m2_per_pct_is_none(self):
        result = self._build()
        assert result["m2_per_pct"] is None

    def test_mowing_time_breakdown_suppressed(self):
        """Mowing-time sub-breakdown fields must be None for non-mow runs."""
        result = self._build()
        assert result["time_mowing_min"] is None
        assert result["time_charging_min"] is None
        assert result["time_other_min"] is None

    def test_elapsed_min_still_present(self):
        """Duration/elapsed must still be present — the run did take time."""
        result = self._build()
        assert result["elapsed_min"] >= 0
        assert result["duration_min"] is not None

    def test_label_is_to_point(self):
        result = self._build(outcome="arrived")
        assert result["label"].startswith("[To Point]")


class TestManualDriveCard:
    """build_picked_session_summary for a manual_drive entry."""

    def _build(self):
        raw = _make_raw(session_type="manual_drive", outcome=None, target_ids=None)
        entry = _make_entry()
        summary = _make_summary()
        label = format_session_label(
            SimpleNamespace(
                start_ts=entry.start_ts,
                end_ts=entry.end_ts,
                map_id=entry.map_id,
                area_mowed_m2=0.0,
                duration_min=21,
                local_trail_complete=True,
                session_type="manual_drive",
            )
        )
        return build_picked_session_summary(
            raw_dict=raw,
            summary=summary,
            entry=entry,
            picker_label=label,
        )

    def test_session_type_present(self):
        result = self._build()
        assert result["session_type"] == "manual_drive"

    def test_area_mowed_is_none(self):
        result = self._build()
        assert result["area_mowed_m2"] is None

    def test_outcome_absent_for_manual_drive(self):
        """manual_drive has no outcome field in raw; card should have None or absent."""
        result = self._build()
        # outcome key may be absent OR None — either is acceptable
        assert result.get("outcome") is None

    def test_label_is_manual(self):
        result = self._build()
        assert result["label"].startswith("[Manual]")


# ===========================================================================
# Regression: mow session card is UNCHANGED
# ===========================================================================

class TestMowCardUnchanged:
    """Mow session card must be identical to current behaviour."""

    def _build(self):
        raw = json.loads((FIXTURE_DIR / "short.json").read_text())
        # short.json is a mow session — no session_type key → defaults to "mow"
        from custom_components.dreame_a2_mower.protocol.session_summary import (
            parse_session_summary,
        )
        entry = SimpleNamespace(
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
        summary = parse_session_summary(raw)
        label = format_session_label(entry)
        return build_picked_session_summary(
            raw_dict=raw,
            summary=summary,
            entry=entry,
            picker_label=label,
        )

    def test_area_mowed_is_numeric(self):
        result = self._build()
        assert isinstance(result["area_mowed_m2"], float)
        assert result["area_mowed_m2"] > 0

    def test_coverage_pct_is_numeric(self):
        result = self._build()
        assert result["coverage_pct"] is not None

    def test_m2_per_min_is_numeric(self):
        result = self._build()
        assert result["m2_per_min"] is not None

    def test_session_type_is_mow(self):
        result = self._build()
        # mow sessions get session_type="mow" in the output
        assert result["session_type"] == "mow"

    def test_outcome_is_none(self):
        result = self._build()
        assert result.get("outcome") is None

    def test_mowing_time_breakdown_present(self):
        result = self._build()
        # time_mowing_min should be an int (not None) for mow sessions
        assert result["time_mowing_min"] is not None
