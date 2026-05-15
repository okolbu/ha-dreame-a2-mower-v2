"""Picked-session summary builder.

Pure derivation: takes a raw archive dict + parsed SessionSummary +
ArchivedSession-like metadata, returns a flat dict of attributes the
dashboard cards consume. No HA / coordinator imports — fully unit-
testable in isolation.

Spec: docs/superpowers/specs/2026-05-15-session-summary-card-design.md
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

MODE_LABELS: dict[int, str] = {
    102: "All areas",
}
"""Best-effort mode-enum labels. Unmapped values render as raw=N."""

PRE_TYPE_LABELS: dict[int, str] = {
    0: "Default",
}

START_MODE_LABELS: dict[int, str] = {
    0: "Schedule",
    1: "Manual (app)",
}

STOP_REASON_LABELS: dict[int, str] = {
    -1: "Natural end",
    0: "Natural end",
}

EFFICIENCY_LABELS: dict[int, str] = {
    0: "Eco",
    1: "Standard",
    2: "High",
}


def _compute_distance_m(raw_dict: dict[str, Any], summary: Any) -> float:
    """Sum of pairwise euclidean over _local_legs (fallback to summary track)."""
    from math import hypot

    legs = raw_dict.get("_local_legs") or []
    if not legs:
        legs = [list(seg) for seg in summary.track_segments]
    total = 0.0
    for leg in legs:
        for i in range(1, len(leg)):
            ax, ay = leg[i - 1][0], leg[i - 1][1]
            bx, by = leg[i][0], leg[i][1]
            total += hypot(bx - ax, by - ay)
    return total


def _label(table: dict[int, str], value: Any) -> str:
    if value is None:
        return "—"
    try:
        v = int(value)
    except (TypeError, ValueError):
        return f"raw={value!r}"
    return table.get(v, f"raw={v}")


def format_session_label(entry: Any) -> str:
    """Build a picker label matching DreameA2WorkLogSelect's format.

    Single source of truth — the select entity and the coordinator both
    call this so labels stay aligned. Expects entry to have:
    end_ts (int), map_id (int), area_mowed_m2 (float), duration_min (int),
    optionally md5, local_trail_complete, still_running.
    """
    try:
        ts_str = datetime.fromtimestamp(int(entry.end_ts)).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        ts_str = "??"
    map_id = getattr(entry, "map_id", -1)
    map_prefix = "[Map ?]" if map_id == -1 else f"[Map {map_id + 1}]"
    base = (
        f"[Mowing] {map_prefix} {ts_str}"
        f" — {entry.area_mowed_m2:.1f} m² / {entry.duration_min}min"
    )
    if not getattr(entry, "local_trail_complete", True):
        return f"⚠ {base} (partial trail)"
    return base


def build_picked_session_summary(
    raw_dict: dict[str, Any],
    summary: Any,  # SessionSummary
    entry: Any,   # ArchivedSession
    picker_label: str,
) -> dict[str, Any]:
    """Compute the flat attribute dict for sensor.picked_session.

    The dict is what extra_state_attributes returns; every key is
    rendered to a card field. See spec § Attribute schema for the
    full list. Future fields go alongside; pure-additive growth is
    safe.
    """
    md5 = getattr(entry, "md5", None) or raw_dict.get("md5")

    # Identity & outcome
    out: dict[str, Any] = {
        "label": picker_label,
        "md5": md5,
        "filename": getattr(entry, "filename", None),
        "map_id": getattr(entry, "map_id", None),
        "started_at_unix": summary.start_ts,
        "ended_at_unix": summary.end_ts,
        "started_at": datetime.fromtimestamp(summary.start_ts).strftime("%Y-%m-%d %H:%M"),
        "ended_at": datetime.fromtimestamp(summary.end_ts).strftime("%Y-%m-%d %H:%M"),
        "duration_min": summary.duration_min,
        "mode_raw": summary.mode,
        "mode_label": _label(MODE_LABELS, summary.mode),
        "pre_type_raw": summary.pre_type,
        "pre_type_label": _label(PRE_TYPE_LABELS, summary.pre_type),
        "start_mode_raw": summary.start_mode,
        "start_mode_label": _label(START_MODE_LABELS, summary.start_mode),
        "result_raw": summary.result,
        "stop_reason_raw": summary.stop_reason,
    }

    # Incomplete entries get a special result label.
    if md5 == "(incomplete)":
        out["result_label"] = "Incomplete"
        out["completed"] = False
    else:
        out["result_label"] = "Completed" if summary.result == 1 else _label({}, summary.result)
        out["completed"] = (summary.result == 1 and summary.stop_reason in (-1, 0))

    out["stop_reason_label"] = _label(STOP_REASON_LABELS, summary.stop_reason)

    # Coverage & efficiency
    area = summary.area_mowed_m2 or 0.0
    map_area = summary.map_area_m2 or 0
    duration = summary.duration_min or 0
    out["area_mowed_m2"] = area
    out["map_area_m2"] = map_area
    out["coverage_pct"] = (area / map_area * 100) if map_area else None

    pref = list(summary.pref) if summary.pref else []
    out["mowing_height_mm"] = pref[0] if len(pref) >= 1 else None
    eff = pref[1] if len(pref) >= 2 else None
    out["mowing_efficiency_raw"] = eff
    out["mowing_efficiency_label"] = _label(EFFICIENCY_LABELS, eff)

    out["distance_m"] = _compute_distance_m(raw_dict, summary)

    out["m2_per_min"] = (area / duration) if duration else None
    # m2_per_pct is computed in Task 9 once charge_used_pct is available.
    # Set None placeholder here; Task 9 overwrites.
    out["m2_per_pct"] = None

    return out
