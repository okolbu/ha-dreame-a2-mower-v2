"""Backfill telemetry sample buffers into existing session archive JSONs.

Pre-v1.0.12a2 session archives don't carry the battery / charging_status /
state / error sample streams that are now captured at the coordinator
level. As long as the matching probe MQTT log still exists, the streams
can be reconstructed offline by replaying properties_changed events that
fall within each session's [start, end] window.

Usage:
    python tools/backfill_session_samples.py \\
        --sessions-dir /tmp/session_backfill \\
        --probe-glob '/data/claude/homeassistant/probe_log_*.jsonl' \\
        --tz Europe/Oslo

The tool mutates session JSONs in place (writes alongside via a .tmp
swap). Pass --dry-run to print what would be written without touching
disk.

Sample shape matches what the live coordinator writes:
    battery_samples            : [[ts_unix, pct],     ...]
    charging_status_samples    : [[ts_unix, enum],    ...]
    state_samples              : [[ts_unix, enum],    ...]
    error_samples              : [[ts_unix, code],    ...]
    charge_at_start            : int | None  (most-recent s3p1 before start)

Run on the dev box where probe logs live; ship resulting JSONs back to
HA's /config/dreame_a2_mower/sessions/ via scp.
"""
from __future__ import annotations

import argparse
import bisect
import datetime
import glob
import json
import os
import sys
import zoneinfo
from collections import defaultdict
from pathlib import Path
from typing import Any

# Slots we currently capture in the live path; same set for backfill.
WATCH_SLOTS: set[tuple[int, int]] = {(3, 1), (3, 2), (2, 1), (2, 2)}

# Field-name table mirrors coordinator/_mqtt_handlers.py::_capture_telemetry_sample.
SLOT_TO_FIELD: dict[tuple[int, int], str] = {
    (3, 1): "battery_samples",
    (3, 2): "charging_status_samples",
    (2, 1): "state_samples",
    (2, 2): "error_samples",
}


def parse_probe_ts(s: str, tz: zoneinfo.ZoneInfo) -> int:
    return int(
        datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).timestamp()
    )


def build_event_store(
    probe_paths: list[str], tz: zoneinfo.ZoneInfo
) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """Scan all probe logs and return {(siid, piid): [(ts, value), ...]} sorted by ts.

    Only properties_changed events for slots in WATCH_SLOTS are kept. Values
    that can't be coerced to int are dropped.
    """
    store: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for p in probe_paths:
        with open(p) as f:
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
                    ts = parse_probe_ts(rec["timestamp"], tz)
                except Exception:
                    continue
                for param in data.get("params") or []:
                    try:
                        slot = (int(param["siid"]), int(param["piid"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if slot not in WATCH_SLOTS:
                        continue
                    val = param.get("value")
                    try:
                        v_int = int(val)
                    except (TypeError, ValueError):
                        continue
                    store[slot].append((ts, v_int))
    for slot, lst in store.items():
        lst.sort(key=lambda t: t[0])
    return store


def collect_window(
    store: dict[tuple[int, int], list[tuple[int, int]]],
    start: int,
    end: int,
) -> dict[str, list[list[int]]]:
    """Return field_name -> [[ts, value], ...] for the slot's events in [start, end].

    Identical-value dedup (mirrors LiveMapState.append_telemetry_sample) is
    applied so the on-wire heartbeat repeats don't bloat the buffers.
    """
    out: dict[str, list[list[int]]] = {}
    for slot, field in SLOT_TO_FIELD.items():
        events = store.get(slot, [])
        if not events:
            continue
        # bisect_left on the ts key.
        ts_keys = [e[0] for e in events]
        lo = bisect.bisect_left(ts_keys, start)
        hi = bisect.bisect_right(ts_keys, end)
        slice_ = events[lo:hi]
        if not slice_:
            continue
        deduped: list[list[int]] = []
        last_v: int | None = None
        for ts, v in slice_:
            if v == last_v:
                continue
            deduped.append([ts, v])
            last_v = v
        if deduped:
            out[field] = deduped
    return out


def find_charge_at_start(
    store: dict[tuple[int, int], list[tuple[int, int]]], start: int
) -> int | None:
    """Most recent s3p1 value at-or-before the session start, or None."""
    events = store.get((3, 1), [])
    if not events:
        return None
    ts_keys = [e[0] for e in events]
    idx = bisect.bisect_right(ts_keys, start) - 1
    if idx < 0:
        return None
    return events[idx][1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sessions-dir", default="/tmp/session_backfill",
        help="Local directory holding session-archive JSONs to mutate.",
    )
    parser.add_argument(
        "--probe-glob",
        default="/data/claude/homeassistant/probe_log_*.jsonl",
        help="Glob for probe log files.",
    )
    parser.add_argument(
        "--tz", default="Europe/Oslo",
        help="Timezone the probe logs were written in (no TZ marker in lines).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Don't write back; just report what would change.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing sample lists. Default: skip if any sample list is already populated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tz = zoneinfo.ZoneInfo(args.tz)
    probe_paths = sorted(glob.glob(args.probe_glob))
    if not probe_paths:
        print(f"no probe logs matched {args.probe_glob!r}", file=sys.stderr)
        return 2

    print(f"scanning {len(probe_paths)} probe log(s) for slots {sorted(WATCH_SLOTS)}…")
    store = build_event_store(probe_paths, tz)
    for slot in sorted(WATCH_SLOTS):
        print(f"  s{slot[0]}p{slot[1]}: {len(store.get(slot, []))} events")

    session_paths = sorted(Path(args.sessions_dir).glob("*.json"))
    session_paths = [
        p for p in session_paths
        if p.name not in {"index.json", "in_progress.json"}
        and not p.name.startswith("index.json.bak")
    ]
    print(f"\nmutating {len(session_paths)} session(s) in {args.sessions_dir}")

    n_changed = 0
    n_skipped = 0
    for p in session_paths:
        try:
            with p.open() as f:
                blob = json.load(f)
        except Exception as ex:
            print(f"  {p.name}: parse error: {ex}")
            continue
        start = blob.get("start")
        end = blob.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            print(f"  {p.name}: missing start/end — skipping")
            n_skipped += 1
            continue

        already_populated = any(
            isinstance(blob.get(field), list) and blob.get(field)
            for field in SLOT_TO_FIELD.values()
        ) or blob.get("charge_at_start") is not None

        if already_populated and not args.force:
            print(f"  {p.name}: already has samples — skipping (use --force to overwrite)")
            n_skipped += 1
            continue

        windowed = collect_window(store, start, end)
        cas = find_charge_at_start(store, start)

        if not windowed and cas is None:
            print(f"  {p.name}: no probe events in window [{start},{end}] — skipping")
            n_skipped += 1
            continue

        for field, samples in windowed.items():
            blob[field] = samples
        if cas is not None:
            blob["charge_at_start"] = cas

        summary = ", ".join(
            f"{field.removesuffix('_samples')}={len(blob[field])}"
            for field in SLOT_TO_FIELD.values()
            if field in blob
        )
        duration_min = max(0, (end - start) // 60)
        print(
            f"  {p.name}: +{summary}"
            f"{f', charge_at_start={cas}' if cas is not None else ''}"
            f"  ({duration_min} min span)"
        )

        if not args.dry_run:
            tmp = p.with_suffix(".json.tmp")
            with tmp.open("w") as f:
                json.dump(blob, f, separators=(",", ":"))
            os.replace(tmp, p)
        n_changed += 1

    print(f"\ndone: {n_changed} mutated, {n_skipped} skipped, {len(session_paths)} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
