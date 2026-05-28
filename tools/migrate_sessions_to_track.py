#!/usr/bin/env python3
"""migrate_sessions_to_track.py — convert old session archives to the
per-point `track` + `cloud_track` format introduced by the 2026-05-28
session-replay rewrite.

This is a dev-box, one-shot MIGRATION tool — distinct from
`rebuild_session.py` (an accreted additive-backfill tool). It:

  * iterates EVERY HA session archive (not just probe-covered windows),
  * reconstructs the per-point `track` from probe s1p4 MQTT (truth:
    timestamps + area + heading), classified by area-delta,
  * stores `cloud_track` verbatim from the archive's own cloud summary
    (used only to sanity-check mowing/traversal; absent for >1-week-old
    sessions whose OSS blob the cloud has purged — that's fine),
  * refines roles with cloud-coverage rescue + smoothing,
  * strips ALL legacy leg keys,
  * backs up every pulled archive locally BEFORE touching anything.

Safety: defaults to DRY-RUN. Nothing is pushed back to HA unless --apply
is passed. A local pre-conversion backup is always written.

No-homeassistant constraint: the dev box has no HA install, and importing
any `custom_components.dreame_a2_mower.*` module runs the package
__init__ which imports homeassistant. So every integration helper here is
loaded via the standalone spec-loader (`_load_decoder_module`) — never a
package import. classify.py / coordinator can't be spec-loaded (relative
+ HA imports), so the tiny area-delta + cloud-rescue + smoothing classify
is inlined below (canonical source: live_map/classify.py).

Usage:
  tools/migrate_sessions_to_track.py                 # dry-run, backup + report
  tools/migrate_sessions_to_track.py --apply         # actually push to HA
  tools/migrate_sessions_to_track.py --force         # re-migrate new-format too
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
import zoneinfo
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools._rebuild_session_lib.ha_archive import HAArchiveFetcher  # noqa: E402
from tools._rebuild_session_lib.probe_reader import ProbeReader  # noqa: E402
from tools._rebuild_session_lib.track_replay import reconstruct_track  # noqa: E402
from tools._rebuild_session_lib.wifi_replay import _load_decoder_module  # noqa: E402

# Legacy trail keys removed by the rewrite — stripped on migration.
LEG_KEYS = ("legs", "_local_legs", "_legs_meta", "_mowing_legs", "_traversal_legs")

_SMOOTH_PASSES = 3
# Capture past the cloud's session-end so the drive-home-to-dock (which the
# cloud excludes but the probe records) lands in the track. The dock-return
# is short (~1-2 min); the stationary charge after it dedups to ~1 point.
_DOCK_RETURN_BUFFER_S = 600


def extract_cloud_track(archive: dict[str, Any]) -> list[list[list[float]]]:
    """Verbatim cloud mowing segments from the archive's own summary.

    Returns list of segments, each a list of [x, y]. Empty list when the
    archive has no parseable cloud track (e.g. OSS purged for old sessions).
    """
    try:
        ss = _load_decoder_module("session_summary")
        summary = ss.parse_session_summary(archive)
        return [
            [[float(p[0]), float(p[1])] for p in seg]
            for seg in (summary.track_segments or ())
        ]
    except Exception:
        return []


def classify(track: list[dict], *, smooth_passes: int = _SMOOTH_PASSES) -> list[dict]:
    """Smooth isolated role stutters (mutates + returns track). Mirrors
    live_map/classify.py:classify_track — smoothing only. Area-delta (set in
    reconstruct_track) is authoritative; cloud-coverage rescue was dropped
    because on a full-lawn mow it can't tell a cross-area traversal (driving
    over already-mowed grass) from real mowing — both sit on the cloud path."""
    if not track:
        return track
    for _ in range(max(0, smooth_passes)):
        roles = [p["role"] for p in track]
        changed = False
        for i in range(1, len(track) - 1):
            if roles[i - 1] == roles[i + 1] and track[i]["role"] != roles[i - 1]:
                track[i]["role"] = roles[i - 1]
                changed = True
        if not changed:
            break
    return track


def is_new_format(archive: dict[str, Any]) -> bool:
    """True when the archive is already migrated: has track + cloud_track and
    carries no legacy leg keys."""
    return (
        "track" in archive
        and "cloud_track" in archive
        and not any(k in archive for k in LEG_KEYS)
    )


def convert_archive(
    archive: dict[str, Any], reader: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (new_archive, stats). Pure aside from `reader` queries.

    new_archive = archive minus leg keys, plus `track` (rows) + `cloud_track`.
    """
    start_ts = int(archive.get("start") or 0)
    end_ts = int(archive.get("end") or 0)

    new = dict(archive)
    had_legs = any(k in archive for k in LEG_KEYS)
    for k in LEG_KEYS:
        new.pop(k, None)

    track: list[dict] = []
    if start_ts and end_ts:
        # Extend past the cloud session-end to capture the drive-home-to-dock
        # (the cloud excludes it; the probe records it). reconstruct_track's
        # 20cm/0.5s dedup collapses the stationary at-dock charge that follows.
        track = reconstruct_track(reader, start_ts, end_ts + _DOCK_RETURN_BUFFER_S)

    cloud_track = extract_cloud_track(archive)
    classify(track)

    new["track"] = [
        [p["t"], p["x_m"], p["y_m"], p["area_m2"], p["heading_deg"],
         p["task_state"], p["role"]]
        for p in track
    ]
    new["cloud_track"] = cloud_track

    mowing = sum(1 for p in track if p["role"] == "mowing")
    stats = {
        "track_points": len(track),
        "mowing_points": mowing,
        "traversal_points": len(track) - mowing,
        "cloud_segments": len(cloud_track),
        "had_legs": had_legs,
    }
    return new, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually push converted archives back to HA. Default: dry-run.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-migrate archives that are already in the new format.",
    )
    parser.add_argument(
        "--probe-glob",
        default="/data/claude/homeassistant/probe_log_*.jsonl",
    )
    parser.add_argument(
        "--tz", default="Europe/Oslo",
        help="Timezone the probe-log naive timestamps are in. MUST match how "
             "the probe captured them, or s1p4 events shift out of session "
             "windows and tracks come out empty (matches rebuild_session).",
    )
    parser.add_argument(
        "--ha-cred-file",
        default="/data/claude/homeassistant/ha-credentials.txt",
    )
    parser.add_argument(
        "--ha-sessions-dir",
        default="/config/dreame_a2_mower/sessions",
    )
    parser.add_argument(
        "--backup-dir", default=None,
        help="Local dir for pre-conversion archive backup + converted output. "
             "Default: /data/claude/homeassistant/session_migrate_<timestamp>/",
    )
    args = parser.parse_args(argv)

    dry_run = not args.apply

    probes = sorted(glob.glob(args.probe_glob))
    if not probes:
        print(f"No probe logs match {args.probe_glob}", file=sys.stderr)
        return 2
    print(f"Loading {len(probes)} probe file(s)… (tz={args.tz})", file=sys.stderr)
    reader = ProbeReader(probes, tz=zoneinfo.ZoneInfo(args.tz))

    cred_lines = Path(args.ha_cred_file).read_text().strip().split("\n")
    host, user, password = cred_lines[0], cred_lines[1], cred_lines[2]
    fetcher = HAArchiveFetcher(
        host=host, user=user, password=password,
        remote_dir=args.ha_sessions_dir, dry_run=dry_run,
    )

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = Path(args.backup_dir or f"/data/claude/homeassistant/session_migrate_{stamp}")
    backup_dir = base / "pre_conversion"
    out_dir = base / "converted"
    backup_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    archives = fetcher.list_archives()
    print(f"HA archives found: {len(archives)}", file=sys.stderr)
    print(f"{'MODE: DRY-RUN (no push)' if dry_run else 'MODE: APPLY (will push)'}")
    print(f"Backup dir:    {backup_dir}")
    print(f"Converted dir: {out_dir}")
    print()

    migrated: list[tuple[str, dict]] = []
    empty_track: list[str] = []
    skipped_new = 0
    failed = 0

    for a in archives:
        local_raw = backup_dir / a.raw
        try:
            fetcher.fetch_archive(a.raw, local_raw)
            archive = json.loads(local_raw.read_text())
        except Exception as ex:
            print(f"  fetch/parse failed {a.raw}: {ex}", file=sys.stderr)
            failed += 1
            continue

        if is_new_format(archive) and not args.force:
            skipped_new += 1
            continue

        try:
            new_archive, stats = convert_archive(archive, reader)
        except Exception as ex:
            print(f"  convert failed {a.raw}: {ex}", file=sys.stderr)
            failed += 1
            continue

        (out_dir / a.raw).write_text(json.dumps(new_archive, indent=2))
        migrated.append((a.raw, stats))
        if stats["track_points"] == 0:
            empty_track.append(a.raw)

        flag = "" if not dry_run else " (dry-run)"
        print(
            f"  {a.raw}: track={stats['track_points']} "
            f"(mow={stats['mowing_points']}/trav={stats['traversal_points']}) "
            f"cloud_segs={stats['cloud_segments']} had_legs={stats['had_legs']}{flag}"
        )
        if not dry_run:
            try:
                fetcher.push_archive(out_dir / a.raw, a.raw)
            except Exception as ex:
                print(f"    push failed: {ex}", file=sys.stderr)
                failed += 1

    print()
    print("=== Summary ===")
    print(f"  Archives:            {len(archives)}")
    print(f"  Migrated:            {len(migrated)}")
    print(f"  Skipped (new fmt):   {skipped_new}")
    print(f"  Failed:              {failed}")
    print(f"  Backup (pre-conv):   {backup_dir}")
    print(f"  Converted output:    {out_dir}")
    if empty_track:
        print()
        print(f"  EMPTY track ({len(empty_track)}) — no probe s1p4 in window "
              f"(pre-probe-era; migrated to clean format but won't render a trail):")
        for fn in empty_track:
            print(f"    {fn}")
    if dry_run:
        print()
        print("  DRY-RUN — nothing pushed. Re-run with --apply to write back to HA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
