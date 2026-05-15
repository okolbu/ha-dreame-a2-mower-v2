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


def _battery_drops_and_rises(battery_samples: list[list[int]]) -> tuple[int, int]:
    """Sum of consecutive-pair drops and rises in battery_samples.

    Drops = energy consumed by mowing/movement. Rises = energy gained
    by charging. With mid-mow recharges, neither equals the net delta
    (start - end) — drops + rises both accumulate across the session.

    Returns (consumed_pct, recovered_pct).
    """
    consumed = 0
    recovered = 0
    for i in range(len(battery_samples) - 1):
        try:
            p1 = int(battery_samples[i][1])
            p2 = int(battery_samples[i + 1][1])
        except (IndexError, TypeError, ValueError):
            continue
        delta = p2 - p1
        if delta < 0:
            consumed += -delta
        elif delta > 0:
            recovered += delta
    return consumed, recovered


def _compute_time_breakdown(
    battery_samples: list[list[int]],
    charging_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> tuple[int | None, int | None, int | None]:
    """Split the session wall-clock into (mowing, charging, other) minutes.

    Algorithm — uses two reliable signals:

    - **time_charging**: sum of intervals where charging_status_samples
      shows the mower at the dock charging (value == 1). Step-integrated
      with initial state 0.
    - **time_mowing**: sum of intervals where battery dropped between
      consecutive battery_samples. Battery declines during active mowing
      (or transit, which we lump in here). Idle drift is usually
      indistinguishable from a 1% drop over a long interval, so very
      slow drops will count as mowing — accepted approximation.
    - **time_other**: total - charging - mowing. Anything left over
      (pauses, faults, idle at dock without charging).

    Returns (None, None, None) when both sample streams are empty so
    the card distinguishes 'no data' from 'zero minutes'.
    """
    if not battery_samples and not charging_samples:
        return (None, None, None)

    total_s = max(0, int(end_ts) - int(start_ts))

    # Charging time from charging_status_samples (step-integrate from
    # implicit 0 at start_ts to whatever value the events dictate).
    charging_s = 0
    if charging_samples:
        cur = 0
        last_t = int(start_ts)
        for raw in charging_samples:
            try:
                t = int(raw[0])
                v = int(raw[1])
            except (IndexError, TypeError, ValueError):
                continue
            if cur == 1:
                charging_s += max(0, t - last_t)
            cur = v
            last_t = t
        if cur == 1:
            charging_s += max(0, int(end_ts) - last_t)

    # Mowing time = sum of intervals where battery dropped between
    # consecutive samples.
    mowing_s = 0
    for i in range(len(battery_samples) - 1):
        try:
            t1 = int(battery_samples[i][0])
            t2 = int(battery_samples[i + 1][0])
            p1 = int(battery_samples[i][1])
            p2 = int(battery_samples[i + 1][1])
        except (IndexError, TypeError, ValueError):
            continue
        if p2 < p1:
            mowing_s += max(0, t2 - t1)

    # Charging is authoritative when both signals overlap — battery
    # samples can drop briefly during charging cycles due to discharge
    # measurement noise. Cap mowing_s at total - charging_s so the
    # three slices sum to the wall-clock window.
    mowing_s = min(mowing_s, max(0, total_s - charging_s))
    other_s = max(0, total_s - charging_s - mowing_s)
    return (mowing_s // 60, charging_s // 60, other_s // 60)


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
    start_ts (int), end_ts (int), map_id (int), area_mowed_m2 (float),
    duration_min (int), optionally md5, local_trail_complete, still_running.

    The timestamp shown is the session START so the label matches what
    the Dreame app displays (the app indexes sessions by start date).
    For mows that cross midnight the end-ts based label would group the
    session under the wrong day.
    """
    try:
        ts_str = datetime.fromtimestamp(int(entry.start_ts)).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError, AttributeError):
        try:
            ts_str = datetime.fromtimestamp(int(entry.end_ts)).strftime("%Y-%m-%d %H:%M")
        except (OverflowError, OSError, ValueError, AttributeError):
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
    *,
    map_projection: dict | None = None,
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
        # Cloud's duration_min is MOWING-ONLY time (matches the Dreame
        # app's display). For a session with mid-mow recharges the
        # wall-clock elapsed is larger — exposed separately so the
        # dashboard can show both without conflating them. Also used
        # as the divisor for m²/min (mowing productivity, not elapsed).
        "duration_min": summary.duration_min,
        "elapsed_min": max(0, (summary.end_ts - summary.start_ts) // 60),
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
    # m2_per_pct is computed below once charge_used_pct is available.
    out["m2_per_pct"] = None

    # Energy & time-breakdown
    bs = list(raw_dict.get("battery_samples") or [])
    cs = list(raw_dict.get("charging_status_samples") or [])
    ss = list(raw_dict.get("state_samples") or [])

    charge_at_start_pct = raw_dict.get("charge_at_start")
    if charge_at_start_pct is None and bs:
        charge_at_start_pct = bs[0][1]
    out["charge_at_start_pct"] = (
        int(charge_at_start_pct) if charge_at_start_pct is not None else None
    )
    out["charge_at_end_pct"] = bs[-1][1] if bs else None
    out["charge_min_pct"] = min(v for _, v in bs) if bs else None

    # charge_used_pct = total energy CONSUMED across all mowing phases.
    # With mid-mow recharges the simple start-end delta understates the
    # true cost (recharges add back into the bank). Sum every drop in
    # battery_samples; sum every rise as charge_recovered_pct. Net delta
    # is exposed separately for sanity.
    consumed, recovered = _battery_drops_and_rises(bs)
    out["charge_used_pct"] = consumed
    out["charge_recovered_pct"] = recovered
    if out["charge_at_start_pct"] is not None and out["charge_at_end_pct"] is not None:
        out["charge_net_delta_pct"] = (
            out["charge_at_start_pct"] - out["charge_at_end_pct"]
        )
    else:
        out["charge_net_delta_pct"] = None

    out["recharge_count"] = sum(
        1 for i in range(1, len(cs)) if cs[i - 1][1] == 0 and cs[i][1] == 1
    )

    mow_min, chg_min, other_min = _compute_time_breakdown(
        bs, cs, summary.start_ts, summary.end_ts
    )
    out["time_mowing_min"] = mow_min
    out["time_charging_min"] = chg_min
    out["time_other_min"] = other_min

    if out["charge_used_pct"] > 0 and area:
        out["m2_per_pct"] = area / out["charge_used_pct"]
    else:
        out["m2_per_pct"] = None

    out["battery_samples"] = bs

    # Diagnostics
    out["fault_count"] = len(summary.faults)
    faults_compact = [str(f) for f in summary.faults[:5]]
    if len(summary.faults) > 5:
        faults_compact.append(f"+{len(summary.faults) - 5} more")
    out["faults_compact"] = faults_compact
    out["obstacle_count"] = len(summary.obstacles)
    out["ai_obstacle_count"] = len(summary.ai_obstacle)
    out["state_transition_count"] = len(ss)
    # Card-side animation reads state_samples to classify mowing-vs-pause
    # intervals for the proportional pause-budget timing model.
    out["state_samples"] = [
        [int(t), int(v)] for t, v in ss
        if isinstance(t, (int, float)) and isinstance(v, (int, float))
    ]
    err_samples = list(raw_dict.get("error_samples") or [])
    out["error_event_count"] = len(err_samples)
    out["error_codes_seen"] = sorted({int(v) for _, v in err_samples})

    ws = list(raw_dict.get("wifi_samples") or [])
    if ws:
        rssis = [int(s[2]) for s in ws]
        out["wifi_rssi_min_dbm"] = min(rssis)
        out["wifi_rssi_max_dbm"] = max(rssis)
        out["wifi_rssi_avg_dbm"] = round(sum(rssis) / len(rssis))
    else:
        out["wifi_rssi_min_dbm"] = None
        out["wifi_rssi_max_dbm"] = None
        out["wifi_rssi_avg_dbm"] = None
    out["wifi_sample_count"] = len(ws)
    out["wifi_samples"] = ws

    # Settings snapshot passthrough
    snapshot = raw_dict.get("settings_snapshot")
    out["settings_snapshot"] = (
        dict(snapshot) if isinstance(snapshot, dict) else None
    )

    # Card-side trail animation reads this; same source as _compute_distance_m.
    legs_raw = raw_dict.get("_local_legs") or [
        list(seg) for seg in summary.track_segments
    ]
    out["legs"] = [
        [[float(p[0]), float(p[1])] for p in leg if len(p) >= 2]
        for leg in legs_raw
        if leg
    ]

    out["map_projection"] = map_projection

    return out
