"""Typed action enum + (siid, aiid) dispatch table for the Dreame A2 mower.

Per spec §3 layer 2: no homeassistant imports. The dispatch helpers
here construct the wire payload but do NOT actually invoke the cloud
client — coordinator.dispatch_action does that.

The legacy DreameMowerActionMapping is at
``ha-dreame-a2-mower/custom_components/dreame_a2_mower/dreame/types.py:807``.
The greenfield only carries the g2408-relevant subset (per P2.1.3 audit).

Cloud-RPC limitation on g2408: the direct ``action(siid, aiid, ...)`` call
returns 80001 ("device unreachable"). The fallback path is the routed
action (siid=2, aiid=50) — the legacy at device.py:4280 documents this
and provides _ALT_ACTION_SIID_MAP as the routing table. This module
records both the primary (siid, aiid) AND the routed-action variant
when applicable; the coordinator's dispatch_action retries via the
routed path on 80001.

(siid, aiid) source: legacy DreameMowerActionMapping verified at
types.py lines 807-838:
  - START_MOWING → DreameMowerAction.START_MOWING: {siid: 5, aiid: 1}
  - PAUSE        → DreameMowerAction.PAUSE:         {siid: 5, aiid: 4}
  - DOCK         → DreameMowerAction.DOCK:           {siid: 5, aiid: 3}
  - STOP         → DreameMowerAction.STOP:           {siid: 5, aiid: 2}
  - SUPPRESS_FAULT → DreameMowerAction.CLEAR_WARNING:{siid: 4, aiid: 3}
  - FIND_BOT     → DreameMowerAction.LOCATE:         {siid: 7, aiid: 1}
  - LOCK_BOT_TOGGLE → no action entry in legacy; CHILD_LOCK is property
                       {siid: 4, piid: 27} (property-set, not action-call).
                       F4.7.1: wired via coordinator.write_setting("CLS", ...)
                       using the cfg_toggle_field mechanism.
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Any, TypedDict


class MowerAction(Enum):
    """Typed action identifiers. Names mirror Dreame app vocabulary
    where reasonable (Recharge, Find My Mower, etc.)."""
    START_MOWING = auto()
    START_ZONE_MOW = auto()
    START_EDGE_MOW = auto()
    START_SPOT_MOW = auto()
    PAUSE = auto()
    DOCK = auto()
    RECHARGE = auto()  # alias for DOCK with explicit "head to charger now" semantic
    STOP = auto()
    FIND_BOT = auto()
    LOCK_BOT_TOGGLE = auto()
    SUPPRESS_FAULT = auto()
    FINALIZE_SESSION = auto()  # integration-local; no cloud call


class ActionEntry(TypedDict, total=False):
    """One row of the dispatch table.

    siid / aiid: primary cloud-RPC mapping (returns 80001 on g2408 for
                 most actions, but recorded for completeness and as a
                 fallback should the cloud's RPC tunnel ever open).
    routed_t:    if set, the action dispatches via routed-action
                 s2 aiid=50 with this 't' value (the working path on g2408).
    routed_o:    optional 'o' opcode for TASK-envelope actions
                 (s2.50 op=100 mow start, op=101 zone-mow, etc.)
    payload_fn:  optional callable that builds the routed-action 'd' field
                 from a parameters dict.
    local_only:  if True, the action is integration-internal (no cloud call).
    cfg_toggle_field: if set, dispatch_action reads
                 ``getattr(coordinator.data, cfg_toggle_field)``,
                 computes ``not bool(current)``, and calls
                 ``coordinator.write_setting(cfg_key, toggled)`` where
                 ``cfg_key`` is the paired ``cfg_key`` entry in this same
                 ActionEntry.  Used for LOCK_BOT_TOGGLE (child lock = CLS).
    cfg_key:     the CFG key string used with cfg_toggle_field (e.g. "CLS").
    """
    siid: int
    aiid: int
    routed_t: str
    routed_o: int
    payload_fn: Any  # Callable[[dict], dict | None]
    local_only: bool
    cfg_toggle_field: str  # MowerState field name whose value is toggled
    cfg_key: str           # CFG key string to pass to write_setting


def _zone_mow_payload(params: dict[str, Any]) -> dict[str, Any]:
    """Build the TASK envelope d-field for zone-mow (op=102).

    Wire format verified against the upstream Tasshack integration's
    `_build_zone_task_payload` (alternatives/dreame-mower
    dreame/device.py:1369), which is known to work for g2408:
        {"m":"a","p":0,"o":102,"d":{"region":[zone_ids]}}
    """
    zones = params.get("zones") or []
    if not zones:
        raise ValueError("START_ZONE_MOW requires non-empty 'zones' list")
    return {"region": [int(z) for z in zones]}


def _edge_mow_payload(params: dict[str, Any]) -> dict[str, Any]:
    """TASK envelope d-field for edge-mow (op=101).

    The cloud expects ``edge`` as a list of [map_id, contour_id] pairs.
    Caller passes ``contour_ids: [[m,c], ...]`` for explicit contour
    selection; default ``[[1, 0]]`` is the outer perimeter on the
    primary map.

    **Empirical finding (2026-05-05, three live edge runs)**: passing
    ``[]`` (empty list) does NOT mean "edge every contour in the
    current map" — the firmware interprets it as "every contour
    INCLUDING merged sub-zone seams" and traces internal boundaries
    that aren't visible in the app, draining the firmware's edge
    budget (`area_mowed_cent = 700`, `dist_dm = 10000`) on irrelevant
    interior segments. On lawns with a tight maneuvering spot near
    such a seam, the mower wheel-binds, the budget cap fires while
    wedged, and the auto-dock planner cannot route home from the
    stuck pose → "Failed to return to station" (`s2p2: 48 → 31`).
    Two consecutive integration-launched edge runs reproduced this;
    an app-launched run with the explicit `[[1, 0]]` payload (the
    canonical outer-perimeter contour pair) traced the proper outer
    perimeter and docked cleanly. The legacy upstream
    ``alternatives/dreame-mower/.../device.py:1745`` rejects empty
    contour_ids outright as an error — confirming our prior
    "empty = all contours" reading was wrong.

    The fallback default ``[[1, 0]]`` here is a last-resort safety
    net for the case where ``coordinator.dispatch_action`` couldn't
    populate ``contour_ids`` from cached map data (e.g. map data not
    yet fetched on this start). The preferred default is
    "all outer-perimeter contours from the cached map", computed in
    ``coordinator.dispatch_action`` and passed in via ``params``.
    """
    contour_ids = params.get("contour_ids") or [[1, 0]]
    return {"edge": [list(pair) for pair in contour_ids]}


def _spot_mow_payload(params: dict[str, Any]) -> dict[str, Any]:
    """TASK envelope d-field for spot-mow (op=103).

    Verified against alternatives/dreame-mower dreame/device.py:1398:
        {"m":"a","p":0,"o":103,"d":{"area":[spot_area_ids]}}
    """
    spots = params.get("spots") or []
    if not spots:
        raise ValueError("START_SPOT_MOW requires non-empty 'spots' list")
    return {"area": [int(s) for s in spots]}


# (siid, aiid) values verified against legacy
# /data/claude/homeassistant/ha-dreame-a2-mower/custom_components/
# dreame_a2_mower/dreame/types.py lines 807-838 (DreameMowerActionMapping).
ACTION_TABLE: dict[MowerAction, ActionEntry] = {
    MowerAction.START_MOWING: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 100,
    },
    MowerAction.START_ZONE_MOW: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 102,
        "payload_fn": _zone_mow_payload,
    },
    MowerAction.START_EDGE_MOW: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 101,
        "payload_fn": _edge_mow_payload,
    },
    MowerAction.START_SPOT_MOW: {
        "siid": 5, "aiid": 1,
        "routed_t": "TASK", "routed_o": 103,
        "payload_fn": _spot_mow_payload,
    },
    MowerAction.PAUSE: {"siid": 5, "aiid": 4},
    MowerAction.DOCK: {"siid": 5, "aiid": 3},
    MowerAction.RECHARGE: {"siid": 5, "aiid": 3},  # same wire call as DOCK
    MowerAction.STOP: {"siid": 5, "aiid": 2},
    # FIND_BOT → legacy DreameMowerAction.LOCATE: {siid: 7, aiid: 1}
    # routed_o=9 per cfg_action.py:182 (findBot opcode)
    MowerAction.FIND_BOT: {"siid": 7, "aiid": 1, "routed_o": 9},
    # LOCK_BOT_TOGGLE — CHILD_LOCK has no action entry in legacy; it is a
    # property write to CFG key CLS (confirmed g2408, docs/research §6.2).
    # F4.7.1 wires it via coordinator.write_setting("CLS", toggled_value).
    # dispatch_action reads cfg_toggle_field from coordinator.data, computes
    # not bool(current), and calls write_setting(cfg_key, toggled).
    MowerAction.LOCK_BOT_TOGGLE: {
        "cfg_toggle_field": "child_lock_enabled",
        "cfg_key": "CLS",
    },
    # SUPPRESS_FAULT → legacy DreameMowerAction.CLEAR_WARNING: {siid: 4, aiid: 3}
    # routed_o=11 per cfg_action.py:182 (suppressFault opcode)
    MowerAction.SUPPRESS_FAULT: {"siid": 4, "aiid": 3, "routed_o": 11},
    # FINALIZE_SESSION — integration-local; no cloud call ever issued.
    # dispatch_action's local_only branch calls _run_finalize_incomplete()
    # (F5.10.1).  local_only=True is kept so the cloud-action path is
    # never reached for this action.
    MowerAction.FINALIZE_SESSION: {"local_only": True},
}
