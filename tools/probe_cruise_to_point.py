#!/usr/bin/env python3
"""Probe candidate cruise-to-point (op=109) payload shapes for g2408.

Background
----------
MQTT capture 2026-05-12 observed the cloud echo when the Dreame app
launched a point→point "Head to Maintenance Point" command::

    s2p50 = {t: TASK, d: {o: 109, exe: True, status: True, ...}}

Confirms op=109 is cruise-to-point on the new integration's TASK
envelope pipeline (s2.50). What the echo does NOT show is the
original ``d`` payload the app sent. So we probe candidate shapes.

The script uses ``DreameA2CloudClient.routed_action`` — the exact
same wire path the integration would use — so an accepted shape
here is guaranteed to work when wired into the integration.

Usage
-----
::

    # List maintenance points (need point_id + x_mm/y_mm)
    python3 tools/probe_cruise_to_point.py --list-points

    # Try one shape against point_id=1
    python3 tools/probe_cruise_to_point.py --point-id 1 --shape tpoint

    # Try each shape sequentially (stops at first cloud "success")
    python3 tools/probe_cruise_to_point.py --point-id 1 --auto

In another terminal, run ``probe_a2_mqtt.py`` so you can confirm
acceptance via the live MQTT echo (``s2p50 o:109 status:true``
followed by ``s2p56=[[N, 0]]`` lifecycle start). Cloud "success" in
the HTTP reply alone is necessary but not sufficient — the firmware
may also reject silently.

Credentials are read from ``DREAME_USER`` / ``DREAME_PASS`` env vars
or ``/data/claude/homeassistant/dreame-cloud-credentials.txt``
(username, password, country one per line).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


# --- Candidate d-payload shapes for op=109 ----------------------------------
#
# Each shape returns just the `d` field that gets wrapped into the TASK
# envelope by ``DreameA2CloudClient.routed_action(op=109, extra={"d": <here>})``.
# Shapes are tried in this order under ``--auto``.

def shape_tpoint(point_id: int, x_mm: int, y_mm: int) -> dict:
    """Legacy MIoT-style. From OLD/.../device.py:4938
    `start_custom(CRUISING_POINT, {"tpoint":[[x,y,0,0]]})`."""
    return {"tpoint": [[x_mm, y_mm, 0, 0]]}


def shape_point_coords(point_id: int, x_mm: int, y_mm: int) -> dict:
    """Minimal coord-list."""
    return {"point": [[x_mm, y_mm]]}


def shape_point_id(point_id: int, x_mm: int, y_mm: int) -> dict:
    """By reference — mirrors spot/zone's `area:[id]` / `region:[id]`."""
    return {"point": [point_id]}


def shape_cleanpoints_id(point_id: int, x_mm: int, y_mm: int) -> dict:
    """Reference using the OSS map blob key name."""
    return {"cleanPoints": [point_id]}


def shape_target_xy(point_id: int, x_mm: int, y_mm: int) -> dict:
    """Object form."""
    return {"target": {"x": x_mm, "y": y_mm}}


SHAPES: dict[str, callable] = {
    "tpoint": shape_tpoint,
    "point_coords": shape_point_coords,
    "point_id": shape_point_id,
    "cleanpoints_id": shape_cleanpoints_id,
    "target_xy": shape_target_xy,
}


# --- Credentials + client setup ----------------------------------------------

def _load_credentials() -> dict[str, str]:
    user = os.environ.get("DREAME_USER")
    passwd = os.environ.get("DREAME_PASS")
    country = os.environ.get("DREAME_COUNTRY", "eu")
    if user and passwd:
        return {"username": user, "password": passwd, "country": country}
    creds_file = Path("/data/claude/homeassistant/dreame-cloud-credentials.txt")
    if creds_file.is_file():
        lines = [l.strip() for l in creds_file.read_text().splitlines() if l.strip()]
        if len(lines) >= 2:
            return {
                "username": lines[0],
                "password": lines[1],
                "country": lines[2] if len(lines) >= 3 else country,
            }
    raise SystemExit(
        "No credentials. Set DREAME_USER / DREAME_PASS env vars or put "
        "username\\npassword\\n[country] in "
        "/data/claude/homeassistant/dreame-cloud-credentials.txt"
    )


def _build_cloud_client():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    creds = _load_credentials()
    client = DreameA2CloudClient(
        username=creds["username"],
        password=creds["password"],
        country=creds["country"],
    )
    if not client.login():
        raise SystemExit("login failed — check credentials")
    return client


# --- Send + report ------------------------------------------------------------

def reply_indicates_success(reply: Any) -> bool:
    """Heuristic match for an accepted routed_action reply.

    Cloud returns ``{"out": [{"r": 0, "d": {...}}]}`` on success and
    ``{"out": [{"r": -<errcode>, ...}]}`` or an outright exception on
    failure. The HTTP-side ``r: 0`` is necessary but NOT sufficient
    proof the firmware accepted — the user must watch MQTT for the
    s2p50 echo.
    """
    if not isinstance(reply, dict):
        return False
    out = reply.get("out") if isinstance(reply.get("out"), list) else None
    if not out:
        return False
    for entry in out:
        if isinstance(entry, dict) and entry.get("r") == 0:
            return True
    return False


def send_one(client, shape_name: str, point_id: int, x_mm: int, y_mm: int):
    shape_fn = SHAPES[shape_name]
    d_field = shape_fn(point_id, x_mm, y_mm)
    extra = {"d": d_field}
    print(f"→ shape={shape_name!r}  envelope d-field = {json.dumps(d_field, separators=(',', ':'))}")
    try:
        reply = client.routed_action(op=109, extra=extra)
    except Exception as ex:
        print(f"  ERROR: {ex!r}")
        return None
    print(f"  ← cloud reply: {json.dumps(reply, ensure_ascii=False)[:400]}")
    return reply


def auto_probe(client, point_id: int, x_mm: int, y_mm: int, pause_s: float):
    """Try each shape; stop at first cloud-side success."""
    for name in SHAPES:
        print()
        print("=" * 64)
        reply = send_one(client, name, point_id, x_mm, y_mm)
        if reply_indicates_success(reply):
            print()
            print(f"✓ shape={name!r}: cloud returned r=0 (HTTP success).")
            print(
                "  Watch the MQTT probe for `s2p50 o:109 status:true` and "
                "`s2p56=[[N,0]]` — those are the firmware-side confirmation. "
                "If the mower starts moving, this shape WORKS."
            )
            return name
        if pause_s > 0:
            time.sleep(pause_s)
    print("\n✗ no shape returned HTTP success. Try a custom payload via "
          "--shape and a fresh idea, or extend SHAPES.")
    return None


# --- Maintenance-point enumeration -------------------------------------------

def _decode_clean_points(map_data: dict) -> list[tuple[int, int, int]]:
    """Pull (point_id, x_mm, y_mm) tuples out of a map's cleanPoints field."""
    cp = map_data.get("cleanPoints")
    if isinstance(cp, dict):
        cp = cp.get("value", [])
    if not isinstance(cp, list):
        return []
    out = []
    for entry in cp:
        try:
            pt_id = int(entry[0])
            pt_data = entry[1]
            path = pt_data.get("path") or []
            if not path:
                continue
            first = path[0]
            x = int(first.get("x", 0))
            y = int(first.get("y", 0))
            out.append((pt_id, x, y))
        except (IndexError, TypeError, KeyError, ValueError):
            continue
    return out


def list_maintenance_points(client) -> None:
    parsed = client.fetch_map() or {}
    if not parsed:
        raise SystemExit("fetch_map returned nothing")
    print(f"Maps: {len(parsed)}")
    for map_id, map_data in sorted(parsed.items()):
        name = map_data.get("name") or f"Map {map_id + 1}"
        print(f"\n--- map_id={map_id}  name={name} ---")
        points = _decode_clean_points(map_data)
        if not points:
            print("  (no maintenance points)")
            continue
        for pt_id, x, y in points:
            print(f"  point_id={pt_id}  x_mm={x}  y_mm={y}")


def resolve_point(client, point_id: int) -> tuple[int, int]:
    """Find (x_mm, y_mm) for a given point_id across all maps."""
    parsed = client.fetch_map() or {}
    for map_data in parsed.values():
        for pt_id, x, y in _decode_clean_points(map_data):
            if pt_id == point_id:
                return x, y
    raise SystemExit(
        f"point_id={point_id} not found in any map; use --list-points"
    )


# --- Main --------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--list-points", action="store_true",
                   help="List maintenance points across all maps and exit.")
    p.add_argument("--shape", choices=sorted(SHAPES),
                   help="Try one specific payload shape.")
    p.add_argument("--auto", action="store_true",
                   help="Try every shape until cloud returns r=0.")
    p.add_argument("--point-id", type=int,
                   help="Maintenance point to target. Coords looked up unless "
                        "--x / --y given.")
    p.add_argument("--x", type=int, help="Override x_mm.")
    p.add_argument("--y", type=int, help="Override y_mm.")
    p.add_argument("--pause-between-shapes", type=float, default=2.0,
                   help="Seconds to wait between shapes in --auto mode "
                        "(lets the mower respond before next attempt).")
    args = p.parse_args()

    client = _build_cloud_client()

    if args.list_points:
        list_maintenance_points(client)
        return 0

    if args.point_id is None and (args.x is None or args.y is None):
        p.error("must specify --point-id (auto coords) or --x AND --y")

    if args.x is not None and args.y is not None:
        x_mm, y_mm = args.x, args.y
        point_id = args.point_id if args.point_id is not None else 0
    else:
        x_mm, y_mm = resolve_point(client, args.point_id)
        point_id = args.point_id
    print(f"Target: point_id={point_id}  x_mm={x_mm}  y_mm={y_mm}")

    if args.auto:
        auto_probe(client, point_id, x_mm, y_mm, args.pause_between_shapes)
    elif args.shape:
        send_one(client, args.shape, point_id, x_mm, y_mm)
        print()
        print("To confirm acceptance: watch MQTT for `s2p50 o:109 status:true` "
              "followed by `s2p56 = [[N, 0]]`.")
    else:
        p.error("must specify --list-points, --shape, or --auto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
