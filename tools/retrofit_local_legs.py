#!/usr/bin/env python3
"""Inject `_local_legs` into live-archive JSONs that pre-date v1.0.0a54.

Background: g2408's cloud session_summary JSON for spot/zone mows
omits ``track`` / ``old_track`` entirely. Sessions archived before
the v1.0.0a54 fix (which started persisting ``live_map.legs`` as
``_local_legs`` before archive) therefore have no path data.

This tool reads each live-archive session JSON over SSH; for every
one that lacks ``_local_legs``, it looks for a recovered session in
``tools/recovered_sessions/`` whose start_ts is within ±5 min, and
patches the live JSON in place with that recovered ``_local_legs``.
The synthetic md5 of the recovered file is NOT carried over — only
the legs.

Idempotent: a session already carrying ``_local_legs`` is skipped.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RECOVERED = _REPO_ROOT / "tools" / "recovered_sessions"
_DEFAULT_CREDS = Path("/data/claude/homeassistant/ha-credentials.txt")
_REMOTE_DIR = "/config/dreame_a2_mower/sessions"
DEDUP_WINDOW_S = 5 * 60


def _load_creds(path: Path) -> tuple[str, str, str]:
    lines = path.read_text().splitlines()
    return lines[0].strip(), lines[1].strip(), lines[2].strip()


def _ssh(host: str, user: str, pwd: str, cmd: str) -> str:
    return subprocess.check_output(
        ["sshpass", "-p", pwd, "ssh", "-o", "StrictHostKeyChecking=no",
         f"{user}@{host}", cmd],
        text=True,
    )


def _scp_to(host: str, user: str, pwd: str, local: Path, remote: str) -> None:
    subprocess.run(
        ["sshpass", "-p", pwd, "scp", "-o", "StrictHostKeyChecking=no",
         str(local), f"{user}@{host}:{remote}"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _scp_from(host: str, user: str, pwd: str, remote: str, local: Path) -> None:
    subprocess.run(
        ["sshpass", "-p", pwd, "scp", "-o", "StrictHostKeyChecking=no",
         f"{user}@{host}:{remote}", str(local)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovered-dir", default=str(_DEFAULT_RECOVERED))
    parser.add_argument("--creds-file", default=str(_DEFAULT_CREDS))
    parser.add_argument(
        "--reload-entry-id",
        default="01KQARZG4K3QEAZ0WT1XFHKRQP",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    rec_dir = Path(args.recovered_dir)
    rec_files = sorted(rec_dir.glob("2026-*.json"))
    rec_index: list[tuple[int, dict]] = []
    for p in rec_files:
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if "_local_legs" not in d:
            continue
        st = int(d.get("start", 0) or 0)
        if st > 0:
            rec_index.append((st, d))
    print(f"loaded {len(rec_index)} recovered sessions with _local_legs")

    host, user, pwd = _load_creds(Path(args.creds_file))

    raw_index = _ssh(host, user, pwd, f"cat {_REMOTE_DIR}/index.json")
    live_index = json.loads(raw_index)
    live_entries = live_index.get("sessions") or []
    print(f"live archive has {len(live_entries)} entries")

    patched = 0
    skipped_have = 0
    skipped_no_match = 0
    for entry in live_entries:
        fname = entry.get("filename")
        if not fname or fname.endswith("(incompl.json"):
            continue
        live_st = int(entry.get("start_ts") or 0)
        if live_st <= 0:
            continue
        # Pull the live JSON
        local_tmp = Path(f"/tmp/_live_{fname}")
        try:
            _scp_from(host, user, pwd, f"{_REMOTE_DIR}/{fname}", local_tmp)
            live_doc = json.loads(local_tmp.read_text())
        except Exception as ex:
            print(f"  skip {fname}: fetch failed ({ex})")
            continue
        if isinstance(live_doc.get("_local_legs"), list) and live_doc["_local_legs"]:
            skipped_have += 1
            continue
        # Find a matching recovered
        match = None
        for rec_st, rec_doc in rec_index:
            if abs(rec_st - live_st) <= DEDUP_WINDOW_S:
                match = rec_doc
                break
        if match is None:
            skipped_no_match += 1
            print(f"  no recovered match for {fname} (start_ts={live_st})")
            continue
        live_doc["_local_legs"] = match["_local_legs"]
        live_doc["_recovered_legs_from"] = (
            f"recover_sessions.py start_ts={int(match['start'])}"
        )
        n_pts = sum(len(l) for l in match["_local_legs"])
        print(f"  patch {fname}: +{n_pts} points from recovered start_ts={int(match['start'])}")
        if args.dry_run:
            continue
        local_tmp.write_text(json.dumps(live_doc, indent=2, sort_keys=True))
        _scp_to(host, user, pwd, local_tmp, f"{_REMOTE_DIR}/{fname}")
        patched += 1

    print(f"\npatched={patched} skipped_have_legs={skipped_have} no_recovered_match={skipped_no_match}")

    if patched and not args.dry_run:
        import urllib.request
        token = Path(args.creds_file).read_text().splitlines()[3]
        req = urllib.request.Request(
            f"http://{host}:8123/api/config/config_entries/entry/{args.reload_entry_id}/reload",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"integration reload: {resp.read().decode().strip()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
