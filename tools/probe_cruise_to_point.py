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
or ``/data/claude/homeassistant/server-credentials.txt`` (email on
line 1, password on line 2, country on optional line 3 — default
``eu``). Pass ``--credentials <path>`` to override.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


# --- Stub `homeassistant` so we can import cloud_client.py standalone --------
# Mirrors /data/claude/homeassistant/dreame_cloud_dump.py.
for _mod in (
    "homeassistant",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers",
    "homeassistant.helpers.event",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.device_registry",
    "homeassistant.components",
    "homeassistant.components.persistent_notification",
    "homeassistant.components.http",
    "homeassistant.components.button",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.camera",
    "homeassistant.components.lawn_mower",
    "homeassistant.components.number",
    "homeassistant.components.select",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "homeassistant.components.time",
    "homeassistant.exceptions",
    "homeassistant.util",
    "voluptuous",
):
    sys.modules.setdefault(_mod, MagicMock())

import importlib.util  # noqa: E402
import types  # noqa: E402

_INTEG_ROOT = str(Path(__file__).resolve().parent.parent / "custom_components" / "dreame_a2_mower")


def _load_module(modname: str, filepath: str, package: str | None = None):
    spec = importlib.util.spec_from_file_location(modname, filepath)
    mod = importlib.util.module_from_spec(spec)
    if package is not None:
        mod.__package__ = package
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# Bootstrap the dreame_a2_mower package + its protocol subpackage so relative
# imports inside cloud_client.py resolve.
_pkg = types.ModuleType("dreame_a2_mower")
_pkg.__path__ = [_INTEG_ROOT]
sys.modules["dreame_a2_mower"] = _pkg

_proto_pkg = types.ModuleType("dreame_a2_mower.protocol")
_proto_pkg.__path__ = [f"{_INTEG_ROOT}/protocol"]
sys.modules["dreame_a2_mower.protocol"] = _proto_pkg

_load_module("dreame_a2_mower.const", f"{_INTEG_ROOT}/const.py", package="dreame_a2_mower")
_load_module(
    "dreame_a2_mower.protocol.cfg_action",
    f"{_INTEG_ROOT}/protocol/cfg_action.py",
    package="dreame_a2_mower.protocol",
)
_cloud_mod = _load_module(
    "dreame_a2_mower.cloud_client",
    f"{_INTEG_ROOT}/cloud_client.py",
    package="dreame_a2_mower",
)
DreameA2CloudClient = _cloud_mod.DreameA2CloudClient


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


# Full envelope variants for op=109. Most ops 100-103 use the
# minimal `{m,p,o,d}` envelope built by routed_action. But the MQTT
# echo we observed for op=109 included `t:'TASK'` at the top level,
# suggesting it may need to be part of the send-side envelope too.
# Each variant returns the FULL parameters[0] dict — no extra
# wrapping done by the caller.
def envelope_minimal(d_field: dict, op: int = 109) -> dict:
    """Baseline: matches the working zone/spot/edge shape."""
    return {"m": "a", "p": 0, "o": op, "d": d_field}


def envelope_with_task(d_field: dict, op: int = 109) -> dict:
    """Adds `t:'TASK'` (matches the MQTT echo top-level)."""
    return {"m": "a", "p": 0, "o": op, "t": "TASK", "d": d_field}


def envelope_with_exe(d_field: dict, op: int = 109) -> dict:
    """Adds `exe:true` (visible in the echo's `d` block — but may belong outside)."""
    return {"m": "a", "p": 0, "o": op, "t": "TASK", "exe": True, "d": d_field}


def envelope_set_mode(d_field: dict, op: int = 109) -> dict:
    """`m:'s'` (set) instead of `m:'a'` (action). Some routed ops use this."""
    return {"m": "s", "p": 0, "o": op, "t": "TASK", "d": d_field}


ENVELOPES: dict[str, callable] = {
    "minimal":      envelope_minimal,
    "with_t_task":  envelope_with_task,
    "with_exe":     envelope_with_exe,
    "set_mode":     envelope_set_mode,
}


# --- Credentials + client setup ----------------------------------------------

DEFAULT_CREDS_PATH = "/data/claude/homeassistant/server-credentials.txt"


def _load_credentials(path: str) -> dict[str, str]:
    """Read server-credentials.txt (line 1 = email, line 2 = password)."""
    user = os.environ.get("DREAME_USER")
    passwd = os.environ.get("DREAME_PASS")
    country = os.environ.get("DREAME_COUNTRY", "eu")
    if user and passwd:
        return {"username": user, "password": passwd, "country": country}
    creds_file = Path(path)
    if not creds_file.is_file():
        raise SystemExit(
            f"Credentials file not found: {creds_file}. "
            "Set DREAME_USER / DREAME_PASS env vars or pass --credentials."
        )
    lines = [l.strip() for l in creds_file.read_text().splitlines() if l.strip()]
    if len(lines) < 2:
        raise SystemExit(f"{creds_file}: need email on line 1, password on line 2")
    return {
        "username": lines[0],
        "password": lines[1],
        "country": lines[2] if len(lines) >= 3 else country,
    }


def _build_cloud_client(creds_path: str):
    creds = _load_credentials(creds_path)
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


def send_one(
    client,
    shape_name: str,
    envelope_name: str,
    point_id: int,
    x_mm: int,
    y_mm: int,
):
    """Send one (envelope, d-shape) combo via siid=2 aiid=50 directly."""
    shape_fn = SHAPES[shape_name]
    envelope_fn = ENVELOPES[envelope_name]
    d_field = shape_fn(point_id, x_mm, y_mm)
    full_envelope = envelope_fn(d_field)
    print(
        f"→ envelope={envelope_name!r}  shape={shape_name!r}"
        f"\n  wire: {json.dumps(full_envelope, separators=(',', ':'))}"
    )
    try:
        # Bypass routed_action to control the FULL envelope (it forces
        # {m,p,o,d} only — no `t` etc.).
        reply = client.action(siid=2, aiid=50, parameters=[full_envelope])
    except Exception as ex:
        print(f"  ERROR: {ex!r}")
        return None
    print(f"  ← cloud reply: {json.dumps(reply, ensure_ascii=False)[:400]}")
    return reply


def auto_probe(client, point_id: int, x_mm: int, y_mm: int, pause_s: float):
    """Try every (envelope × d-shape) combo; stop at first cloud success."""
    for env_name in ENVELOPES:
        for shape_name in SHAPES:
            print()
            print("=" * 64)
            reply = send_one(
                client, shape_name, env_name, point_id, x_mm, y_mm
            )
            if reply_indicates_success(reply):
                print()
                print(
                    f"✓ envelope={env_name!r}  shape={shape_name!r}: "
                    "cloud returned r=0 (HTTP success)."
                )
                print(
                    "  Watch the MQTT probe for `s2p50 o:109 status:true` "
                    "and `s2p56=[[N,0]]` to confirm firmware-side acceptance."
                )
                return (env_name, shape_name)
            if pause_s > 0:
                time.sleep(pause_s)
    print(
        "\n✗ no (envelope, shape) combo accepted. The cloud's HTTP layer "
        "is rejecting op=109 via `s2.50`; the app may use a different "
        "endpoint entirely. Time to dig into app traffic or the apk."
    )
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
                   help="Try one specific payload d-shape.")
    p.add_argument("--envelope", choices=sorted(ENVELOPES), default="minimal",
                   help="Outer envelope variant for --shape mode. Default: minimal.")
    p.add_argument("--auto", action="store_true",
                   help="Try every (envelope × shape) combo until cloud returns r=0.")
    p.add_argument("--point-id", type=int,
                   help="Maintenance point to target. Coords looked up unless "
                        "--x / --y given.")
    p.add_argument("--x", type=int, help="Override x_mm.")
    p.add_argument("--y", type=int, help="Override y_mm.")
    p.add_argument("--pause-between-shapes", type=float, default=2.0,
                   help="Seconds to wait between shapes in --auto mode "
                        "(lets the mower respond before next attempt).")
    p.add_argument("--credentials", default=DEFAULT_CREDS_PATH,
                   help=f"Credentials file (email/pass/country one per line). "
                        f"Default: {DEFAULT_CREDS_PATH}")
    args = p.parse_args()

    client = _build_cloud_client(args.credentials)

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
        send_one(client, args.shape, args.envelope, point_id, x_mm, y_mm)
        print()
        print("To confirm acceptance: watch MQTT for `s2p50 o:109 status:true` "
              "followed by `s2p56 = [[N, 0]]`.")
    else:
        p.error("must specify --list-points, --shape, or --auto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
