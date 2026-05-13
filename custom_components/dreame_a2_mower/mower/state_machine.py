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

    HB_STALENESS_S: int = 90
    S2P2_71_WINDOW_S: int = 30

    def __init__(self) -> None:
        self._snapshot: StateSnapshot = StateSnapshot.initial()
        self._dirty: bool = False
        # s2p2=71 disambiguation buffer
        self._s2p2_71_pending_since: int | None = None
        self._s2p2_71_followups_codes: set[int] = set()
        self._s2p2_71_saw_returning: bool = False

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
        if self._s2p2_71_pending_since is not None and task_state == 5:
            self._s2p2_71_saw_returning = True

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
        # s2p2=71 disambiguation: start buffer on 71, record follow-ups otherwise
        if event_code == 71:
            self._s2p2_71_pending_since = now_unix
            self._s2p2_71_followups_codes = set()
            self._s2p2_71_saw_returning = False
        elif self._s2p2_71_pending_since is not None:
            self._s2p2_71_followups_codes.add(event_code)

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

    def seed_in_session(self, now_unix: int) -> StateSnapshot:
        """Flip mow_session to IN_SESSION as a coordinator-driven seed.

        Called from _restore_in_progress when an in_progress.json file
        is found on disk — its existence is proof that a real mow
        session was active before the reload. Telemetry-based reconcile
        can't see area_mowed_m2 after reload (it's not persisted), so
        we seed directly.

        Conservative:
        - Only flips when mow_session is BETWEEN_SESSIONS (never
          overwrites a real start event the state machine already saw).
        - Only sets current_activity to MOWING when it's still IDLE
          (preserves PAUSED / RETURNING / CHARGE_RESUME if those were
          already captured via cloud or post-restore MQTT).
        """
        from .state_snapshot import CurrentActivity, MowSession
        if self._snapshot.mow_session != MowSession.BETWEEN_SESSIONS:
            return self._snapshot
        updates: dict[str, Any] = {"mow_session": MowSession.IN_SESSION}
        freshness = dict(self._snapshot.field_freshness)
        freshness["mow_session"] = now_unix
        if self._snapshot.current_activity == CurrentActivity.IDLE:
            updates["current_activity"] = CurrentActivity.MOWING
            freshness["current_activity"] = now_unix
        updates["field_freshness"] = freshness
        return self._replace(**updates)

    # Distance (metres) from dock origin beyond which we infer ON_LAWN.
    # Larger than typical dock footprint, smaller than the shortest lawn.
    OFF_DOCK_THRESHOLD_M: float = 1.0

    def reconcile_from_telemetry(
        self,
        *,
        live_map_active: bool,
        area_mowed_m2: float | None,
        position_x_m: float | None,
        position_y_m: float | None,
        dock_x_mm: float | None,
        dock_y_mm: float | None,
        now_unix: int,
    ) -> StateSnapshot:
        """Cold-boot reconciliation from continuous telemetry.

        MQTT properties_changed only fires on CHANGE. After a mid-session
        integration restart we never receive the start events (s2p2=50,
        s2p1=1) — they fired hours ago. Telemetry (battery, position,
        area_mowed, live_map) keeps flowing, so we use it to infer that
        a session is in progress.

        Inferences are conservative and gated:
        - Mowing inference requires `area_mowed_m2 > 0` (a real mow signal),
          not just live_map activity, because cruise-to-point also drives
          live_map. Only flips BETWEEN_SESSIONS → IN_SESSION; never
          overwrites an already-known session.
        - Location inference requires AT_DOCK + a position clearly off the
          dock origin. Never overwrites AT_POINT / OUTSIDE_KNOWN_AREA.
        """
        from .state_snapshot import CurrentActivity, MowSession, Location

        updates: dict[str, Any] = {}
        freshness = dict(self._snapshot.field_freshness)

        # Mow-session inference: requires real mow evidence (area_mowed),
        # not just movement (which happens during cruise too).
        if (
            self._snapshot.mow_session == MowSession.BETWEEN_SESSIONS
            and live_map_active
            and area_mowed_m2 is not None
            and area_mowed_m2 > 0
        ):
            updates["mow_session"] = MowSession.IN_SESSION
            updates["current_activity"] = CurrentActivity.MOWING
            freshness["mow_session"] = now_unix
            freshness["current_activity"] = now_unix

        # Location inference: AT_DOCK + position clearly off-dock → ON_LAWN.
        # dock_*_mm is in millimetres, position_*_m in metres.
        if (
            self._snapshot.location == Location.AT_DOCK
            and position_x_m is not None
            and position_y_m is not None
        ):
            dock_x_m = (dock_x_mm or 0) / 1000.0
            dock_y_m = (dock_y_mm or 0) / 1000.0
            dx = position_x_m - dock_x_m
            dy = position_y_m - dock_y_m
            dist_m = (dx * dx + dy * dy) ** 0.5
            if dist_m > self.OFF_DOCK_THRESHOLD_M:
                updates["location"] = Location.ON_LAWN
                freshness["location"] = now_unix

        if not updates:
            return self._snapshot
        updates["field_freshness"] = freshness
        return self._replace(**updates)

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

    def tick(self, now_unix: int) -> StateSnapshot:
        """Periodic resolver. Call ~every 10 seconds.

        1) Flips mqtt_connectivity → STALE if HB gap exceeds HB_STALENESS_S.
        2) Resolves buffered s2p2=71 disambiguation:
           - Saw 31 or 33 → STUCK + OUTSIDE_KNOWN_AREA
           - Saw s2p1=5 (RETURNING) → auto-return (no positioning change;
             activity already set by s2p1 handler)
           - Neither → leave positioning_health untouched
        """
        from .state_snapshot import Connectivity, PositioningHealth, Location
        updates: dict[str, Any] = {}
        freshness = dict(self._snapshot.field_freshness)

        # 1) HB staleness check
        last_hb = self._snapshot.last_heartbeat_unix
        if last_hb is not None and (now_unix - last_hb) > self.HB_STALENESS_S:
            if self._snapshot.mqtt_connectivity != Connectivity.STALE:
                updates["mqtt_connectivity"] = Connectivity.STALE
                freshness["mqtt_connectivity"] = now_unix

        # 2) Resolve buffered s2p2=71
        pending = self._s2p2_71_pending_since
        if pending is not None and (now_unix - pending) >= self.S2P2_71_WINDOW_S:
            if 31 in self._s2p2_71_followups_codes or 33 in self._s2p2_71_followups_codes:
                updates["positioning_health"] = PositioningHealth.STUCK
                updates["location"] = Location.OUTSIDE_KNOWN_AREA
                freshness["positioning_health"] = now_unix
                freshness["location"] = now_unix
            elif self._s2p2_71_saw_returning:
                # Auto-return — leave positioning_health LOCALIZED
                # (current_activity was already set to RETURNING by s2p1 handler)
                pass
            else:
                _LOGGER.info(
                    "MowerStateMachine: s2p2=71 buffer expired with no "
                    "disambiguating follow-up; leaving positioning_health unchanged"
                )
            # Clear buffer either way
            self._s2p2_71_pending_since = None
            self._s2p2_71_followups_codes = set()
            self._s2p2_71_saw_returning = False

        if not updates:
            return self._snapshot
        updates["field_freshness"] = freshness
        return self._replace(**updates)

    async def save_persisted(self, store: Any) -> None:
        """Write the current snapshot to a Store-shaped object.

        `store` must implement `async_save(data: dict) -> coroutine`.
        Compatible with HA's homeassistant.helpers.storage.Store.
        """
        await store.async_save(self._snapshot.to_dict())
        self._clear_dirty()

    async def load_persisted(self, store: Any) -> None:
        """Restore snapshot from a Store-shaped object.

        `store` must implement `async_load() -> coroutine[dict | None]`.
        Returns None → snapshot stays at initial. Corrupt data → log
        warning and stay at initial.
        """
        raw = await store.async_load()
        if raw is None:
            return
        try:
            self._snapshot = StateSnapshot.from_dict(raw)
            self._dirty = False
        except (KeyError, ValueError, TypeError) as ex:
            _LOGGER.warning(
                "MowerStateMachine: load_persisted failed (%s) — keeping initial",
                ex,
            )

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
