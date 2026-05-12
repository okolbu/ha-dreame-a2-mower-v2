"""MowerStateMachine — single owner of the multi-dim mower state.

Inputs (MQTT slots, cloud-poll results, heartbeat ticks) in;
StateSnapshot out. Pure-Python; the only HA dependency is the
optional Store used by load_persisted / save_persisted (added later).
"""
from __future__ import annotations

import logging
from typing import Any

from .state_snapshot import StateSnapshot

_LOGGER = logging.getLogger(__name__)


class MowerStateMachine:
    """Multi-dim mower state machine."""

    def __init__(self) -> None:
        self._snapshot: StateSnapshot = StateSnapshot.initial()
        self._dirty: bool = False

    def snapshot(self) -> StateSnapshot:
        """Cheap accessor — returns the current immutable snapshot."""
        return self._snapshot

    def _replace(self, **kwargs: Any) -> StateSnapshot:
        """Replace snapshot fields, marking dirty if changed."""
        import dataclasses
        new = dataclasses.replace(self._snapshot, **kwargs)
        if new != self._snapshot:
            self._snapshot = new
            self._dirty = True
        return new

    def is_dirty(self) -> bool:
        return self._dirty

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _clear_dirty(self) -> None:
        self._dirty = False

    def handle_mqtt_property(
        self, siid: int, piid: int, value: Any, now_unix: int
    ) -> StateSnapshot:
        """Apply one MQTT property change. Returns the (possibly new) snapshot.

        Unknown (siid, piid) combinations are logged at DEBUG and the
        snapshot is returned unchanged.
        """
        key = (int(siid), int(piid))

        # Scalar slots — battery, charging, etc.
        if key == (3, 1):
            return self._apply_scalar("battery_percent", int(value), now_unix)
        if key == (3, 2):
            return self._apply_scalar("charging", bool(int(value)), now_unix)

        if key == (2, 1):
            return self._apply_s2p1_task_state(int(value), now_unix)
        if key == (2, 2):
            return self._apply_s2p2_event(int(value), now_unix)
        if key == (2, 50):
            return self._apply_s2p50_task_envelope(value, now_unix)
        if key == (2, 56):
            return self._apply_s2p56_lifecycle(value, now_unix)

        _LOGGER.debug(
            "MowerStateMachine: unrecognised slot s%dp%d value=%r",
            siid, piid, value,
        )
        return self._snapshot

    def _apply_s2p1_task_state(
        self, task_state: int, now_unix: int
    ) -> StateSnapshot:
        """s2p1 task_state code → current_activity.

        Task state codes:
          1 = working/mowing
          2 = task done (also closes mow_session)
          5 = returning to dock
          6 = charging (mid-mow charge-resume)
        """
        from .state_snapshot import CurrentActivity, MowSession
        activity_map: dict[int, CurrentActivity] = {
            1: CurrentActivity.MOWING,
            2: CurrentActivity.IDLE,
            5: CurrentActivity.RETURNING,
            6: CurrentActivity.CHARGE_RESUME,
        }
        new_activity = activity_map.get(
            task_state, self._snapshot.current_activity
        )
        new_session = self._snapshot.mow_session
        if task_state == 2:
            new_session = MowSession.BETWEEN_SESSIONS

        freshness = dict(self._snapshot.field_freshness)
        freshness["raw_s2p1"] = now_unix
        updates: dict[str, Any] = {"raw_s2p1": task_state}
        if new_activity != self._snapshot.current_activity:
            updates["current_activity"] = new_activity
            freshness["current_activity"] = now_unix
        if new_session != self._snapshot.mow_session:
            updates["mow_session"] = new_session
            freshness["mow_session"] = now_unix
        updates["field_freshness"] = freshness
        return self._replace(**updates)

    def _apply_s2p2_event(
        self, event_code: int, now_unix: int
    ) -> StateSnapshot:
        """s2p2 event code → side effects on mow_session / activity / location.

        Notable codes:
          50, 53 = mowing_started / scheduled_mowing_started → enter session
          48     = mowing_complete                          → leave session
          75     = arrived_at_maintenance_point             → location AT_POINT
        Other s2p2 codes only stamp raw_s2p2 for diagnostics.
        """
        from .state_snapshot import CurrentActivity, MowSession, Location
        updates: dict[str, Any] = {"raw_s2p2": event_code}
        freshness = dict(self._snapshot.field_freshness)
        freshness["raw_s2p2"] = now_unix

        if event_code in (50, 53):
            updates["mow_session"] = MowSession.IN_SESSION
            updates["current_activity"] = CurrentActivity.MOWING
            freshness["mow_session"] = now_unix
            freshness["current_activity"] = now_unix
        elif event_code == 48:
            updates["mow_session"] = MowSession.BETWEEN_SESSIONS
            updates["current_activity"] = CurrentActivity.IDLE
            freshness["mow_session"] = now_unix
            freshness["current_activity"] = now_unix
        elif event_code == 75:
            updates["location"] = Location.AT_POINT
            updates["current_activity"] = CurrentActivity.AT_POINT
            freshness["location"] = now_unix
            freshness["current_activity"] = now_unix

        updates["field_freshness"] = freshness
        return self._replace(**updates)

    def _apply_s2p50_task_envelope(
        self, envelope: Any, now_unix: int
    ) -> StateSnapshot:
        """TASK echo: {t:'TASK', d:{o:<op>, exe:bool, status:bool, ...}}.

        - status=True: dispatch current_activity by op code; mow ops
          (100/101/102/103) also enter mow_session=IN_SESSION
        - status=False: still record last_task_op for diagnostics, but
          don't change activity (firmware rejected the task)
        - op=109 (cruise) and op=10 (fast mapping) do NOT enter mow_session
        """
        from .state_snapshot import CurrentActivity, MowSession
        if not isinstance(envelope, dict):
            return self._snapshot
        d = envelope.get("d")
        if not isinstance(d, dict):
            return self._snapshot
        op = d.get("o")
        if not isinstance(op, int):
            return self._snapshot
        # Absent "status" key means accepted (True); only False = rejected
        status = bool(d.get("status", True))

        updates: dict[str, Any] = {"last_task_op": op}
        freshness = dict(self._snapshot.field_freshness)
        freshness["last_task_op"] = now_unix

        if status:
            op_map: dict[int, CurrentActivity] = {
                100: CurrentActivity.MOWING,
                101: CurrentActivity.MOWING,  # edge variant
                102: CurrentActivity.MOWING,  # zone variant
                103: CurrentActivity.MOWING,  # spot variant
                109: CurrentActivity.CRUISING_TO_POINT,
                10:  CurrentActivity.FAST_MAPPING,
            }
            new_activity = op_map.get(op)
            if new_activity is not None and new_activity != self._snapshot.current_activity:
                updates["current_activity"] = new_activity
                freshness["current_activity"] = now_unix
            if op in (100, 101, 102, 103):
                if self._snapshot.mow_session != MowSession.IN_SESSION:
                    updates["mow_session"] = MowSession.IN_SESSION
                    freshness["mow_session"] = now_unix
        updates["field_freshness"] = freshness
        return self._replace(**updates)

    def _apply_s2p56_lifecycle(
        self, envelope: Any, now_unix: int
    ) -> StateSnapshot:
        """s2p56 = {status: [[task_id, lifecycle_stage]]}.

        Stage 2 in a cruise context (CRUISING_TO_POINT) → arrived AT_POINT.
        Stage 2 in other contexts is handled by other slots (s2p1=2 / s2p2=48).
        """
        from .state_snapshot import CurrentActivity
        if not isinstance(envelope, dict):
            return self._snapshot
        statuses = envelope.get("status")
        if not isinstance(statuses, list) or not statuses:
            return self._snapshot
        first = statuses[0]
        if not isinstance(first, list) or len(first) < 2:
            return self._snapshot
        stage = first[1]
        if stage == 2 and self._snapshot.current_activity == CurrentActivity.CRUISING_TO_POINT:
            freshness = dict(self._snapshot.field_freshness)
            freshness["current_activity"] = now_unix
            return self._replace(
                current_activity=CurrentActivity.AT_POINT,
                field_freshness=freshness,
            )
        return self._snapshot

    def handle_cloud_poll(
        self, source: str, payload: dict[str, Any], now_unix: int
    ) -> StateSnapshot:
        """Apply a cloud-poll result.

        Per-field precedence: only overwrite a field when the cloud
        poll's `now_unix` is GREATER than the field's last MQTT update
        stamp in `field_freshness`. Stale cloud-cached values that
        carry a now_unix older than our last MQTT update for the same
        field are silently ignored — MQTT-primary wins.

        Unknown sources are silently no-op (returns snapshot unchanged).
        """
        if source == "DOCK":
            return self._apply_cloud_dock(payload, now_unix)
        return self._snapshot

    def _apply_cloud_dock(
        self, payload: dict[str, Any], now_unix: int
    ) -> StateSnapshot:
        """CFG.DOCK payload → location.

        connect_status=1 → AT_DOCK; connect_status=0 → ON_LAWN.
        Skips when field freshness > now_unix (MQTT was fresher).
        Skips when value already matches (no-op).
        """
        from .state_snapshot import Location
        connect = payload.get("connect_status")
        if connect is None:
            return self._snapshot
        new_location = Location.AT_DOCK if int(connect) == 1 else Location.ON_LAWN
        last_mqtt = self._snapshot.field_freshness.get("location", 0)
        if now_unix <= last_mqtt:
            return self._snapshot
        freshness = dict(self._snapshot.field_freshness)
        freshness["location"] = now_unix
        return self._replace(location=new_location, field_freshness=freshness)

    def handle_heartbeat(self, hb: Any, now_unix: int) -> StateSnapshot:
        """Apply a decoded s1p1 heartbeat (from protocol.heartbeat.Heartbeat).

        Always updates last_heartbeat_unix + sets mqtt_connectivity = ONLINE.
        pin_required and wifi_rssi_dbm only update (and freshness only bumps)
        when their value changes.
        """
        from .state_snapshot import Connectivity
        freshness = dict(self._snapshot.field_freshness)
        freshness["last_heartbeat_unix"] = now_unix
        freshness["mqtt_connectivity"] = now_unix
        updates: dict[str, Any] = {
            "last_heartbeat_unix": now_unix,
            "mqtt_connectivity": Connectivity.ONLINE,
        }
        if hb.emergency_stop != self._snapshot.pin_required:
            updates["pin_required"] = hb.emergency_stop
            freshness["pin_required"] = now_unix
        if hb.wifi_rssi_dbm != self._snapshot.wifi_rssi_dbm:
            updates["wifi_rssi_dbm"] = hb.wifi_rssi_dbm
            freshness["wifi_rssi_dbm"] = now_unix
        updates["field_freshness"] = freshness
        return self._replace(**updates)

    def _apply_scalar(
        self, field_name: str, new_value: Any, now_unix: int
    ) -> StateSnapshot:
        """Update a scalar field with freshness stamping.

        No-op on same value (returns current snapshot, does not bump
        the field's freshness timestamp).
        """
        current = getattr(self._snapshot, field_name)
        if current == new_value:
            return self._snapshot
        new_freshness = dict(self._snapshot.field_freshness)
        new_freshness[field_name] = now_unix
        return self._replace(
            **{field_name: new_value},
            field_freshness=new_freshness,
        )
