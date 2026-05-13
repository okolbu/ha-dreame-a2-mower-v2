#!/usr/bin/env python3
"""Probe candidate map-edit payloads for adding a maintenance point.

Background
----------
We have captured the s2p50 ECHO for map-edit operations on g2408:

    s2p50 = {m:'a', d:{o:204, exe:T, status:T}, t:'TASK'}    # begin
    s2p50 = {m:'a', d:{o:234, id:N, ids:[]}, t:'TASK'}       # save geometry
    s2p50 = {m:'a', d:{o:201, status:T, error:0}, t:'TASK'}  # commit

The echo for o:234 carries only the firmware-assigned `id` — the
geometry/coordinates are NOT in the echo. Two possibilities:

  A. The geometry was uploaded via a SEPARATE channel (setDeviceData
     write of MAP.0..N) and o:234 is just a "go, reload your map"
     signal.
  B. The app's o:234 REQUEST contains the geometry, but the firmware
     strips it in the echo.

This script tests (B) — sends o:234 with several guessed payload
shapes and checks whether the cloud / firmware accept them.

Target map: map_id=1 (Map 2 — sacrificial per user direction).
Target geometry: a single maintenance point at (5000, 5000) mm
in cloud-frame, far from any existing feature.

Cloud-success criterion: `code:0` in the HTTP response.
Firmware-success: `out[0].r:0`. Anything else (r=-3, etc.) is
"shape rejected".

If ALL shapes fail, the o:234 path is likely just a signal — the
real write surface is MAP.0..N chunked write or an HTTP endpoint we
haven't sniffed yet. Update docs/research/cloud-write-reference.md
with findings.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Stub HA so cloud_client imports
for _mod in (
    "homeassistant", "homeassistant.const", "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers", "homeassistant.helpers.event",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.device_registry",
    "homeassistant.components",
    "homeassistant.components.persistent_notification",
    "homeassistant.components.http", "homeassistant.components.button",
    "homeassistant.components.binary_sensor", "homeassistant.components.camera",
    "homeassistant.components.lawn_mower", "homeassistant.components.number",
    "homeassistant.components.select", "homeassistant.components.sensor",
    "homeassistant.components.switch", "homeassistant.components.time",
    "homeassistant.exceptions", "homeassistant.util", "voluptuous",
):
    sys.modules.setdefault(_mod, MagicMock())

import importlib.util
import types

_INTEG = str(Path(__file__).resolve().parent.parent / "custom_components" / "dreame_a2_mower")


def _load(modname, filepath, package=None):
    spec = importlib.util.spec_from_file_location(modname, filepath)
    mod = importlib.util.module_from_spec(spec)
    if package is not None:
        mod.__package__ = package
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_pkg = types.ModuleType("dreame_a2_mower"); _pkg.__path__ = [_INTEG]
sys.modules["dreame_a2_mower"] = _pkg
_proto = types.ModuleType("dreame_a2_mower.protocol"); _proto.__path__ = [f"{_INTEG}/protocol"]
sys.modules["dreame_a2_mower.protocol"] = _proto
_load("dreame_a2_mower.const", f"{_INTEG}/const.py", "dreame_a2_mower")
_load("dreame_a2_mower.protocol.cfg_action", f"{_INTEG}/protocol/cfg_action.py", "dreame_a2_mower.protocol")
_cloud = _load("dreame_a2_mower.cloud_client", f"{_INTEG}/cloud_client.py", "dreame_a2_mower")
DreameA2CloudClient = _cloud.DreameA2CloudClient


def _load_creds() -> dict[str, str]:
    p = Path("/data/claude/homeassistant/server-credentials.txt")
    lines = [l.strip() for l in p.read_text().splitlines() if l.strip()]
    return {"username": lines[0], "password": lines[1],
            "country": lines[2] if len(lines) > 2 else "eu"}


def _client() -> DreameA2CloudClient:
    creds = _load_creds()
    c = DreameA2CloudClient(**creds)
    if not c.login():
        raise SystemExit("login failed")
    devices = c.get_devices()
    if not devices:
        raise SystemExit("no devices")
    c.get_device_info()
    return c


# Candidate d-payloads for o:234 (save maintenance point).
# Target map_id=1 (Map 2). Point at cloud-frame (5000, 5000) mm.
TARGET_MAP = 1
TARGET_X = 5000
TARGET_Y = 5000
NEW_ID = 999  # unlikely to collide with existing firmware-assigned ids


def shape_a() -> dict:
    """Mimic forbiddenAreas/notObsAreas wrapper. type=9 is what app
    uses for cleanPoints per inventory.yaml."""
    return {
        "map_id": TARGET_MAP, "id": NEW_ID, "ids": [],
        "type": 9, "shapeType": 1,
        "path": [{"x": TARGET_X, "y": TARGET_Y}],
        "angle": 0,
    }


def shape_b() -> dict:
    """Without map_id (rely on active map). Might fail since active
    is Map 1, not Map 2."""
    return {
        "id": NEW_ID, "ids": [],
        "type": 9, "shapeType": 1,
        "path": [{"x": TARGET_X, "y": TARGET_Y}],
    }


def shape_c() -> dict:
    """Geometry-only, no id (firmware should assign)."""
    return {
        "map_id": TARGET_MAP,
        "type": 9, "shapeType": 1,
        "path": [{"x": TARGET_X, "y": TARGET_Y}],
        "angle": 0,
    }


def shape_d() -> dict:
    """Wrapped in cleanPoints (mirrors how cloud stores it)."""
    return {
        "map_id": TARGET_MAP,
        "cleanPoints": {"value": [[NEW_ID, {
            "id": NEW_ID, "type": 9, "shapeType": 1,
            "path": [{"x": TARGET_X, "y": TARGET_Y}], "angle": 0,
        }]]},
    }


SHAPES = [("A_full", shape_a), ("B_no_map_id", shape_b),
          ("C_no_id", shape_c), ("D_cleanpoints_wrap", shape_d)]


def _probe(c: DreameA2CloudClient, name: str, d: dict) -> dict[str, Any]:
    """Send {m:'a', p:0, o:234, t:'TASK', **d} as siid=2 aiid=50."""
    params = [{"m": "a", "p": 0, "o": 234, "t": "TASK", **d}]
    try:
        result = c.action(siid=2, aiid=50, parameters=params)
    except Exception as ex:
        return {"shape": name, "error": str(ex), "result": None}
    return {"shape": name, "payload": params[0], "result": result}


def main() -> int:
    c = _client()
    print(f"# Probe: add maintenance point on map_id={TARGET_MAP} at "
          f"({TARGET_X}, {TARGET_Y}) mm")
    print()

    # First, send o:204 (begin edit) to put firmware in edit mode.
    print("Step 1: o:204 (begin edit)")
    begin = c.action(siid=2, aiid=50, parameters=[
        {"m": "a", "p": 0, "o": 204, "t": "TASK", "map_id": TARGET_MAP},
    ])
    print(f"  result: {json.dumps(begin)[:200]}")
    print()

    # Try each o:234 shape, leaving 2s between sends.
    for name, factory in SHAPES:
        d = factory()
        r = _probe(c, name, d)
        print(f"Step 2 ({name}): {json.dumps(r)[:400]}")
        time.sleep(2)

    print()
    print("Step 3: o:201 (commit) — best-effort")
    commit = c.action(siid=2, aiid=50, parameters=[
        {"m": "a", "p": 0, "o": 201, "t": "TASK"},
    ])
    print(f"  result: {json.dumps(commit)[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
