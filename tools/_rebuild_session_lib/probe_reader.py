"""Walk probe *.jsonl files; expose properties_changed events
indexed by (siid, piid).

Mirrors the logic in tools/backfill_session_samples.py but exposes
events for ALL slots, not just the four sample arrays. Downstream
helpers (wifi_replay, track_replay, settings_replay) consume events
for the slots they need.
"""
from __future__ import annotations

import datetime as dt
import json
import zoneinfo
from collections import defaultdict
from typing import Any


def _parse_probe_ts(s: str, tz: zoneinfo.ZoneInfo) -> int:
    """Parse a probe-log timestamp string to unix seconds.

    Probe writes 'YYYY-MM-DD HH:MM:SS' in the configured timezone.
    """
    return int(
        dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=tz)
        .timestamp()
    )


class ProbeReader:
    """Parsed event store. One instance covers a list of probe files.

    Events are indexed by (siid, piid) and within that sorted by ts.
    Values are kept verbatim — callers decode dicts/lists/ints as
    appropriate for the slot.
    """

    def __init__(
        self,
        probe_paths: list[str],
        tz: zoneinfo.ZoneInfo | None = None,
    ) -> None:
        self._tz = tz if tz is not None else zoneinfo.ZoneInfo("UTC")
        # {(siid, piid): [(ts_unix, value), ...]}
        self._store: dict[tuple[int, int], list[tuple[int, Any]]] = defaultdict(list)
        for p in probe_paths:
            self._ingest(p)
        for events in self._store.values():
            events.sort(key=lambda t: t[0])

    def _ingest(self, path: str) -> None:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "mqtt_message":
                    continue
                payload = rec.get("payload") or {}
                data = payload.get("data") or {}
                if data.get("method") != "properties_changed":
                    continue
                try:
                    ts = _parse_probe_ts(rec["timestamp"], self._tz)
                except Exception:
                    continue
                for param in data.get("params") or []:
                    try:
                        slot = (int(param["siid"]), int(param["piid"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    self._store[slot].append((ts, param.get("value")))

    def events_for_slot(
        self,
        siid: int,
        piid: int,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> list[tuple[int, Any]]:
        """Return events for the given slot.

        If start_ts/end_ts provided, filters to events within
        [start_ts, end_ts] inclusive.
        """
        events = self._store.get((siid, piid), [])
        if start_ts is None and end_ts is None:
            return list(events)
        out: list[tuple[int, Any]] = []
        for ts, val in events:
            if start_ts is not None and ts < start_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue
            out.append((ts, val))
        return out

    def slots_seen(self) -> list[tuple[int, int]]:
        """Diagnostic: list of all slots with at least one event."""
        return sorted(self._store.keys())
