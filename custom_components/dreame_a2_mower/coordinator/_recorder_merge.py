"""Recorder-merge safety net for session sample arrays.

At session-finalize time, the in_progress.json sample arrays
(populated by the 30s-debounced persist + restore chain) may be
missing windows where the persist/restore couldn't run (HA restart
during quiet periods, write-failure, etc.). HA's own recorder
keeps state history for any sensor entity with default-true
recording, so battery and wifi-RSSI samples are recoverable from
there.

Two clean layers:
  - Pure ``_merge_samples`` / ``_merge_wifi_samples`` helpers
    operate on lists. No HA dependency. Trivially unit-tested.
  - Async ``merge_recorder_samples`` orchestrates the recorder
    queries (wrapped in executor jobs) and stitches results into
    raw_dict via the pure helpers.

No ``homeassistant.*`` imports at module top so the pure helpers
can be tested without a running HA. The async function does its
imports lazily inside the function body.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def _merge_samples(
    existing: list[list[int]], additions: list[list[int]]
) -> list[list[int]]:
    """Combine two `[ts_s, value]` lists; dedup on (ts, value); sort by ts.

    Both inputs are lists of 2-element ``[int_ts_seconds, int_value]``
    entries. Returns a new list — neither input is mutated.

    Dedup key is (ts, value), not ts alone, because the same
    timestamp can legitimately carry two distinct values in rare
    cases (e.g., MQTT push and recorder-rounded poll at the same
    second). Keeping both is correct behavior for charts.
    """
    out: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    for src in (existing, additions):
        for s in src:
            if len(s) < 2:
                continue
            key = (int(s[0]), int(s[1]))
            if key in seen:
                continue
            seen.add(key)
            out.append([int(s[0]), int(s[1])])
    out.sort(key=lambda s: s[0])
    return out


def _merge_wifi_samples(
    existing: list[list[Any]], additions: list[list[Any]]
) -> list[list[Any]]:
    """Combine two WiFi sample lists; dedup on (ts, rssi); sort by ts.

    WiFi sample shape: ``[lat_offset, lon_offset, rssi, ts]``.
    Position fields (indices 0 and 1) can be None on
    recorder-sourced samples (no positional context for those
    readings). Dedup compares only the (ts, rssi) pair so
    recorder-sourced entries with None positions correctly merge
    against MQTT-sourced entries that have real positions.
    """
    out: list[list[Any]] = []
    seen: set[tuple[int, int]] = set()
    for src in (existing, additions):
        for s in src:
            if len(s) < 4:
                continue
            try:
                ts = int(s[3])
                rssi = int(s[2])
            except (TypeError, ValueError):
                continue
            key = (ts, rssi)
            if key in seen:
                continue
            seen.add(key)
            out.append([s[0], s[1], rssi, ts])
    out.sort(key=lambda s: s[3])
    return out


# Entity IDs hardcoded here. Both are part of the integration's
# stable entity contract — sensor.py (battery + wifi_rssi) registers
# them with these unique-id suffixes which HA resolves to the
# entity_ids below. If a user renames the entities, the recorder
# merge silently returns 0 samples (no exception); not worth an
# indirection layer until someone reports it.
BATTERY_ENTITY_ID = "sensor.dreame_a2_mower_battery"
WIFI_RSSI_ENTITY_ID = "sensor.dreame_a2_mower_wifi_rssi"

# Lazy import: keeps the module loadable without HA so the pure
# helpers above stay unit-testable in isolation.
try:
    from homeassistant.components.recorder.history import (
        state_changes_during_period,
    )
except ImportError:
    # Tests stub state_changes_during_period at this module path
    # via `unittest.mock.patch`, so the symbol needs to exist
    # at import time even when HA isn't available.
    state_changes_during_period = None  # type: ignore[assignment]


def _read_battery_history_sync(hass, start_dt, end_dt) -> list[list[int]]:
    """Read battery-sensor state history from HA recorder.

    Synchronous — wrapped by ``merge_recorder_samples`` via
    recorder.async_add_executor_job. Returns ``[[ts_seconds, int_pct], ...]``
    sorted ascending by timestamp. Skips entries that aren't
    parseable as ints in the 0..100 range (unknown/unavailable,
    non-numeric, recorder rounding artifacts).
    """
    if state_changes_during_period is None:
        return []
    raw = state_changes_during_period(
        hass,
        start_dt,
        end_dt,
        entity_id=BATTERY_ENTITY_ID,
        include_start_time_state=True,
    )
    out: list[list[int]] = []
    for st in raw.get(BATTERY_ENTITY_ID, []):
        try:
            v = int(st.state)
        except (TypeError, ValueError):
            continue
        if not 0 <= v <= 100:
            continue
        try:
            ts = int(st.last_changed.timestamp())
        except TypeError:
            continue
        out.append([ts, v])
    return out


def _read_wifi_history_sync(hass, start_dt, end_dt) -> list[list[Any]]:
    """Read WiFi-RSSI sensor state history from HA recorder.

    Output shape matches the existing wifi_samples format
    ``[lat_offset, lon_offset, rssi, ts]`` with positions nulled
    (recorder doesn't carry positional context). Skips non-numeric
    states. RSSI is kept as-is from the sensor — typically a
    negative dBm value.
    """
    if state_changes_during_period is None:
        return []
    raw = state_changes_during_period(
        hass,
        start_dt,
        end_dt,
        entity_id=WIFI_RSSI_ENTITY_ID,
        include_start_time_state=True,
    )
    out: list[list[Any]] = []
    for st in raw.get(WIFI_RSSI_ENTITY_ID, []):
        try:
            rssi = int(st.state)
        except (TypeError, ValueError):
            continue
        try:
            ts = int(st.last_changed.timestamp())
        except TypeError:
            continue
        out.append([None, None, rssi, ts])
    return out


async def _async_fetch_battery_from_recorder(
    hass, start_ts: int, end_ts: int
) -> list[list[int]]:
    """Async wrapper around _read_battery_history_sync that runs the
    blocking recorder query in an executor.

    Returns an empty list if the recorder isn't loaded or the query
    raises — the caller treats this as "no augmenting samples
    available" and falls back to the in_progress.json samples
    alone.
    """
    try:
        from homeassistant.components.recorder import get_instance
    except ImportError:
        return []
    try:
        instance = get_instance(hass)
    except Exception:
        LOGGER.exception("[recorder_merge] get_instance failed")
        return []
    start_dt = _dt.datetime.fromtimestamp(start_ts, _dt.UTC)
    end_dt = _dt.datetime.fromtimestamp(end_ts, _dt.UTC)
    try:
        return await instance.async_add_executor_job(
            _read_battery_history_sync, hass, start_dt, end_dt
        )
    except Exception:
        LOGGER.exception(
            "[recorder_merge] battery history query failed for [%d, %d]",
            start_ts, end_ts,
        )
        return []


async def _async_fetch_wifi_from_recorder(
    hass, start_ts: int, end_ts: int
) -> list[list[Any]]:
    """Async wrapper around _read_wifi_history_sync. Same failure
    mode as the battery variant — returns [] on any error.
    """
    try:
        from homeassistant.components.recorder import get_instance
    except ImportError:
        return []
    try:
        instance = get_instance(hass)
    except Exception:
        LOGGER.exception("[recorder_merge] get_instance failed")
        return []
    start_dt = _dt.datetime.fromtimestamp(start_ts, _dt.UTC)
    end_dt = _dt.datetime.fromtimestamp(end_ts, _dt.UTC)
    try:
        return await instance.async_add_executor_job(
            _read_wifi_history_sync, hass, start_dt, end_dt
        )
    except Exception:
        LOGGER.exception(
            "[recorder_merge] wifi history query failed for [%d, %d]",
            start_ts, end_ts,
        )
        return []


async def merge_recorder_samples(
    hass, raw_dict: dict[str, Any], start_ts: int, end_ts: int
) -> dict[str, int]:
    """Merge HA recorder history for battery + wifi-RSSI into raw_dict.

    Mutates ``raw_dict`` in place: replaces ``battery_samples`` and
    ``wifi_samples`` with the merged-and-sorted union of whatever
    was there + whatever the recorder reports for the window.

    Returns a dict with raw-fetch counts so the caller can log
    how much the recorder contributed.

    Failure mode: recorder errors are caught and logged inside the
    _async_fetch_* helpers; this orchestrator never raises. If
    both fetches return [] the existing raw_dict samples are left
    untouched.
    """
    battery_recorder = await _async_fetch_battery_from_recorder(
        hass, start_ts, end_ts,
    )
    wifi_recorder = await _async_fetch_wifi_from_recorder(
        hass, start_ts, end_ts,
    )
    existing_battery = raw_dict.get("battery_samples") or []
    existing_wifi = raw_dict.get("wifi_samples") or []
    raw_dict["battery_samples"] = _merge_samples(
        existing_battery, battery_recorder,
    )
    raw_dict["wifi_samples"] = _merge_wifi_samples(
        existing_wifi, wifi_recorder,
    )
    return {
        "battery_recorder_count": len(battery_recorder),
        "wifi_recorder_count": len(wifi_recorder),
    }
