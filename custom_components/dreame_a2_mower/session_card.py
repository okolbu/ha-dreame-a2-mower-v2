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

PEN_UP_GAP_S_DEFAULT: float = 30.0


def derive_render_legs(
    track: list[dict],
    *,
    pen_up_gap_s: float = PEN_UP_GAP_S_DEFAULT,
) -> list[dict]:
    """Split a per-point track into render legs.

    A new leg starts on a role flip OR a pen-up boundary (time gap >
    pen_up_gap_s). On a role flip the boundary point is shared between the
    closing and opening legs so the polylines visually touch. On a pen-up
    boundary the legs do NOT share a point (the connecting stroke is
    suppressed at render time).

    Returns list of {role, start_ts, end_ts, pts:[(x,y),...]}.
    """
    if not track:
        return []
    legs: list[dict] = []
    cur: dict | None = None
    for i, p in enumerate(track):
        role = p["role"]
        xy = (p["x_m"], p["y_m"])
        pen_up = (
            i > 0 and (p["t"] - track[i - 1]["t"]) > pen_up_gap_s
        )
        if cur is None:
            cur = {"role": role, "start_ts": p["t"], "end_ts": p["t"], "pts": [xy]}
            continue
        if pen_up:
            legs.append(cur)
            cur = {"role": role, "start_ts": p["t"], "end_ts": p["t"], "pts": [xy]}
        elif role != cur["role"]:
            legs.append(cur)
            prev_xy = track[i - 1]["x_m"], track[i - 1]["y_m"]
            cur = {"role": role, "start_ts": track[i - 1]["t"],
                   "end_ts": p["t"], "pts": [prev_xy, xy]}
        else:
            cur["pts"].append(xy)
            cur["end_ts"] = p["t"]
    if cur is not None:
        legs.append(cur)
    return [leg for leg in legs if len(leg["pts"]) >= 2]


def compute_track_distances(
    track: list[dict],
    *,
    pen_up_gap_s: float = PEN_UP_GAP_S_DEFAULT,
) -> dict[str, float]:
    """Total/mowing/traversal distance in metres over the track.

    A segment's role is the role of its END point. Segments across a pen-up
    boundary (time gap > pen_up_gap_s) are excluded from all three totals.
    """
    from math import hypot

    total = mow = trav = 0.0
    for i in range(1, len(track)):
        a, b = track[i - 1], track[i]
        if (b["t"] - a["t"]) > pen_up_gap_s:
            continue
        d = hypot(b["x_m"] - a["x_m"], b["y_m"] - a["y_m"])
        total += d
        if b["role"] == "mowing":
            mow += d
        else:
            trav += d
    return {"distance_m": total, "distance_mowing_m": mow, "distance_traversal_m": trav}


def _normalise_settings_snapshot(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Return a v2-shaped settings_snapshot dict.

    v1 snapshots are flat dicts with no ``version`` key (per-map fields only).
    v2 snapshots carry ``version >= 2`` and four named sections.  Both forms
    are wrapped/passed-through into the canonical v2 shape so that downstream
    consumers (dashboard T13+) can always read ``snapshot["per_map"]`` etc.
    without branching.

    Returns a zero-content v2 shape for ``None`` so downstream ``.get()``
    calls never crash.
    """
    if not snap:
        return {
            "version": 0,
            "per_map": {},
            "device_wide": {},
            "peripheral": {},
            "forensic": {},
        }
    if snap.get("version", 0) >= 2:
        # Already v2 — pass through but defensively backfill missing sections.
        return {
            "version": snap.get("version", 2),
            "captured_at_unix": snap.get("captured_at_unix"),
            "per_map": snap.get("per_map") or {},
            "device_wide": snap.get("device_wide") or {},
            "peripheral": snap.get("peripheral") or {},
            "forensic": snap.get("forensic") or {},
        }
    # v1: flat dict of per-map fields — wrap as per_map subsection.
    return {
        "version": 1,
        "per_map": dict(snap),
        "device_wide": {},
        "peripheral": {},
        "forensic": {},
    }



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


# Mowing-state codes per s2p1 task_state semantics. Only state=1
# (active mowing) is classified as mowing time; states 2/3 fall into
# Other (transition/fault codes that don't represent true blade-on time).
_MOWING_STATE_CODES: set[int] = {1}
_CHARGING_STATE_CODE: int = 6


def _build_rain_intervals(
    error_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> list[tuple[int, int]]:
    """Walk error_samples; each 'enter err=56' opens, next 'leave 56' closes.

    Robust to:
      - Consecutive err=56 events (treated as one window).
      - A 56 that's never closed before end_ts (extends to end_ts).
      - Out-of-order input (sorts first).
      - Events outside [start_ts, end_ts] (ignored).
    """
    if not error_samples:
        return []
    sorted_err = sorted(error_samples, key=lambda s: int(s[0]))
    intervals: list[tuple[int, int]] = []
    open_ts: int | None = None
    for s in sorted_err:
        if len(s) < 2:
            continue
        try:
            ts = int(s[0])
            code = int(s[1])
        except (TypeError, ValueError):
            continue
        if ts < start_ts or ts > end_ts:
            continue
        if code == 56 and open_ts is None:
            open_ts = ts
        elif code != 56 and open_ts is not None:
            intervals.append((open_ts, ts))
            open_ts = None
    if open_ts is not None:
        intervals.append((open_ts, end_ts))
    return intervals


def _build_state_intervals(
    state_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
) -> list[tuple[int, int, int]]:
    """Forward-fill state_samples into [start_ts, end_ts] step intervals.

    Returns a list of (interval_start, interval_end, state_code).
    Adjacent intervals with the same state code are merged.

    Special handling:
      - The gap [start_ts, first_state_ts] gets state=-1 (sentinel
        for "unknown"; never matches the mowing/charging filters
        so it falls into Other).
      - A state entry with ts < start_ts seeds the initial state
        instead of producing a -1 prefix.
      - Entries with ts > end_ts are ignored.
      - Out-of-order input is sorted first.
    """
    if end_ts <= start_ts:
        return []
    if not state_samples:
        return [(start_ts, end_ts, -1)]

    sorted_samples = sorted(state_samples, key=lambda s: int(s[0]))
    intervals: list[tuple[int, int, int]] = []

    # Determine initial state at start_ts.
    initial_state = -1
    in_window: list[tuple[int, int]] = []
    for s in sorted_samples:
        if len(s) < 2:
            continue
        try:
            ts = int(s[0])
            code = int(s[1])
        except (TypeError, ValueError):
            continue
        if ts <= start_ts:
            initial_state = code
        elif ts <= end_ts:
            in_window.append((ts, code))

    cur_state = initial_state
    cur_start = start_ts
    for ts, code in in_window:
        if code == cur_state:
            continue  # merge adjacent same-state entries
        if ts > cur_start:
            intervals.append((cur_start, ts, cur_state))
        cur_start = ts
        cur_state = code
    if cur_start < end_ts:
        intervals.append((cur_start, end_ts, cur_state))
    return intervals


def _interval_total_seconds(intervals: list[tuple[int, int]]) -> int:
    """Sum (end - start) over a list of (start, end) intervals.

    Assumes non-overlapping (caller's responsibility).
    _build_rain_intervals satisfies this naturally.
    """
    return sum(max(0, b - a) for a, b in intervals)


def _state_seconds_outside_intervals(
    state_intervals: list[tuple[int, int, int]],
    target_states: set[int],
    excluded_intervals: list[tuple[int, int]],
) -> int:
    """Sum seconds in any state_interval whose state is in target_states,
    EXCLUDING any overlap with excluded_intervals.

    Both interval lists are assumed sorted ascending and
    non-overlapping internally. Excluded intervals are subtracted
    via per-pair clipping (O(N*M); fine for our N,M < 1000).
    """
    total = 0
    for sa, sb, sv in state_intervals:
        if sv not in target_states:
            continue
        seg_total = sb - sa
        for ea, eb in excluded_intervals:
            if eb <= sa or ea >= sb:
                continue
            seg_total -= min(sb, eb) - max(sa, ea)
        total += max(0, seg_total)
    return total


def _compute_time_breakdown(
    battery_samples: list[list[int]],
    charging_samples: list[list[int]],
    start_ts: int,
    end_ts: int,
    *,
    error_samples: list[list[int]] | None = None,
    state_samples: list[list[int]] | None = None,
) -> tuple[int | None, int | None, int, int | None]:
    """Split the session wall-clock into (mowing, charging, rain, other) minutes.

    State-driven (not battery-drop-driven). Buckets are mutually
    exclusive and sum to elapsed minutes exactly.

    Priority order:
      1. Rain delay  — any second inside an s2p2=56 window
                       (regardless of mower state)
      2. Mowing      — state=1 outside rain
      3. Charging    — state=6 outside rain
      4. Other       — remainder (state=13/5/3/2 + unknown gaps)

    battery_samples and charging_samples are kept in the
    signature for API compatibility but no longer used for time
    totals. They're still consumed by the dashboard chart.

    error_samples and state_samples are keyword-only kwargs to
    keep older positional callers working — they'll receive
    (None, None, 0, None) which is the safest fallback when no
    state_samples are passed.
    """
    if state_samples is None or not state_samples:
        rain_intervals_only = _build_rain_intervals(
            error_samples or [], start_ts, end_ts,
        )
        rain_s = _interval_total_seconds(rain_intervals_only)
        return (None, None, rain_s // 60, None)

    rain_intervals = _build_rain_intervals(
        error_samples or [], start_ts, end_ts,
    )
    state_intervals = _build_state_intervals(
        state_samples, start_ts, end_ts,
    )

    rain_s = _interval_total_seconds(rain_intervals)
    mowing_s = _state_seconds_outside_intervals(
        state_intervals, _MOWING_STATE_CODES, rain_intervals,
    )
    charging_s = _state_seconds_outside_intervals(
        state_intervals, {_CHARGING_STATE_CODE}, rain_intervals,
    )

    total_min = max(0, end_ts - start_ts) // 60
    mow_min = mowing_s // 60
    chg_min = charging_s // 60
    rain_min = rain_s // 60
    other_min = max(0, total_min - mow_min - chg_min - rain_min)

    return (mow_min, chg_min, rain_min, other_min)


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


def _summary_identity(summary: Any, entry: Any, picker_label: str, md5: str | None) -> dict[str, Any]:
    """Identity & outcome section of build_picked_session_summary."""
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
    return out


def _summary_coverage_efficiency(summary: Any, raw_dict: dict[str, Any]) -> dict[str, Any]:
    """Coverage & efficiency section of build_picked_session_summary."""
    out: dict[str, Any] = {}
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

    _dist = compute_track_distances(_track_as_dicts(raw_dict))
    out["distance_m"] = _dist["distance_m"]
    out["distance_mowing_m"] = _dist["distance_mowing_m"]
    out["distance_traversal_m"] = _dist["distance_traversal_m"]

    out["m2_per_min"] = (area / duration) if duration else None
    # m2_per_pct is computed by the orchestrator once charge_used_pct is available.
    return out


def _summary_energy_time(raw_dict: dict[str, Any], summary: Any) -> dict[str, Any]:
    """Energy & time-breakdown section of build_picked_session_summary."""
    out: dict[str, Any] = {}
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

    err_samples = list(raw_dict.get("error_samples") or [])
    mow_min, chg_min, rain_min, other_min = _compute_time_breakdown(
        bs, cs, summary.start_ts, summary.end_ts,
        error_samples=err_samples,
        state_samples=ss,
    )
    out["time_mowing_min"] = mow_min
    out["time_charging_min"] = chg_min
    out["time_rain_protection_min"] = rain_min
    out["time_other_min"] = other_min

    out["battery_samples"] = bs
    return out


def _summary_diagnostics(summary: Any, raw_dict: dict[str, Any]) -> dict[str, Any]:
    """Diagnostics section of build_picked_session_summary."""
    out: dict[str, Any] = {}
    ss = list(raw_dict.get("state_samples") or [])
    err_samples = list(raw_dict.get("error_samples") or [])
    ws = list(raw_dict.get("wifi_samples") or [])

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
    out["error_event_count"] = len(err_samples)
    out["error_codes_seen"] = sorted({int(v) for _, v in err_samples})

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
    return out


def _track_as_dicts(raw_dict: dict[str, Any]) -> list[dict]:
    """Normalize raw_dict['track'] to the point-DICT shape.

    Archives persist track as ROWS ([t, x_m, y_m, area_m2, heading_deg,
    task_state, role]); the in-memory/derive working shape is dicts. This is
    the archive→working-shape boundary: rows are converted, dicts pass
    through unchanged (transient in-memory callers + unit tests)."""
    from .live_map.state import track_row_to_dict

    out: list[dict] = []
    for r in raw_dict.get("track") or []:
        out.append(r if isinstance(r, dict) else track_row_to_dict(r))
    return out


def _summary_trail_legs(raw_dict: dict[str, Any], summary: Any, map_projection: dict | None) -> dict[str, Any]:
    """Trail/legs section, derived purely from the per-point track."""
    track = _track_as_dicts(raw_dict)
    legs = derive_render_legs(track)
    legs_timeline = [
        {"role": leg["role"], "start_ts": int(leg["start_ts"]),
         "end_ts": int(leg["end_ts"]),
         "pts": [[float(x), float(y)] for (x, y) in leg["pts"]]}
        for leg in legs
    ]
    out: dict[str, Any] = {
        "legs_timeline": legs_timeline,
        "track_first_ts": int(track[0]["t"]) if track else None,
        "track_last_ts": int(track[-1]["t"]) if track else None,
        "map_projection": map_projection,
    }
    _ts_for_url = (summary.start_ts if summary is not None else None) or (
        track[0]["t"] if track else 0
    )
    out["base_map_image_url"] = f"/api/dreame_a2_mower/work_log.png?ts={int(_ts_for_url)}"
    out["base_map_image_url_no_trail"] = (
        f"/api/dreame_a2_mower/work_log.png?ts={int(_ts_for_url)}&trail=false"
    )
    return out


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
    out: dict[str, Any] = {}
    out.update(_summary_identity(summary, entry, picker_label, md5))
    out.update(_summary_coverage_efficiency(summary, raw_dict))
    out.update(_summary_energy_time(raw_dict, summary))
    out.update(_summary_diagnostics(summary, raw_dict))
    out["settings_snapshot"] = _normalise_settings_snapshot(raw_dict.get("settings_snapshot"))
    out.update(_summary_trail_legs(raw_dict, summary, map_projection))
    # Cross-section: m2_per_pct needs charge_used_pct (energy) + area (coverage).
    area = out.get("area_mowed_m2") or 0.0
    out["m2_per_pct"] = (
        (area / out["charge_used_pct"])
        if out.get("charge_used_pct", 0) > 0 and area
        else None
    )
    return out
