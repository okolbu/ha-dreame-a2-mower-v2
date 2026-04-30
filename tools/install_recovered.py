#!/usr/bin/env python3
"""Install recovered sessions onto a live HA.

Reads tools/recovered_sessions/index_recovered.json, filters out
sessions whose duration looks bogus (probe gap → missed
end-transition), skips entries whose start_ts already exists in
the live index, SCPs the chosen JSONs into the on-HA archive
directory, merges them into the live index.json, then reloads
the integration via the REST API.

Suspect-session filter:
  - duration_min > 500: skip
  - area / duration < 0.05 AND duration > 90: skip

(Keeps real long all-area mows ~270-340 min while excluding the
"session never closed because probe was off" cases.)

Run from the repo root after `tools/recover_sessions.py` has
populated `tools/recovered_sessions/`. Requires `sshpass` and the
ha-credentials.txt next to the homeassistant directory. Idempotent
— rerun is safe.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# CLI / config
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RECOVERED = _REPO_ROOT / "tools" / "recovered_sessions"
_DEFAULT_CREDS = Path("/data/claude/homeassistant/ha-credentials.txt")
_REMOTE_SESSIONS_DIR = "/config/dreame_a2_mower/sessions"
_REMOTE_INDEX = f"{_REMOTE_SESSIONS_DIR}/index.json"


def _load_creds(creds_path: Path) -> tuple[str, str, str]:
    lines = creds_path.read_text().splitlines()
    return lines[0].strip(), lines[1].strip(), lines[2].strip()  # host, user, pwd


# ---------------------------------------------------------------------------
# Suspect-session filter
# ---------------------------------------------------------------------------


def is_suspect(entry: dict) -> tuple[bool, str]:
    """Return (skip?, reason)."""
    dur = int(entry.get("duration_min") or 0)
    area = float(entry.get("area_mowed_m2") or 0.0)
    if dur > 500:
        return True, f"duration_min={dur} > 500 (probe gap)"
    if dur > 90 and area / max(dur, 1) < 0.05:
        return True, (
            f"area/duration ratio {area / max(dur, 1):.3f} m²/min < 0.05 "
            f"and duration_min={dur} (likely missed end-transition)"
        )
    return False, ""


# ---------------------------------------------------------------------------
# Live-HA interactions
# ---------------------------------------------------------------------------


def _ssh(host: str, user: str, pwd: str, cmd: str) -> str:
    return subprocess.check_output(
        [
            "sshpass",
            "-p",
            pwd,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            f"{user}@{host}",
            cmd,
        ],
        text=True,
    )


def _scp(host: str, user: str, pwd: str, local: Path, remote: str) -> None:
    subprocess.run(
        [
            "sshpass",
            "-p",
            pwd,
            "scp",
            "-o",
            "StrictHostKeyChecking=no",
            str(local),
            f"{user}@{host}:{remote}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def fetch_live_index(host: str, user: str, pwd: str) -> dict:
    raw = _ssh(host, user, pwd, f"cat {_REMOTE_INDEX}")
    return json.loads(raw)


def push_live_index(host: str, user: str, pwd: str, index: dict, tmp: Path) -> None:
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True))
    _scp(host, user, pwd, tmp, _REMOTE_INDEX)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovered-dir", default=str(_DEFAULT_RECOVERED))
    parser.add_argument("--creds-file", default=str(_DEFAULT_CREDS))
    parser.add_argument(
        "--reload-entry-id",
        default="01KQARZG4K3QEAZ0WT1XFHKRQP",
        help="HA config entry id for the integration; reload via REST after install",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without copying anything",
    )
    args = parser.parse_args(argv)

    rec_dir = Path(args.recovered_dir)
    rec_index_path = rec_dir / "index_recovered.json"
    if not rec_index_path.exists():
        print(f"missing {rec_index_path} — run recover_sessions.py first", file=sys.stderr)
        return 1

    rec_index = json.loads(rec_index_path.read_text())
    rec_entries = rec_index.get("sessions") or []

    host, user, pwd = _load_creds(Path(args.creds_file))
    live_index = fetch_live_index(host, user, pwd)
    live_entries = live_index.get("sessions") or []
    live_start_ts = sorted(int(e.get("start_ts") or 0) for e in live_entries)

    # Probe-observed start_ts can lag the cloud's recorded start_ts by
    # 10-60 s (cloud takes the firmware-reported tick; probe takes the
    # MQTT push timestamp). Match within ±5 min so the same physical mow
    # isn't installed twice.
    DEDUP_WINDOW_S = 5 * 60

    def overlaps_live(ts: int) -> bool:
        for live_ts in live_start_ts:
            if abs(live_ts - ts) <= DEDUP_WINDOW_S:
                return True
        return False

    plan_install: list[dict] = []
    plan_skip: list[tuple[dict, str]] = []
    for entry in rec_entries:
        suspect, reason = is_suspect(entry)
        if suspect:
            plan_skip.append((entry, f"suspect: {reason}"))
            continue
        st = int(entry.get("start_ts") or 0)
        if overlaps_live(st):
            plan_skip.append((entry, f"start_ts={st} within ±{DEDUP_WINDOW_S}s of a live entry"))
            continue
        plan_install.append(entry)

    print(f"recovered: {len(rec_entries)}")
    print(f"  → install: {len(plan_install)}")
    print(f"  → skip:    {len(plan_skip)}")
    print()
    print("INSTALL:")
    for e in plan_install:
        print(
            f"  {e['filename']}  start_ts={e['start_ts']} "
            f"dur={e['duration_min']}min area={e['area_mowed_m2']}m²"
        )
    print()
    print("SKIP:")
    for e, why in plan_skip:
        print(
            f"  {e['filename']}  start_ts={e['start_ts']} "
            f"dur={e['duration_min']}min area={e['area_mowed_m2']}m² — {why}"
        )

    if args.dry_run:
        print("\n--dry-run; no changes made")
        return 0

    if not plan_install:
        print("\nnothing to install")
        return 0

    print(f"\ncopying {len(plan_install)} JSONs to {_REMOTE_SESSIONS_DIR}...")
    for e in plan_install:
        local = rec_dir / e["filename"]
        remote = f"{_REMOTE_SESSIONS_DIR}/{e['filename']}"
        _scp(host, user, pwd, local, remote)

    merged = list(live_entries)
    merged.extend(plan_install)
    merged.sort(key=lambda x: int(x.get("end_ts") or 0))
    new_index = {"sessions": merged, "version": int(live_index.get("version", 1))}
    tmp_index = Path("/tmp/_dreame_index_merge.json")
    push_live_index(host, user, pwd, new_index, tmp_index)
    print(f"merged index now has {len(merged)} entries")

    import urllib.request

    token = Path(args.creds_file).read_text().splitlines()[3]
    req = urllib.request.Request(
        f"http://{host}:8123/api/config/config_entries/entry/{args.reload_entry_id}/reload",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
    print(f"integration reload: {body.strip()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
