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
    """Build the TASK envelope d-field for zone-mow (op=101)."""
    zones = params.get("zones") or []
    if not zones:
        raise ValueError("START_ZONE_MOW requires non-empty 'zones' list")
    return {"region_id": list(zones)}


def _edge_mow_payload(params: dict[str, Any]) -> dict[str, Any]:
    """TASK envelope for edge-mow.

    Without zone_id: edge all zones. With zone_id: edge only that zone.
    """
    zone_id = params.get("zone_id")
    if zone_id is not None:
        return {"region_id": [int(zone_id)]}
    return {}


def _spot_mow_payload(params: dict[str, Any]) -> dict[str, Any]:
    x = params.get("x_m")
    y = params.get("y_m")
    if x is None or y is None:
        raise ValueError("START_SPOT_MOW requires 'x_m' and 'y_m'")
    # Spot point is in mower-frame metres. The wire format may need
    # conversion to centimetres or to cloud-frame coords — verify
    # against legacy device.py spot-mow handler. This stub uses metres
    # directly; adjust if legacy converts.
    return {"point": [float(x), float(y)]}


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
        "routed_t": "TASK", "routed_o": 101,
        "payload_fn": _zone_mow_payload,
    },
    MowerAction.START_EDGE_MOW: {
        "routed_t": "TASK", "routed_o": 101,
        "payload_fn": _edge_mow_payload,
    },
    # START_SPOT_MOW — op=103 (spotMower) is confirmed in legacy device.py:289,
    # but the legacy dispatches via DreameMowerAction.START_CUSTOM (a property-set
    # action at siid=5/aiid=5 with STATUS+CLEANING_PROPERTIES piid payload), not
    # via the routed-action TASK envelope. The TASK/op=103 wire format is therefore
    # unconfirmed for g2408. Marked local_only until F5 reverse-engineers the
    # exact CLEANING_PROPERTIES payload for spot-mow (see legacy clean_spot()).
    # TODO(F5): wire START_SPOT_MOW when spot-mow protocol path is understood.
    MowerAction.START_SPOT_MOW: {
        "local_only": True,
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
    # FINALIZE_SESSION — integration-local; F5 wires the actual implementation.
    MowerAction.FINALIZE_SESSION: {"local_only": True},
}
