"""MowerStateMachine — single owner of the multi-dim mower state.

Inputs (MQTT slots, cloud-poll results, heartbeat ticks) in;
StateSnapshot out. Pure-Python; the only HA dependency is the
optional Store used by load_persisted / save_persisted (added later).
"""
from __future__ import annotations

import logging
from typing import Any

from ..protocol.mode_enum import MOW_MODE_CODES
from .state_snapshot import StateSnapshot

_LOGGER = logging.getLogger(__name__)


class MowerStateMachine:
    """Multi-dim mower state machine."""

    HB_STALENESS_S: int = 90

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
            return self._apply_battery_percent(int(value), now_unix)
        if key == (3, 2):
            return self._apply_charging(bool(int(value)), now_unix)

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
        from .state_snapshot import CurrentActivity, MowSession, PositioningHealth

        activity_map: dict[int, CurrentActivity] = {
            1: CurrentActivity.MOWING,
            2: CurrentActivity.IDLE,
            5: CurrentActivity.RETURNING,
        }
        if task_state == 6:
            # CHARGE_RESUME means "mid-session charging". Outside a session,
            # task_state=6 from idle-charging at the dock → IDLE (avoid the
            # misleading "Charging mid-session" label).
            new_activity = (
                CurrentActivity.CHARGE_RESUME
                if self._snapshot.mow_session == MowSession.IN_SESSION
                else CurrentActivity.IDLE
            )
        else:
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
        # Resuming mowing means the mower re-localized — clear a prior STUCK
        # (e.g. the 12:32 relocate-fail → Paused → auto-resume an hour later).
        if (
            task_state == 1
            and self._snapshot.positioning_health == PositioningHealth.STUCK
        ):
            updates["positioning_health"] = PositioningHealth.LOCALIZED
            freshness["positioning_health"] = now_unix
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
          33     = positioning / off-dock-relocate failure  → STUCK
        Other s2p2 codes only stamp raw_s2p2 for diagnostics.

        NB: s2p2=71 ("standby outside station too long → auto-return") is NOT a
        positioning failure (verified 2026-05-30); it carries no positioning
        side effect here — the s2p1=5 handler sets RETURNING. STUCK is derived
        from the orthogonal failure code 33, not a 71+31 combination (those two
        never co-occur in any probe log).
        """
        from .state_snapshot import (
            CurrentActivity,
            MowSession,
            Location,
            PositioningHealth,
        )

        updates: dict[str, Any] = {"raw_s2p2": event_code}
        freshness = dict(self._snapshot.field_freshness)
        freshness["raw_s2p2"] = now_unix

        if event_code in (50, 53):
            updates["mow_session"] = MowSession.IN_SESSION
            updates["current_activity"] = CurrentActivity.MOWING
            freshness["mow_session"] = now_unix
            freshness["current_activity"] = now_unix
        elif event_code == 33:
            # Positioning / off-dock-relocate failure (the real "stuck" signal).
            updates["positioning_health"] = PositioningHealth.STUCK
            updates["location"] = Location.OUTSIDE_KNOWN_AREA
            freshness["positioning_health"] = now_unix
            freshness["location"] = now_unix
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
            # Mow-variant ops (100-103) come from the canonical mode enum so
            # this map can't drift from the session-card labels / summary slugs.
            # 109 (cruise) and 10 (fast-mapping) are op-only — no OSS mode — so
            # they stay here. Patrol (108) is intentionally absent: it is not a
            # mow and currently maps to no activity change.
            op_map: dict[int, CurrentActivity] = {
                code: CurrentActivity.MOWING for code in MOW_MODE_CODES
            }
            op_map[109] = CurrentActivity.CRUISING_TO_POINT
            op_map[10] = CurrentActivity.FAST_MAPPING
            new_activity = op_map.get(op)
            if new_activity is not None and new_activity != self._snapshot.current_activity:
                updates["current_activity"] = new_activity
                freshness["current_activity"] = now_unix
            if op in MOW_MODE_CODES:
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

        Stale-cloud guard: cloud DOCK status lags by 5-10 min on g2408,
        sometimes reporting AT_DOCK while the mower is clearly mid-mow.
        When mow_session=IN_SESSION and we already believe location is
        ON_LAWN, ignore a cloud AT_DOCK claim. Telemetry-driven location
        is more trustworthy in that case.
        """
        from .state_snapshot import Location, MowSession
        connect = payload.get("connect_status")
        if connect is None:
            return self._snapshot
        new_location = Location.AT_DOCK if int(connect) == 1 else Location.ON_LAWN
        if (
            new_location == Location.AT_DOCK
            and self._snapshot.mow_session == MowSession.IN_SESSION
            and self._snapshot.location == Location.ON_LAWN
        ):
            return self._snapshot
        last_mqtt = self._snapshot.field_freshness.get("location", 0)
        if now_unix <= last_mqtt:
            return self._snapshot
        freshness = dict(self._snapshot.field_freshness)
        freshness["location"] = now_unix
        return self._replace(location=new_location, field_freshness=freshness)

    def end_session(self, now_unix: int) -> StateSnapshot:
        """Flip mow_session to BETWEEN_SESSIONS + activity to IDLE.

        Called from the coordinator's finalize gate (_fire_mowing_ended)
        when a session ends via cloud-summary archive OR the
        FINALIZE_INCOMPLETE path. The state machine otherwise only
        learns about session end via MQTT s2p1=2 or s2p2=48 — but
        the finalize gate can fire on a cloud-detected task_state
        transition (prev ∈ {0,4} → new ∈ {2,None}) that doesn't
        always have a matching MQTT push. Without this hook the
        state machine stays IN_SESSION + MOWING indefinitely while
        the lifecycle event correctly reports the session ended.
        """
        from .state_snapshot import CurrentActivity, MowSession
        updates: dict[str, Any] = {}
        freshness = dict(self._snapshot.field_freshness)
        if self._snapshot.mow_session != MowSession.BETWEEN_SESSIONS:
            updates["mow_session"] = MowSession.BETWEEN_SESSIONS
            freshness["mow_session"] = now_unix
        if self._snapshot.current_activity != CurrentActivity.IDLE:
            updates["current_activity"] = CurrentActivity.IDLE
            freshness["current_activity"] = now_unix
        if not updates:
            return self._snapshot
        updates["field_freshness"] = freshness
        return self._replace(**updates)

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

    def _reconcile_mow_activity(
        self, *, live_map_active: bool, area_mowed_m2: float | None,
    ) -> dict[str, Any]:
        """Mow-session / activity inference (R1-R5). Returns field updates only
        (freshness is derived by the caller). Rules are mutually exclusive."""
        from .state_snapshot import CurrentActivity, MowSession, Location
        updates: dict[str, Any] = {}

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

        # Inverse inference: state machine stuck at IN_SESSION but live_map
        # is no longer active. The finalize gate ended the session (lifecycle
        # event fired) but state machine wasn't notified — fall back to
        # BETWEEN_SESSIONS. New end_session() hook in coordinator catches the
        # forward path; this handles legacy stuck snapshots and any future
        # gap where the finalize→state-machine wire breaks.
        elif (
            self._snapshot.mow_session == MowSession.IN_SESSION
            and not live_map_active
        ):
            updates["mow_session"] = MowSession.BETWEEN_SESSIONS
            updates["current_activity"] = CurrentActivity.IDLE

        # Stuck-activity recovery: if state machine is IN_SESSION but
        # current_activity is a transient state (CHARGE_RESUME) that
        # never received its follow-up MQTT push, fall through to MOWING
        # whenever the mower is clearly off the dock. AT_DOCK with
        # CHARGE_RESUME is left alone — that's a legitimate charging mid
        # session.
        elif (
            self._snapshot.mow_session == MowSession.IN_SESSION
            and self._snapshot.current_activity == CurrentActivity.CHARGE_RESUME
            and self._snapshot.location != Location.AT_DOCK
            and area_mowed_m2 is not None
            and area_mowed_m2 > 0
        ):
            updates["current_activity"] = CurrentActivity.MOWING

        # Out-of-session CHARGE_RESUME → IDLE. After v1.0.10a3 the
        # _apply_s2p1_task_state handler only sets CHARGE_RESUME when
        # mow_session=IN_SESSION, but if the snapshot was persisted with
        # CHARGE_RESUME under the old logic, this self-heals on the next
        # tick rather than waiting for the next s2p1 MQTT push.
        elif (
            self._snapshot.mow_session == MowSession.BETWEEN_SESSIONS
            and self._snapshot.current_activity == CurrentActivity.CHARGE_RESUME
        ):
            updates["current_activity"] = CurrentActivity.IDLE

        # Mirror case: IN_SESSION + MOWING but mower has returned to the
        # dock without an MQTT signal we caught. The activity is stuck
        # at MOWING. The genuine state is some flavour of "at-dock mid
        # session" — pick CHARGE_RESUME since that's how the mower
        # behaves at a recharge boundary.
        elif (
            self._snapshot.mow_session == MowSession.IN_SESSION
            and self._snapshot.current_activity == CurrentActivity.MOWING
            and self._snapshot.location == Location.AT_DOCK
        ):
            updates["current_activity"] = CurrentActivity.CHARGE_RESUME

        return updates

    def _reconcile_location(
        self, *, position_x_m: float | None, position_y_m: float | None,
        dock_x_mm: float | None, dock_y_mm: float | None,
    ) -> dict[str, Any]:
        """Location inference (R6): AT_DOCK + position clearly off-dock → ON_LAWN.
        Returns field updates only (freshness derived by the caller)."""
        from .state_snapshot import Location
        updates: dict[str, Any] = {}

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

        return updates

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
        updates: dict[str, Any] = {
            **self._reconcile_mow_activity(
                live_map_active=live_map_active, area_mowed_m2=area_mowed_m2),
            **self._reconcile_location(
                position_x_m=position_x_m, position_y_m=position_y_m,
                dock_x_mm=dock_x_mm, dock_y_mm=dock_y_mm),
        }
        if not updates:
            return self._snapshot
        freshness = dict(self._snapshot.field_freshness)
        for field in updates:
            freshness[field] = now_unix
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

    def handle_misc_persisted(
        self,
        *,
        mowing_phase: int | None = None,
        task_state_code: int | None = None,
        slam_task_label: str | None = None,
        now_unix: int,
    ) -> StateSnapshot:
        """Persist last-known values for fields that otherwise live only in
        MowerState. After HA restart, the snapshot retains these so the
        entities don't go Unknown until the next live MQTT event."""
        updates: dict[str, Any] = {}
        freshness = dict(self._snapshot.field_freshness)
        for name, value in (
            ("mowing_phase", mowing_phase),
            ("task_state_code", task_state_code),
            ("slam_task_label", slam_task_label),
        ):
            if value is None:
                continue
            if getattr(self._snapshot, name) != value:
                updates[name] = value
                freshness[name] = now_unix
        if not updates:
            return self._snapshot
        updates["field_freshness"] = freshness
        return self._replace(**updates)

    def handle_pre_shadow_update(
        self,
        *,
        map_id: int,
        mowing_height_mm: int | None = None,
        mowing_efficiency: int | None = None,
        edgemaster: bool | None = None,
        now_unix: int,
    ) -> StateSnapshot:
        """Record the active map's PRE-family settings from an s6.2 push.

        The Dreame app pushes the full active-map profile (height +
        efficiency + edgemaster) via s6.2 whenever the user saves the
        settings page. We capture all three fields tagged with the
        active map_id so per-map entities can surface stored values
        for each map.

        No-op when map_id is None, when all three field values are None,
        or when none of the supplied values would actually change the
        existing shadow entry.

        See `docs/research/g2408-protocol.md` § s6.2 for the wire-shape
        derivation and the live test sequence that confirmed the
        per-map-shadow model.
        """
        if map_id is None:
            return self._snapshot
        current = dict(self._snapshot.pre_shadow_by_map_id)
        entry = dict(current.get(int(map_id), {}))
        changed = False
        if mowing_height_mm is not None and entry.get("mowing_height_mm") != int(mowing_height_mm):
            entry["mowing_height_mm"] = int(mowing_height_mm)
            changed = True
        if mowing_efficiency is not None and entry.get("mowing_efficiency") != int(mowing_efficiency):
            entry["mowing_efficiency"] = int(mowing_efficiency)
            changed = True
        if edgemaster is not None and entry.get("edgemaster") != bool(edgemaster):
            entry["edgemaster"] = bool(edgemaster)
            changed = True
        if not changed:
            return self._snapshot
        current[int(map_id)] = entry
        freshness = dict(self._snapshot.field_freshness)
        freshness[f"pre_shadow[{int(map_id)}]"] = now_unix
        return self._replace(
            pre_shadow_by_map_id=current,
            field_freshness=freshness,
        )

    def handle_position(
        self,
        *,
        x_m: float | None,
        y_m: float | None,
        north_m: float | None,
        east_m: float | None,
        now_unix: int,
    ) -> StateSnapshot:
        """Apply a position update from telemetry.

        Position is high-frequency telemetry but worth persisting so the
        "last known position" survives reboot. No-op on unchanged values.
        """
        updates: dict[str, Any] = {}
        freshness = dict(self._snapshot.field_freshness)
        for name, value in (
            ("position_x_m", x_m),
            ("position_y_m", y_m),
            ("position_north_m", north_m),
            ("position_east_m", east_m),
        ):
            if value is None:
                continue
            if getattr(self._snapshot, name) != value:
                updates[name] = value
                freshness[name] = now_unix
        if not updates:
            return self._snapshot
        updates["field_freshness"] = freshness
        return self._replace(**updates)

    def tick(self, now_unix: int) -> StateSnapshot:
        """Periodic resolver. Call ~every 10 seconds.

        Flips mqtt_connectivity → STALE if the HB gap exceeds HB_STALENESS_S.
        (positioning_health is now resolved synchronously: STUCK on s2p2=33,
        cleared on a mowing resume — no buffered-disambiguation step here.)
        """
        from .state_snapshot import Connectivity
        updates: dict[str, Any] = {}
        freshness = dict(self._snapshot.field_freshness)

        # HB staleness check
        last_hb = self._snapshot.last_heartbeat_unix
        if last_hb is not None and (now_unix - last_hb) > self.HB_STALENESS_S:
            if self._snapshot.mqtt_connectivity != Connectivity.STALE:
                updates["mqtt_connectivity"] = Connectivity.STALE
                freshness["mqtt_connectivity"] = now_unix

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

    def _apply_charging(
        self, new_value: bool, now_unix: int
    ) -> StateSnapshot:
        """Update charging, enforcing the at-dock invariant.

        Charging can only happen at the dock. When charging transitions
        False→True we therefore also set location=AT_DOCK if not
        already. This is the strongest at-dock signal we have — it
        even overrides the IN_SESSION+ON_LAWN suppression in
        _apply_cloud_dock.
        """
        from .state_snapshot import Location
        if self._snapshot.charging == new_value:
            return self._snapshot
        freshness = dict(self._snapshot.field_freshness)
        freshness["charging"] = now_unix
        updates: dict[str, Any] = {
            "charging": new_value,
            "field_freshness": freshness,
        }
        if new_value and self._snapshot.location != Location.AT_DOCK:
            updates["location"] = Location.AT_DOCK
            freshness["location"] = now_unix
        return self._replace(**updates)

    def _apply_battery_percent(
        self, new_value: int, now_unix: int
    ) -> StateSnapshot:
        """Update battery_percent, inferring charging=True on a rise.

        s3p2 (explicit charging flag) only fires on change, so after a
        mid-charge reload it can stay at whatever was persisted before.
        A rising battery is hard evidence the mower IS charging — use
        it as a fallback. Falling battery is left alone (could be a
        brief load spike; the firmware s3p2=0 path is authoritative
        for clearing the flag).
        """
        from .state_snapshot import Location
        prev = self._snapshot.battery_percent
        if prev == new_value:
            return self._snapshot
        freshness = dict(self._snapshot.field_freshness)
        freshness["battery_percent"] = now_unix
        updates: dict[str, Any] = {
            "battery_percent": new_value,
            "field_freshness": freshness,
        }
        # Only infer on rise, and only when we have a prior value to
        # compare against. The first observation cannot infer direction.
        if prev is not None and new_value > prev and not self._snapshot.charging:
            updates["charging"] = True
            freshness["charging"] = now_unix
            # Invariant: the only charging surface is the dock.
            if self._snapshot.location != Location.AT_DOCK:
                updates["location"] = Location.AT_DOCK
                freshness["location"] = now_unix
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
