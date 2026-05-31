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


def _load_package(modname: str, pkgdir: str):
    """Load a PACKAGE (dir with __init__.py) so its `from ._sub import …`
    relative imports resolve via the import machinery.

    cloud_client was a single module pre-2026-05-20; it is now a package
    (cloud_client/__init__.py + _auth/_rpc/_fetchers/… mixins).
    """
    spec = importlib.util.spec_from_file_location(
        modname,
        f"{pkgdir}/__init__.py",
        submodule_search_locations=[pkgdir],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# Bootstrap the dreame_a2_mower package + its protocol subpackage so relative
# imports inside the cloud_client package resolve.
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
_cloud_mod = _load_package(
    "dreame_a2_mower.cloud_client",
    f"{_INTEG_ROOT}/cloud_client",
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


def shape_area_id(point_id: int, x_mm: int, y_mm: int) -> dict:
    """By-id, mirroring the WORKING spot-mow op103 `{area:[id]}`.

    Highest-confidence shape: the 2026-05-30 s2p56 finding shows
    point-runs are addressed by a stable selector id (status[0][0] =
    1/2 for these two points), and spot — the closest cousin — uses
    `{area:[id]}` and is live-confirmed."""
    return {"area": [point_id]}


def shape_region_id(point_id: int, x_mm: int, y_mm: int) -> dict:
    """By-id, mirroring zone-mow op102 `{region:[id]}`."""
    return {"region": [point_id]}


# Map-paired by-id shapes. cleanPoints are PER-MAP (point id is per-map), so the
# payload may need [map_id, point_id] even when that map is active. Map 0 is the
# active map in this account (MAPL col-1==1); change ACTIVE_MAP if it differs.
ACTIVE_MAP = 0


def shape_point_map(point_id: int, x_mm: int, y_mm: int) -> dict:
    """[map_id, point_id] pair under `point` (edge-mow's [[map,contour]] style)."""
    return {"point": [[ACTIVE_MAP, point_id]]}


def shape_cleanpoint_map(point_id: int, x_mm: int, y_mm: int) -> dict:
    """[map_id, point_id] pair under the map-blob key `cleanPoints`."""
    return {"cleanPoints": [[ACTIVE_MAP, point_id]]}


# Order = descending confidence. By-id shapes first (the s2p56 selector-id
# lead), coordinate shapes last (demoted by that same finding).
SHAPES: dict[str, callable] = {
    "area_id": shape_area_id,
    "region_id": shape_region_id,
    "point_id": shape_point_id,
    "cleanpoints_id": shape_cleanpoints_id,
    "point_map": shape_point_map,
    "cleanpoint_map": shape_cleanpoint_map,
    "tpoint": shape_tpoint,
    "point_coords": shape_point_coords,
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
    # Pin the mower (populates _did/_host) so fetch_map / action have a target.
    client.select_first_g2408()
    client.get_device_info()
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


# --- Routed-action path (the REAL working transport for ops 100-103) ---------
#
# The prior 20-combo run sent via a hand-built envelope through
# ``client.action(siid=2, aiid=50, [full_envelope])``. This path instead
# goes through ``client.routed_action(109, d)`` — byte-identical to how the
# live-confirmed spot/zone/edge ops are dispatched — so an acceptance here
# is exactly what the integration would produce.

BY_ID_SHAPES = ["area_id", "region_id", "point_id", "cleanpoints_id"]


def relay_check(client) -> bool:
    """Fire a known-harmless routed op (findBot, op=9) to tell whether the
    cloud action relay is alive RIGHT NOW.

    Rationale: op=109 returning 80001 ("device offline / send timeout") is a
    TRANSPORT error, not an opcode reject. An idle-at-dock g2408 frequently
    lets the cloud relay tunnel sleep, so every routed_action 80001s
    regardless of opcode. findBot is the cheapest control — it just makes the
    mower beep — and uses the identical transport. If THIS 80001s too, the
    relay is asleep and the by-id result is inconclusive (re-test while the
    device is actively connected). If it succeeds but op=109 80001s, that's a
    genuine op-specific reject.
    """
    print("--- relay control: routed_action op=9 (findBot, harmless beep) ---")
    client._last_send_error_code = None
    reply = client.routed_action(9)
    err = getattr(client, "_last_send_error_code", None)
    alive = reply is not None
    print(
        f"  ← result: {json.dumps(reply, ensure_ascii=False)[:200]}"
        f"  (last_send_error_code={err})"
    )
    print(
        "  relay ALIVE — known-good op accepted; by-id 80001s would be a real "
        "op=109 reject."
        if alive else
        "  relay ASLEEP/UNREACHABLE (80001 on a known-good op too) — any by-id "
        "80001 is INCONCLUSIVE. Re-probe while the mower is actively connected "
        "(e.g. just after an app command wakes it, or mid-mow)."
    )
    return alive


def send_one_routed(client, shape_name: str, point_id: int, x_mm: int, y_mm: int):
    """Send op=109 through routed_action: {m:'a',p:0,o:109,d:<shape>}."""
    d_field = SHAPES[shape_name](point_id, x_mm, y_mm)
    print(
        f"→ routed_action op=109  shape={shape_name!r}"
        f"\n  d-field: {json.dumps(d_field, separators=(',', ':'))}"
    )
    client._last_send_error_code = None
    try:
        reply = client.routed_action(109, d_field)
    except Exception as ex:
        print(f"  ERROR: {ex!r}")
        return None
    err = getattr(client, "_last_send_error_code", None)
    print(
        f"  ← result: {json.dumps(reply, ensure_ascii=False)[:400]}"
        f"  (last_send_error_code={err})"
    )
    return reply


def send_routed_retry(client, op: int, d_field, retries: int, delay_s: float,
                      label: str = ""):
    """Call routed_action(op, d) up to `retries` times until a non-None result.

    80001 ("device offline / send timeout") on /device/sendCommand is the
    relay timing out reaching an ASLEEP docked device — the first call often
    wakes it, so a later retry can succeed. routed_action/send() does NOT
    retry 80001 itself (it fast-returns None), so we retry here.
    """
    for attempt in range(1, retries + 1):
        client._last_send_error_code = None
        reply = client.routed_action(op, d_field)
        err = getattr(client, "_last_send_error_code", None)
        print(
            f"  [{label}attempt {attempt}/{retries}] op={op} "
            f"d={json.dumps(d_field, separators=(',', ':')) if d_field else '{}'}"
            f"  → result={json.dumps(reply, ensure_ascii=False)[:200]} "
            f"(err={err})"
        )
        if reply is not None:
            return reply, attempt
        if attempt < retries and delay_s > 0:
            time.sleep(delay_s)
    return None, retries


def spot_control(client, spot_id: int, retries: int, delay_s: float):
    """Replicate the integration's spot-mow start EXACTLY, with retries.

    The integration's start_mowing_spot → dispatch_action(START_SPOT_MOW) →
    routed_action(103, {"area":[spot_id]}). This is a KNOWN-GOOD action the
    user confirms works from the integration — so it's the control that tells
    us whether /device/sendCommand works at all (wake-up theory) vs op=109
    being specifically unroutable. NOTE: success will physically send the
    mower out to mow the spot.
    """
    print(f"=== SPOT-MOW CONTROL: op=103 d={{area:[{spot_id}]}} "
          f"(retries={retries}, delay={delay_s}s) ===")
    print("    (success = the mower physically leaves the dock to mow the spot)")
    reply, attempt = send_routed_retry(
        client, 103, {"area": [spot_id]}, retries, delay_s, label="spot "
    )
    if reply is not None:
        print(f"\n✓ spot-mow ACCEPTED on attempt {attempt} — routed_action / "
              "/device/sendCommand DOES work (after wake). The op=109 80001s are "
              "then a wake/retry issue, not a wrong transport.")
    else:
        print(f"\n✗ spot-mow 80001'd on all {retries} attempts — even a "
              "known-good integration action can't get through right now.")
    return reply


def routed_byid_probe(client, point_id, x_mm, y_mm, shapes, pause_s,
                      retries=1, retry_delay=8.0):
    """Try by-id shapes one at a time via routed_action; stop at first
    non-None result.

    routed_action returns ``None`` on 80001/HTTP-error and the RPC
    ``result`` object on cloud acceptance. A non-None result is the
    NEW signal (the prior run got None/400 for every combo) — but
    firmware acceptance still needs MQTT/visual confirmation.
    """
    for shape_name in shapes:
        print()
        print("=" * 64)
        print(f"shape={shape_name!r}")
        d_field = SHAPES[shape_name](point_id, x_mm, y_mm)
        reply, attempt = send_routed_retry(
            client, 109, d_field, retries, retry_delay, label=f"{shape_name} "
        )
        if reply is not None:
            print()
            print(
                f"✓ shape={shape_name!r}: routed_action returned a RESULT on "
                f"attempt {attempt} — the cloud RPC was ACCEPTED."
            )
            print(
                f"  CONFIRM firmware-side: watch the mower leave the dock and "
                f"MQTT for `s2p50 o:109 status:true` then `s2p56=[[{point_id},0]]`."
            )
            return shape_name
        if pause_s > 0:
            time.sleep(pause_s)
    print(
        "\n✗ no by-id shape accepted via routed_action (all 80001). Interpret "
        "AGAINST the spot-mow control: if the control also 80001'd, the relay "
        "couldn't reach the device at all (wake/retry harder or try later); if "
        "the control SUCCEEDED, op=109 is specifically unroutable via "
        "/device/sendCommand → needs the app's real endpoint (MITM/apk)."
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
    p.add_argument("--relay-check", action="store_true",
                   help="Fire findBot (op=9, harmless) via routed_action to "
                        "report whether the cloud action relay is awake. Exits.")
    p.add_argument("--spot-control", type=int, metavar="SPOT_ID",
                   help="CONTROL: replicate the integration's spot-mow start "
                        "exactly — routed_action(103, {area:[SPOT_ID]}) with "
                        "retries. Success physically mows the spot. Exits.")
    p.add_argument("--retries", type=int, default=1,
                   help="Attempts per op before giving up (wake-up retry). "
                        "Default 1. Use ~5 to test the 'device takes a few "
                        "seconds to wake' theory.")
    p.add_argument("--retry-delay", type=float, default=8.0,
                   help="Seconds between retries (default 8).")
    p.add_argument("--routed-byid", action="store_true",
                   help="Send the by-id shapes (area_id/region_id/point_id/"
                        "cleanpoints_id) through the REAL routed_action path "
                        "(the working transport for mow ops). Stops at first "
                        "accepted RPC. This is the recommended live re-probe.")
    p.add_argument("--routed-shape", choices=sorted(SHAPES),
                   help="Send ONE op=109 shape via routed_action with retries "
                        "(one-at-a-time stepping). Read the s2p50 o:109 echo "
                        "(status:true=accepted) — cloud r:0 alone is not enough.")
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

    if args.relay_check:
        relay_check(client)
        return 0

    if args.spot_control is not None:
        spot_control(client, args.spot_control, args.retries, args.retry_delay)
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

    if args.routed_shape:
        d_field = SHAPES[args.routed_shape](point_id, x_mm, y_mm)
        print(f"=== single shape={args.routed_shape!r} op=109 "
              f"(retries={args.retries}) ===")
        reply, attempt = send_routed_retry(
            client, 109, d_field, args.retries, args.retry_delay,
            label=f"{args.routed_shape} ")
        print("\nNow READ the MQTT log for the s2p50 o:109 echo:")
        print("  status:true  → shape ACCEPTED (mower should head to the point)")
        print("  status:false → shape REJECTED (try the next shape)")
        print("  (cloud r:0 above only means the cloud forwarded it — not accept)")
        return 0

    if args.routed_byid:
        alive = relay_check(client)
        print()
        routed_byid_probe(client, point_id, x_mm, y_mm, BY_ID_SHAPES,
                          args.pause_between_shapes,
                          retries=args.retries, retry_delay=args.retry_delay)
        if not alive:
            print(
                "\nNOTE: relay control 80001'd too — the by-id result above is "
                "INCONCLUSIVE (transport asleep, not an op=109 reject)."
            )
    elif args.auto:
        auto_probe(client, point_id, x_mm, y_mm, args.pause_between_shapes)
    elif args.shape:
        send_one(client, args.shape, args.envelope, point_id, x_mm, y_mm)
        print()
        print("To confirm acceptance: watch MQTT for `s2p50 o:109 status:true` "
              "followed by `s2p56 = [[N, 0]]`.")
    else:
        p.error("must specify --list-points, --routed-byid, --shape, or --auto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
