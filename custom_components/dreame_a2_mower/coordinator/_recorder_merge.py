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
