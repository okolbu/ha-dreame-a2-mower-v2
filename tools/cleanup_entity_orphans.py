#!/usr/bin/env python3
"""Delete orphan entity-registry entries left over from the multiple
per-map naming-scheme changes (Phase 2 sub-device split, double-prefix
fix, v1.0.11a4 namespace consolidation).

Usage:
    python3 tools/cleanup_entity_orphans.py [--dry-run] [--ha-host HOST]

Reads HA URL + token from /data/claude/homeassistant/ha-credentials.txt
unless overridden. Lists every dreame_a2_mower entity in HA's registry,
classifies orphans by pattern, prints the table, and (in non-dry-run
mode) prompts before deleting each one.

Classification rules:

  - "doubled-prefix": entity_id slug contains map_N_map_N_ (the 2026-05-13
     bug fixed in v1.0.10a8). These never had a working entity_id; the
     class re-registered under a clean slug, leaving these stranded.
  - "bare map_N":   entity_id slug starts with `map_1_*` or `map_2_*` but
     not the doubled form. Created when per-map sub-devices were named
     just "Map N+1"; v1.0.11a4 namespaced the device name so re-registration
     lands at `dreame_a2_mower_map_N_*`.
  - "dead class":   the integration class that originally created this
     entity no longer exists. Currently known: `select.dreame_a2_mower_wifi_view`.
  - "entry-id-uid": unique_id starts with a ULID-shaped prefix (26 chars
     of [0-9A-Z]) — registered before SN-based identifiers were the
     fallback. Replaced by SN-uid entries with a numeric `_2` suffix.
  - "per-map at parent slug": unique_id contains `_map_N_*` (per-map entity)
     but the entity_id is slugged at the parent prefix `dreame_a2_mower_*`.
     Pre-Phase-2 registration. v1.0.11a4 puts new registrations at
     `dreame_a2_mower_map_N_*`; deletion lets HA re-register fresh.

This script ONLY deletes entries it can match into one of these buckets.
Anything else (the 159+ correctly-named parent-device entities) is left
untouched.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import websocket  # pip install websocket-client


DREAME_CREDS = "/data/claude/homeassistant/ha-credentials.txt"
DEFAULT_HOST = "10.0.0.30"
DEFAULT_PORT = 8123

# Unique_ids of entities whose integration class was deleted.
DEAD_CLASS_UIDS = {
    "G2408053AEE0006232_wifi_view",
}

# ULID-shaped: 26 chars of Crockford base32. Catches the legacy
# entry-id fallback uids.
_ULID_PREFIX = re.compile(r"^[0-9A-Z]{26}_")


def classify(eid: str, uid: str) -> tuple[str | None, str]:
    """Return (bucket, reason) for an orphan, or (None, "") if not an orphan."""
    plat, slug = eid.split(".", 1)

    if "map_1_map_1_" in slug or "map_2_map_2_" in slug:
        return ("doubled-prefix", "slug carries the duplicated map_N_map_N_ prefix")

    if (slug.startswith("map_1_") or slug.startswith("map_2_")) and not slug.startswith(
        ("map_1_map_", "map_2_map_")
    ):
        return ("bare map_N", "slug lacks integration prefix")

    if uid in DEAD_CLASS_UIDS:
        return ("dead class", "originating class removed from integration")

    if _ULID_PREFIX.match(uid):
        return ("entry-id-uid", "uid uses pre-SN entry-id fallback")

    # Per-map entity (uid contains _map_N_) slugged at parent prefix.
    m = re.match(r"^[^_]+_map_(\d+)_", uid)
    if m:
        target = f"dreame_a2_mower_map_{int(m.group(1)) + 1}_"
        # Two acceptable forms: the new namespaced slug, or a sub-pattern
        # we shouldn't touch (e.g. the wifi_heatmap/lidar cameras under
        # the new device — those will register at the new slug after
        # this entry is deleted).
        if not slug.startswith(target):
            return (
                "per-map at parent slug",
                f"uid maps to map_id={m.group(1)} but slug isn't {target}*",
            )

    return (None, "")


def ws_connect(host: str, port: int, token: str) -> websocket.WebSocket:
    ws = websocket.create_connection(f"ws://{host}:{port}/api/websocket")
    ws.recv()  # auth_required
    ws.send(json.dumps({"type": "auth", "access_token": token}))
    auth_resp = json.loads(ws.recv())
    if auth_resp.get("type") != "auth_ok":
        print(f"auth failed: {auth_resp}", file=sys.stderr)
        sys.exit(1)
    return ws


def list_entities(ws: websocket.WebSocket) -> list[dict]:
    ws.send(json.dumps({"id": 1, "type": "config/entity_registry/list"}))
    res = json.loads(ws.recv())
    return [e for e in res["result"] if e.get("platform") == "dreame_a2_mower"]


def delete_entity(ws: websocket.WebSocket, eid: str, req_id: int) -> dict:
    ws.send(
        json.dumps(
            {
                "id": req_id,
                "type": "config/entity_registry/remove",
                "entity_id": eid,
            }
        )
    )
    return json.loads(ws.recv())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List orphans, do not delete (default behaviour requires --yes).",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the per-batch confirmation prompt and delete unconditionally.",
    )
    p.add_argument("--ha-host", default=DEFAULT_HOST)
    p.add_argument("--ha-port", type=int, default=DEFAULT_PORT)
    p.add_argument("--creds", default=DREAME_CREDS,
                   help="Path to HA credentials file (4th line = long-lived token).")
    args = p.parse_args(argv)

    with open(args.creds) as f:
        token = f.readlines()[3].strip()

    ws = ws_connect(args.ha_host, args.ha_port, token)
    entries = list_entities(ws)
    print(f"Scanned {len(entries)} dreame_a2_mower registry entries.\n")

    orphans: list[tuple[str, str, str, str]] = []  # (bucket, eid, uid, reason)
    for e in entries:
        eid = e["entity_id"]
        uid = e.get("unique_id", "")
        bucket, reason = classify(eid, uid)
        if bucket:
            orphans.append((bucket, eid, uid, reason))

    if not orphans:
        print("No orphans found. Registry is clean.")
        ws.close()
        return 0

    # Group by bucket for the report.
    from collections import defaultdict
    by_bucket: dict[str, list] = defaultdict(list)
    for o in orphans:
        by_bucket[o[0]].append(o)

    for bucket, items in by_bucket.items():
        print(f"[{bucket}] {len(items)}")
        for _, eid, uid, _ in sorted(items):
            print(f"  {eid:60}  uid={uid}")
        print()

    print(f"Total: {len(orphans)} orphans.\n")

    if args.dry_run:
        print("Dry-run mode — no entries deleted. Re-run without --dry-run "
              "(and with --yes to skip the prompt) to apply.")
        ws.close()
        return 0

    if not args.yes:
        ans = input(f"Delete all {len(orphans)} entries? Type 'yes' to confirm: ")
        if ans.strip().lower() != "yes":
            print("Aborted — no entries deleted.")
            ws.close()
            return 0

    req_id = 100
    deleted = 0
    failed: list[tuple[str, str]] = []
    for bucket, eid, uid, _ in orphans:
        req_id += 1
        res = delete_entity(ws, eid, req_id)
        if res.get("success"):
            print(f"  deleted: {eid}")
            deleted += 1
        else:
            err = res.get("error", {}).get("message", str(res))
            print(f"  FAILED:  {eid}  → {err}")
            failed.append((eid, err))

    print(f"\nDone. {deleted}/{len(orphans)} deleted.")
    if failed:
        print(f"{len(failed)} failures:")
        for eid, err in failed:
            print(f"  {eid}  → {err}")

    print("\nReload the integration (Settings → Devices → Dreame A2 Mower → "
          "options → Reload) or restart HA so the entities re-register under "
          "the v1.0.11a4 namespaced slugs.")
    ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
