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
# Extend with the literal uid (SN + key) when an entity class is
# removed from the integration. Entries here are deleted via
# config/entity_registry/remove (no rename target).
DEAD_CLASS_UIDS = {
    # Pre-v1.0.10 — DreameA2WifiViewSelect class deleted.
    "G2408053AEE0006232_wifi_view",
    # v1.0.11a5 — parent-level read-only/phantom-write surfaces
    # superseded by the per-map equivalents:
    "G2408053AEE0006232_edgemaster",
    "G2408053AEE0006232_mowing_efficiency",
    # v1.0.11a5 — per-map PRE-shadow sensor superseded by
    # DreameA2MapMowingEfficiencySelect:
    "G2408053AEE0006232_map_0_pre_mowing_efficiency",
    "G2408053AEE0006232_map_1_pre_mowing_efficiency",
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


def update_entity_id(
    ws: websocket.WebSocket, eid: str, new_eid: str, req_id: int
) -> dict:
    """Rename a registry entry directly. Survives reloads/restarts.

    Delete-then-reload doesn't actually rename the slug — HA caches the
    old entity_id internally and re-registration picks it up again
    (see _migration.py:_migrate_double_prefix_mowing_mode_orphans for
    the prior verification of this behavior).
    """
    ws.send(
        json.dumps(
            {
                "id": req_id,
                "type": "config/entity_registry/update",
                "entity_id": eid,
                "new_entity_id": new_eid,
            }
        )
    )
    return json.loads(ws.recv())


def compute_new_entity_id(eid: str, uid: str, bucket: str) -> str | None:
    """Return the desired v1.0.11a4-namespaced entity_id for an orphan.

    Algorithm (by bucket):

    - "doubled-prefix" (slug ``<platform>.map_N_map_N_<key>``):
        new = ``<platform>.dreame_a2_mower_map_N_<key>``
    - "bare map_N"     (slug ``<platform>.map_N_<key>``):
        new = ``<platform>.dreame_a2_mower_map_N_<key>``
    - "per-map at parent slug" (slug ``<platform>.dreame_a2_mower_<key>``,
       uid carries ``_map_N_``):
        new = ``<platform>.dreame_a2_mower_map_N_<key>``

    Buckets "dead class" and "entry-id-uid" don't get renamed — they're
    deleted (the originating class is gone or replaced).

    Two cleanups applied to every output:
    - Trailing ``_2``/``_3`` etc. is stripped (HA's auto-suffix from
      historic slug collisions; the live class no longer collides so
      the suffix is just noise).
    - The legacy slug ``camera.<...>_map_N`` (the per-map base camera's
      pre-namespace slug, where its only suffix WAS the map number) is
      mapped to ``camera.dreame_a2_mower_map_N_base`` — matches the
      class's current ``_attr_name = "Base"``.
    """
    plat, slug = eid.split(".", 1)

    if bucket == "doubled-prefix":
        m = re.match(r"^map_([12])_map_\1_(.+)$", slug)
        if not m:
            return None
        new = f"{plat}.dreame_a2_mower_map_{m.group(1)}_{m.group(2)}"
    elif bucket == "bare map_N":
        m = re.match(r"^map_([12])_(.+)$", slug)
        if not m:
            return None
        new = f"{plat}.dreame_a2_mower_map_{m.group(1)}_{m.group(2)}"
    elif bucket == "per-map at parent slug":
        uid_m = re.match(r"^[^_]+_map_(\d+)_", uid)
        if not uid_m:
            return None
        map_n = int(uid_m.group(1)) + 1
        if not slug.startswith("dreame_a2_mower_"):
            return None
        suffix = slug[len("dreame_a2_mower_"):]
        # Special case: the per-map base camera's slug was just
        # `..._map_N` (the map number was the only suffix). The class
        # now uses `_attr_name = "Base"`.
        if plat == "camera" and re.fullmatch(r"map_[12]", suffix):
            return f"camera.dreame_a2_mower_{suffix}_base"
        new = f"{plat}.dreame_a2_mower_map_{map_n}_{suffix}"
    else:
        return None

    # Strip historic auto-suffix `_2`/`_3` etc.
    new = re.sub(r"_\d+$", "", new)
    return new


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

    # Compute rename plan. Buckets with a rename target are renamed via
    # update_entity; "dead class" / "entry-id-uid" go via remove.
    renames: list[tuple[str, str, str]] = []  # (eid, new_eid, bucket)
    deletions: list[tuple[str, str]] = []     # (eid, bucket)
    existing_eids = {e["entity_id"] for e in entries}

    for bucket, eid, uid, _ in orphans:
        if bucket in ("dead class", "entry-id-uid"):
            deletions.append((eid, bucket))
            continue
        new_eid = compute_new_entity_id(eid, uid, bucket)
        if new_eid is None:
            print(f"  [SKIP] {eid} — no rename target computable (bucket={bucket})")
            continue
        if new_eid == eid:
            continue  # already in the right slug
        if new_eid in existing_eids and new_eid != eid:
            print(f"  [SKIP] {eid} → {new_eid} — target slug already exists")
            continue
        renames.append((eid, new_eid, bucket))

    print(f"\nPlan: {len(renames)} rename(s), {len(deletions)} delete(s).")
    if renames:
        print("\nRenames:")
        for eid, new_eid, _ in sorted(renames):
            print(f"  {eid:60} → {new_eid}")
    if deletions:
        print("\nDeletions:")
        for eid, _ in sorted(deletions):
            print(f"  {eid}")

    if args.dry_run:
        print("\nDry-run mode — nothing applied. Re-run without --dry-run "
              "(and with --yes to skip the prompt) to apply.")
        ws.close()
        return 0

    if not args.yes:
        ans = input(
            f"\nApply {len(renames)} renames + {len(deletions)} deletes? "
            "Type 'yes' to confirm: "
        )
        if ans.strip().lower() != "yes":
            print("Aborted — no changes applied.")
            ws.close()
            return 0

    req_id = 100
    renamed_count = 0
    deleted_count = 0
    failed: list[tuple[str, str]] = []

    for eid, new_eid, _ in renames:
        req_id += 1
        res = update_entity_id(ws, eid, new_eid, req_id)
        if res.get("success"):
            print(f"  renamed: {eid} → {new_eid}")
            renamed_count += 1
        else:
            err = res.get("error", {}).get("message", str(res))
            print(f"  FAILED rename: {eid} → {new_eid}  → {err}")
            failed.append((f"rename {eid} → {new_eid}", err))

    for eid, _ in deletions:
        req_id += 1
        res = delete_entity(ws, eid, req_id)
        if res.get("success"):
            print(f"  deleted: {eid}")
            deleted_count += 1
        else:
            err = res.get("error", {}).get("message", str(res))
            print(f"  FAILED delete: {eid}  → {err}")
            failed.append((f"delete {eid}", err))

    print(f"\nDone. {renamed_count}/{len(renames)} renamed, "
          f"{deleted_count}/{len(deletions)} deleted.")
    if failed:
        print(f"{len(failed)} failures:")
        for what, err in failed:
            print(f"  {what}  → {err}")

    print(
        "\nNo HA restart needed — renames are immediate. The integration "
        "keeps providing the entities at their new slugs without interruption.\n"
        "Update the dashboard if any references still point at the old slugs."
    )
    ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
