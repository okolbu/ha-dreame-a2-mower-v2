#!/usr/bin/env python3
"""rebuild_session.py — end-to-end session rebuild from probe logs.

See docs/superpowers/specs/2026-05-16-session-rebuild-tool-design.md
for the full design.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import sys
import zoneinfo
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Put the repo root on sys.path so `from tools._rebuild_session_lib...` works
# regardless of the cwd from which the tool is invoked. The script lives at
# <repo>/tools/rebuild_session.py, so parent.parent is <repo>.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools._rebuild_session_lib.ha_archive import (  # noqa: E402
    HAArchiveFetcher,
)
from tools._rebuild_session_lib.legs_replay import reconstruct_legs  # noqa: E402
from tools._rebuild_session_lib.probe_reader import ProbeReader  # noqa: E402
from tools._rebuild_session_lib.samples_replay import backfill_samples  # noqa: E402
from tools._rebuild_session_lib.session_windows import (  # noqa: E402
    Window,
    detect_windows,
)
from tools._rebuild_session_lib.ha_archive import (  # noqa: E402
    ArchiveFilename,
)
from tools._rebuild_session_lib.state_replay import (  # noqa: E402
    charge_at_start,
    settings_snapshot_at_start,
)
from tools._rebuild_session_lib.wifi_replay import reconstruct_wifi_samples  # noqa: E402


@dataclass
class StreamDiff:
    in_archive: int
    in_probe: int
    added: int
    final: int


def _diff_and_merge_samples(
    archive_list: list,
    probe_list: list,
    *,
    ts_index: int = 0,
) -> tuple[StreamDiff, list]:
    """Union archive + probe sample lists, dedup on full-tuple equality.

    For sample arrays [ts, val] use the default ts_index=0.
    For wifi_samples [x, y, rssi, ts] pass ts_index=3.
    Returns (diff_counts, merged_list).
    """
    a = len(archive_list or [])
    p = len(probe_list or [])
    seen: set[tuple[int, ...]] = set()
    union: list = []
    for src in (archive_list or [], probe_list or []):
        for s in src:
            key = tuple(s)
            if key in seen:
                continue
            seen.add(key)
            union.append(list(s))
    union.sort(key=lambda s: s[ts_index])
    return StreamDiff(in_archive=a, in_probe=p, added=len(union) - a, final=len(union)), union


def rebuild_one_session(
    reader: ProbeReader,
    archive: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Rebuild a single session.

    Returns (new_archive, diff_report) where diff_report is a dict
    of stream_name -> {in_archive, in_probe, added, final}.
    """
    start_ts = int(archive["start"])
    end_ts = int(archive["end"])

    new = dict(archive)
    diff: dict[str, dict[str, Any]] = {}

    # 4 sample arrays
    samples = backfill_samples(reader, start_ts, end_ts)
    for field, probe_list in samples.items():
        d, union = _diff_and_merge_samples(archive.get(field) or [], probe_list)
        new[field] = union
        diff[field] = d.__dict__

    # wifi (may fail if integration decoders unavailable in dev environment)
    try:
        wifi_probe = [list(t) for t in reconstruct_wifi_samples(reader, start_ts, end_ts)]
    except ImportError as _e:
        print(f"  [warn] wifi decoder unavailable ({_e}); skipping wifi_samples", file=sys.stderr)
        wifi_probe = []
    d, union = _diff_and_merge_samples(
        archive.get("wifi_samples") or [], wifi_probe, ts_index=3,
    )
    new["wifi_samples"] = union
    diff["wifi_samples"] = d.__dict__

    # legs (different shape — list of lists of [x,y]; replace if probe has more total points)
    try:
        legs_probe = reconstruct_legs(reader, start_ts, end_ts)
    except ImportError as _e:
        print(f"  [warn] position decoder unavailable ({_e}); skipping legs", file=sys.stderr)
        legs_probe = []
    archive_legs = archive.get("legs") or []
    archive_pts = sum(len(leg) for leg in archive_legs)
    probe_pts = sum(len(leg) for leg in legs_probe)
    if probe_pts > archive_pts:
        new["legs"] = legs_probe
        diff["legs"] = {
            "in_archive": archive_pts, "in_probe": probe_pts,
            "added": probe_pts - archive_pts, "final": probe_pts,
        }
    else:
        diff["legs"] = {
            "in_archive": archive_pts, "in_probe": probe_pts,
            "added": 0, "final": archive_pts,
        }

    # charge_at_start
    cas_probe = charge_at_start(reader, start_ts)
    cas_archive = archive.get("charge_at_start")
    if cas_archive is None and cas_probe is not None:
        new["charge_at_start"] = cas_probe
        diff["charge_at_start"] = {
            "in_archive": "None", "in_probe": cas_probe,
            "added": 1, "final": cas_probe,
        }
    else:
        diff["charge_at_start"] = {
            "in_archive": cas_archive, "in_probe": cas_probe,
            "added": 0, "final": cas_archive,
        }

    # settings_snapshot
    snap_probe = settings_snapshot_at_start(reader, start_ts)
    snap_archive = archive.get("settings_snapshot") or {}
    if (snap_archive in (None, {})) and snap_probe:
        new["settings_snapshot"] = snap_probe
        diff["settings_snapshot"] = {
            "in_archive": 0, "in_probe": len(snap_probe),
            "added": len(snap_probe), "final": len(snap_probe),
        }
    else:
        diff["settings_snapshot"] = {
            "in_archive": len(snap_archive) if snap_archive else 0,
            "in_probe": len(snap_probe),
            "added": 0,
            "final": len(snap_archive) if snap_archive else 0,
        }

    return new, diff


def _print_diff(
    window: Window,
    archive_filename: str | None,
    diff: dict[str, dict[str, Any]],
    improved: bool,
) -> None:
    start_str = dt.datetime.fromtimestamp(window.start_ts).isoformat()
    print(f"=== Session {start_str} ({window.start_ts} -> {window.end_ts}) ===")
    print(f"  archive: {archive_filename or '(synthesizing new)'}")
    print(f"  {'stream':<28s} {'archive':>10s} {'probe':>10s} {'added':>10s} {'final':>10s}")
    for k, v in diff.items():
        ia = v.get("in_archive", "")
        ip = v.get("in_probe", "")
        ad = v.get("added", "")
        fn = v.get("final", "")
        print(f"  {k:<28s} {ia!s:>10s} {ip!s:>10s} {ad!s:>10s} {fn!s:>10s}")
    if improved:
        # sum only when 'added' is an integer
        total_added = sum(
            int(v["added"]) for v in diff.values()
            if isinstance(v.get("added"), int)
        )
        print(f"  decision: copy back to HA ({total_added} new datapoints)")
    else:
        print("  decision: skip (no improvements)")


def _hash_filename(start_ts: int, end_ts: int) -> str:
    h = hashlib.sha1(f"{start_ts}-{end_ts}".encode()).hexdigest()[:4]
    return f"rec_{h}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--session-start", type=str,
        help="ISO8601 or epoch seconds. Default mode is --bulk.",
    )
    grp.add_argument("--bulk", action="store_true")
    parser.add_argument(
        "--probe-glob",
        default="/data/claude/homeassistant/probe_log_*.jsonl",
    )
    parser.add_argument("--tz", default="Europe/Oslo")
    parser.add_argument(
        "--ha-cred-file",
        default="/data/claude/homeassistant/ha-credentials.txt",
    )
    parser.add_argument(
        "--ha-sessions-dir", default="/config/dreame_a2_mower/sessions",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    tz = zoneinfo.ZoneInfo(args.tz)
    probes = sorted(glob.glob(args.probe_glob))
    if not probes:
        print(f"No probe logs match {args.probe_glob}", file=sys.stderr)
        return 2

    print(f"Loading {len(probes)} probe file(s)...", file=sys.stderr)
    reader = ProbeReader(probes, tz=tz)

    cred_lines = Path(args.ha_cred_file).read_text().strip().split("\n")
    host, user, password = cred_lines[0], cred_lines[1], cred_lines[2]
    fetcher = HAArchiveFetcher(
        host=host, user=user, password=password,
        remote_dir=args.ha_sessions_dir, dry_run=args.dry_run,
    )

    # Build sub_state event timeline for detect_windows.
    # status[0] comes in two shapes on g2408:
    #   2-element: [task_id, sub_state]
    #   3-element: [task_id, sub_mode, ?]  (scheduled edge/spot/zone since 2026-04-27)
    # status[0][1] reads the right thing on 2-element entries. For 3-element
    # entries it reads the middle field (always 0), so a sub_state of 2 in
    # the third position is invisible — those sessions are session-end-signalled
    # by a later empty [] event, not by the [1,0,2] entry itself. Treating
    # [1,0,2] as session-end was tried 2026-05-16 and broke the 19h rain-paused
    # session case (where [1,0,2] mid-session is followed by 19h more activity).
    # For sessions where the probe lacks a closing [] event (e.g. HA restart),
    # the --session-start mode falls back to the HA archive's recorded start/end
    # below.
    s2p56 = reader.events_for_slot(2, 56)
    sub_state_events: list[tuple[int, int | None]] = []
    for ts, val in s2p56:
        sub = None
        if isinstance(val, dict):
            status = val.get("status") or []
            if status and isinstance(status[0], list) and len(status[0]) >= 2:
                try:
                    sub = int(status[0][1])
                except (TypeError, ValueError):
                    sub = None
        sub_state_events.append((ts, sub))
    windows = detect_windows(sub_state_events)
    print(f"Found {len(windows)} session windows in probe data.", file=sys.stderr)

    archives = fetcher.list_archives()
    archive_by_end = {a.end_ts: a for a in archives}

    # Single mode: filter
    if args.session_start:
        try:
            target = int(args.session_start)
        except ValueError:
            target = int(dt.datetime.fromisoformat(args.session_start).timestamp())
        matching = [w for w in windows if abs(w.start_ts - target) <= 300]
        if matching:
            windows = matching
        else:
            # Fallback: probe didn't catch a closed window near target. Most
            # often this is a session where the [] terminator never landed
            # (probe truncated, HA restart, or the 3-element [1,0,X] envelope
            # whose closing signal lives in a slot we don't track here). In
            # that case the HA archive is still the authoritative record — it
            # was written by the integration's session-end gate, which fuses
            # MQTT + cloud-summary signals. Look it up by `start` field.
            print(
                f"No probe-detected window matches {target} +/-300s; "
                f"checking HA archives by start_ts...", file=sys.stderr,
            )
            target_date = dt.datetime.fromtimestamp(target, tz).strftime("%Y-%m-%d")
            archive_window: Window | None = None
            for cand in archives:
                if cand.date != target_date:
                    continue
                tmp = Path(f"/tmp/rebuild_probe_{cand.end_ts}.json")
                try:
                    fetcher.fetch_archive(cand.raw, tmp)
                    content = json.loads(tmp.read_text())
                except Exception as ex:
                    print(f"  failed to inspect {cand.raw}: {ex}", file=sys.stderr)
                    continue
                arc_start = int(content.get("start", 0))
                arc_end = int(content.get("end", 0))
                if abs(arc_start - target) <= 300:
                    archive_window = Window(start_ts=arc_start, end_ts=arc_end)
                    print(
                        f"  matched archive {cand.raw}: "
                        f"start={dt.datetime.fromtimestamp(arc_start, tz).isoformat()} "
                        f"end={dt.datetime.fromtimestamp(arc_end, tz).isoformat()}",
                        file=sys.stderr,
                    )
                    break
            if archive_window is None:
                print(
                    f"No archive matches {target} +/-300s either", file=sys.stderr,
                )
                return 1
            windows = [archive_window]

    visited_end_ts: set[int] = set()
    rebuilt_count = skipped_count = failed_count = 0

    for w in windows:
        archive_meta = archive_by_end.get(w.end_ts)
        if archive_meta is not None:
            visited_end_ts.add(archive_meta.end_ts)
            tmp = Path(f"/tmp/rebuild_{archive_meta.end_ts}.json")
            try:
                fetcher.fetch_archive(archive_meta.raw, tmp)
                local_archive = json.loads(tmp.read_text())
                local_filename = archive_meta.raw
            except Exception as ex:
                print(f"  failed to fetch {archive_meta.raw}: {ex}", file=sys.stderr)
                failed_count += 1
                continue
        else:
            local_archive = {"start": w.start_ts, "end": w.end_ts}
            local_filename = (
                f"{dt.datetime.fromtimestamp(w.start_ts).strftime('%Y-%m-%d')}_"
                f"{w.end_ts}_{_hash_filename(w.start_ts, w.end_ts)}.json"
            )

        try:
            new_archive, diff = rebuild_one_session(reader, local_archive)
        except Exception as ex:
            print(f"  rebuild failed for {local_filename}: {ex}", file=sys.stderr)
            failed_count += 1
            continue

        improved = any(
            isinstance(v.get("added"), int) and int(v["added"]) > 0
            for v in diff.values()
        )
        _print_diff(w, local_filename, diff, improved)
        if improved:
            tmp_out = Path(f"/tmp/rebuild_{w.end_ts}_new.json")
            tmp_out.write_text(json.dumps(new_archive, indent=2))
            try:
                fetcher.push_archive(tmp_out, local_filename)
                rebuilt_count += 1
            except Exception as ex:
                print(f"  push failed: {ex}", file=sys.stderr)
                failed_count += 1
        else:
            skipped_count += 1

    print()
    print("=== Summary ===")
    print(f"Sessions in probe windows: {len(windows)}")
    print(f"  Backfilled: {rebuilt_count}")
    print(f"  Skipped:    {skipped_count}")
    print(f"  Failed:     {failed_count}")
    uncovered = [a for a in archives if a.end_ts not in visited_end_ts]
    if uncovered:
        print()
        print(f"Sessions in HA archive with NO probe coverage: {len(uncovered)}")
        for a in uncovered:
            print(f"  {args.ha_sessions_dir}/{a.raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
