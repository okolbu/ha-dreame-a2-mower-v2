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

    # Card-side trail animation reads this. We expose the UNION of both
    # available trail sources because each tells a different part of the
    # story:
    #
    # - `_local_legs` (locally captured from s1p4 trail samples) records
    #   the FULL motion trail including non-mowing traversals: dock
    #   returns, cross-yard navigation between unmowed areas, etc.
    # - `summary.track_segments` (cloud-curated `map[].track`) records
    #   only the actual mowing path, but as many small fragmented
    #   segments. Sometimes captures mowing chunks that _local_legs
    #   missed (the g2408 spot/zone partial-capture case).
    #
    # Neither alone is complete. Concatenating both means the animation
    # draws both the traversal arcs AND every mowing chunk. Where both
    # sources overlap on the actual mowing path, the line is drawn twice
    # — visually identical to once.
    cloud_legs = [list(seg) for seg in summary.track_segments]
    local_legs = raw_dict.get("_local_legs") or []

    def _clean(leg):
        """Drop malformed points; keep only legs with >=2 surviving points."""
        return [[float(p[0]), float(p[1])] for p in leg if len(p) >= 2]

    # local_legs come FIRST in the union so the card can attribute the
    # pause budget (charging time) to the gaps between them — those
    # gaps ARE the real "mower stopped to charge" boundaries. Cloud
    # legs come after and are mid-mow fragmentation noise; their
    # inter-leg gaps shouldn't get a slice of the pause budget.
    clean_local = [_clean(leg) for leg in local_legs if leg]
    clean_local = [leg for leg in clean_local if len(leg) >= 2]
    clean_cloud = [_clean(leg) for leg in cloud_legs if leg]
    clean_cloud = [leg for leg in clean_cloud if len(leg) >= 2]
    out["legs"] = clean_local + clean_cloud
    # Count of legs in the union that came from _local_legs (after the
    # <2-point filter that the card also applies). The card uses this
    # to know which gaps are "real" pen-up boundaries vs cloud-side
    # fragmentation noise, and concentrates pauseBudgetMs on the real ones.
    out["local_leg_count"] = len(clean_local)

    out["map_projection"] = map_projection

    # Static path — WorkLogImageView serves the active work-log PNG without
    # auth (same as the live-map view). The card consumes this as the SVG's
    # <image href=...> background so the trail aligns with the base map.
    # ts query param forces the browser to refetch when the picked session
    # changes (the underlying view returns the current _work_log_png, which is
    # set atomically with _picked_session_summary). Without the cache-buster,
    # the browser may serve a stale PNG and the SVG paths (projected for the
    # NEW session's map_projection) would overlay the WRONG base image.
    #
    # We use started_at_unix (per-session unique), NOT md5 — on g2408 the
    # md5 is per-map, shared across all sessions for the same map. Using
    # md5 as the cache-buster caused the browser to serve the previous
    # session's PNG when picking a different session on the same map.
    _ts_for_url = out.get("started_at_unix") or 0
    out["base_map_image_url"] = (
        f"/api/dreame_a2_mower/work_log.png?ts={_ts_for_url}"
    )

    return out
