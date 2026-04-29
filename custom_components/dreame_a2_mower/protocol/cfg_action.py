"""Routed-action wrappers for siid:2 aiid:50 calls.

Per apk.md, the Dreame mower exposes most of its CFG/PRE/CMS/etc.
machinery via a single MIoT action endpoint at siid=2 aiid=50.
The `in[0]` payload routes by `m` (mode: 'g'=get, 's'=set, 'a'=action,
'r'=remote) and `t` (target: 'CFG', 'PRE', 'DOCK', 'CMS', ...).

Returns are unwrapped from `result.out[0]` (the cloud envelope).

This module provides typed wrappers but deliberately stays
protocol-only — no HA imports. The device.py layer is responsible
for translating CFG payloads into entity state.
"""

from __future__ import annotations

from typing import Any


# Action endpoint constants per apk decompilation.
ROUTED_ACTION_SIID = 2
ROUTED_ACTION_AIID = 50


class CfgActionError(RuntimeError):
    """Raised when a routed action call returns no data."""


def _unwrap(result: Any) -> Any:
    """Unwrap the cloud envelope. The protocol's send-action path
    returns `{"result": {"out": [<payload>]}}` on success and various
    error shapes on failure. We accept any shape that yields an
    `out[0]` mapping; everything else raises.

    The unwrapped payload may itself be a Dreame application-level
    error: `{'m': 'r', 'q': <id>, 'r': <code>}` where `r != 0` means
    the endpoint rejected the request (e.g. unsupported on this
    firmware, missing parameters). We surface this with a specific
    error message so callers can distinguish it from a transport
    failure and skip wasteful retries."""
    if not isinstance(result, dict):
        raise CfgActionError(f"unexpected result type: {type(result).__name__}")
    inner = result.get("result", result)  # tolerate flat or nested
    out = inner.get("out") if isinstance(inner, dict) else None
    if not isinstance(out, list) or not out:
        raise CfgActionError(f"action returned no `out`: {result!r}")
    payload = out[0]
    # Dreame error envelope detection.
    if (
        isinstance(payload, dict)
        and payload.get("m") == "r"
        and "r" in payload
        and payload["r"] != 0
    ):
        raise CfgActionError(
            f"endpoint returned Dreame error r={payload['r']} "
            f"(likely not supported on this firmware): {payload!r}"
        )
    return payload


def get_cfg(send_action) -> dict:
    """Fetch the full settings dict (WRP, DND, BAT, CLS, VOL, LIT,
    AOP, REC, STUN, ATA, PATH, WRF, PROT, CMS, PRE, ...).

    `send_action` must be a callable matching the protocol's
    action(siid, aiid, parameters) signature.
    """
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": "CFG"}]
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        raise CfgActionError(f"getCFG returned no `d` dict: {payload!r}")
    return d


def get_dock_pos(send_action) -> dict:
    """Fetch dock position + lawn-connection status."""
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": "DOCK"}]
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        raise CfgActionError(f"getDockPos returned no `d` dict: {payload!r}")
    dock = d.get("dock")
    if not isinstance(dock, dict):
        raise CfgActionError(f"getDockPos: missing dock subkey: {d!r}")
    return dock


def get_obs(send_action) -> dict:
    """Fetch obstacle-avoidance settings (Pathway Obstacle Avoidance,
    Obstacle Avoidance Distance / Height, etc.).

    Per apk catalogue (g2408 unconfirmed). Returns the raw `d` dict
    so the caller can label keys as toggle-correlation evidence
    accumulates."""
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": "OBS"}]
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        raise CfgActionError(f"getOBS returned no `d` dict: {payload!r}")
    return d


def get_aiobs(send_action) -> dict:
    """Fetch AI obstacle settings (AI Obstacle Recognition: Humans /
    Animals / Objects, possibly Capture Photos AI Obstacles).

    Per apk catalogue (g2408 unconfirmed)."""
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": "AIOBS"}]
    )
    payload = _unwrap(raw)
    d = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(d, dict):
        raise CfgActionError(f"getAIOBS returned no `d` dict: {payload!r}")
    return d


# All GET endpoints listed in apk.md §"GET-Befehle" that we have NOT
# yet wired explicitly. The probe call below tries each at startup so
# we learn empirically which ones g2408 supports.
_GET_ENDPOINT_CATALOGUE: tuple[str, ...] = (
    "DEV",    # device info (SN, MAC, FW)
    "CFG",    # full settings dict (already wired separately)
    "NET",    # network/wifi info
    "IOT",    # IoT connection info
    "MAPL",   # map list
    "MAPI",   # map info for index
    "MAPD",   # map data (chunked — may not return on a single call)
    "DOCK",   # dock position (already wired separately)
    "MISTA",  # current mission status
    "MITRC",  # mission track
    "MIHIS",  # mission history
    "CMS",    # wear meters
    "PIN",    # PIN status
    "OBS",    # obstacle data (already wired separately)
    "AIOBS",  # AI obstacle data (already wired separately)
    "LOCN",   # GPS location (lon, lat)
    "RPET",   # Rain Protection End Time
    "PRE",    # preference data per-zone
    "PREI",   # preference info
)


def probe_get(send_action, target: str) -> Any:
    """Fire a generic getX routed action and return the raw payload
    (unwrapped one level). Caller handles the per-endpoint shape;
    this is intentionally tolerant for probe/discovery purposes."""
    raw = send_action(
        ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [{"m": "g", "t": target}]
    )
    return _unwrap(raw)


def set_pre(send_action, pre_array: list) -> Any:
    """Write the PRE preferences array. Caller is responsible for
    read-modify-write semantics (read CFG.PRE, modify the slot,
    pass the full updated array here)."""
    if not isinstance(pre_array, list) or len(pre_array) < 10:
        raise ValueError(
            f"PRE array must have at least 10 elements, got {len(pre_array) if isinstance(pre_array, list) else type(pre_array).__name__}"
        )
    return send_action(
        ROUTED_ACTION_SIID,
        ROUTED_ACTION_AIID,
        [{"m": "s", "t": "PRE", "d": {"value": pre_array}}],
    )


def call_action_op(send_action, op: int, extra: dict | None = None) -> Any:
    """Invoke an action opcode (`{m:'a', p:0, o:OP, d:{...}}`).

    Per apk § "Actions": op 100=globalMower, 101=edgeMower,
    102=zoneMower, 103=spotMower, 110=startLearningMap,
    11=suppressFault, 9=findBot, 12=lockBot, 401=takePic,
    503=cutterBias.

    The extra dict (if given) is wrapped in a ``d`` sub-key — that's
    the wire format the mower's parser actually expects. Verified
    against alternatives/dreame-mower
    ``dreame/device.py:_build_*_task_payload`` for op 100/101/102/103.
    Pre-v1.0.0a34 we merged extras at the top level
    (``{m,p,o,region:[1]}``) and the mower silently ignored the
    field, which is why zone/spot mow looked like a no-op.
    """
    payload: dict = {"m": "a", "p": 0, "o": int(op)}
    if extra:
        payload["d"] = extra
    return send_action(ROUTED_ACTION_SIID, ROUTED_ACTION_AIID, [payload])
