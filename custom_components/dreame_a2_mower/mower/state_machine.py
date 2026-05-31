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

    # Prior s2p1 codes that indicate the mower is stationary/docked.
    # When s2p1 transitions INTO working(1) FROM one of these states, it is a
    # genuine undock — enter REPOSITIONING for the ~42s reorientation window.
    # Values: 6=CHARGING, 13=CHARGING_COMPLETED, 2=IDLE, 16=BATT_TEMP_HOLD.
    # (See inventory.yaml § s2p1 value_catalog for the full enum.)
    _DOCKED_PRIOR_STATES: frozenset[int] = frozenset({2, 6, 13, 16})

    # Minimum distance (metres) the mower must move from its REPOSITIONING
    # origin before handle_position exits REPOSITIONING → RETURNING on the
    # return leg. Mirrors _BETWEEN_SESSION_MOVE_THRESHOLD_M in _rendering.py;
    # chosen to be well above GPS jitter (< 0.1 m) but below a genuine
    # first-step (~0.5–1 m per s1p4 push during active driving).
    _RETURN_REPOSITION_MOVE_THRESHOLD_M: float = 0.3

    def _apply_s2p1_task_state(
        self, task_state: int, now_unix: int
    ) -> StateSnapshot:
        """s2p1 task_state code → current_activity.

        Task state codes:
          1 = working/mowing
          2 = task done (also closes mow_session)
          5 = returning to dock
          6 = charging (mid-mow charge-resume)

        Undock detection (REPOSITIONING):
          When task_state transitions INTO 1 ("Exiting the station") FROM a
          stationary/docked prior state (raw_s2p1 ∈ _DOCKED_PRIOR_STATES) AND
          mow_session is BETWEEN_SESSIONS (i.e. not a mid-mow recharge return),
          set current_activity=REPOSITIONING + location=ON_LAWN and clear any
          stale last_task_op. The op echo (~42s later) refines this to the real
          task activity via _apply_s2p50_task_envelope.

        Return-leg detection (REPOSITIONING):
          When task_state transitions INTO 5 ("Returning to dock") FROM a
          stationary at-point state (location == AT_POINT), the mower performs
          a ~26s reorientation dance before actually starting to drive home.
          Enter REPOSITIONING to represent this window. Exit to RETURNING when
          handle_position detects significant movement (> _RETURN_REPOSITION_MOVE_THRESHOLD_M),
          or when a subsequent s2p1 fires (the false-fire exit handles that via
          the standard activity map — second s2p1=5 → RETURNING).
        """
        from .state_snapshot import CurrentActivity, Location, MowSession, PositioningHealth

        freshness = dict(self._snapshot.field_freshness)
        freshness["raw_s2p1"] = now_unix
        updates: dict[str, Any] = {"raw_s2p1": task_state}

        # ---- REPOSITIONING entry: undock transition only ----
        if (
            task_state == 1
            and self._snapshot.raw_s2p1 in self._DOCKED_PRIOR_STATES
            and self._snapshot.mow_session == MowSession.BETWEEN_SESSIONS
        ):
            updates["current_activity"] = CurrentActivity.REPOSITIONING
            freshness["current_activity"] = now_unix
            # ON_LAWN at undock (same freshness approach as _apply_s2p50_task_envelope
            # so a stale cloud DOCK poll can't immediately revert it).
            if self._snapshot.location != Location.ON_LAWN:
                updates["location"] = Location.ON_LAWN
                freshness["location"] = now_unix
            # Clear stale last_task_op so a prior run's type (e.g. op=109
            # from a to-point session) doesn't corrupt the REPOSITIONING label
            # or make s2p1=1 route to CRUISING_TO_POINT on the next push.
            if self._snapshot.last_task_op is not None:
                updates["last_task_op"] = None
                freshness["last_task_op"] = now_unix
            # Clear STUCK if needed (undocking = new start attempt)
            if self._snapshot.positioning_health == PositioningHealth.STUCK:
                updates["positioning_health"] = PositioningHealth.LOCALIZED
                freshness["positioning_health"] = now_unix
            updates["field_freshness"] = freshness
            return self._replace(**updates)

        # ---- REPOSITIONING entry: return-leg transition (Bug 3 fix) ----
        # When s2p1=5 (returning) arrives while the mower is stationary at
        # AT_POINT (location == AT_POINT), the mower has NOT yet started moving
        # home — it performs a ~26s reorientation before driving.  Enter
        # REPOSITIONING so the activity sensor shows "Repositioning" during
        # this window instead of jumping straight to "Returning".
        # Gate: only from AT_POINT (not from ON_LAWN mid-drive or AT_DOCK).
        # Exit: handle_position detects movement > threshold → RETURNING (below).
        # OR: the false-fire exit resolves the next s2p1 push via standard map.
        if (
            task_state == 5
            and self._snapshot.location == Location.AT_POINT
            and self._snapshot.current_activity != CurrentActivity.REPOSITIONING
        ):
            updates["current_activity"] = CurrentActivity.REPOSITIONING
            freshness["current_activity"] = now_unix
            updates["field_freshness"] = freshness
            return self._replace(**updates)

        # ---- REPOSITIONING false-fire exit ----
        # If we're currently REPOSITIONING and s2p1 leaves the working state
        # without an op echo having arrived, resolve to the appropriate activity.
        # Gate: only exits REPOSITIONING — do not disrupt other activity states.
        # NOTE: this also handles the return-leg REPOSITIONING exit when a
        # second s2p1=5 arrives (false-fire maps 5 → RETURNING via activity_map).
        if (
            self._snapshot.current_activity == CurrentActivity.REPOSITIONING
            and task_state != 1
        ):
            # s2p1=2(idle/done), s2p1=5(returning), etc. while still REPOSITIONING
            # means the task was cancelled or aborted before the echo arrived.
            # Fall through to the standard activity map below.
            pass  # resolved by the standard mapping below

        # ---- Standard s2p1 mapping ----
        # BUG 2 fix: s2p1=1 during a to-point run (last_task_op=109) must
        # resolve to CRUISING_TO_POINT, not MOWING. The firmware emits s2p1=1
        # ("working") after the op=109 echo, which previously clobbered the
        # CRUISING_TO_POINT activity set by _apply_s2p50_task_envelope.
        # Only op=109 (cruise) needs this override; all real mow ops (100-103)
        # and unspecified ops (None) keep the unconditional MOWING mapping.
        task_state_1_activity = (
            CurrentActivity.CRUISING_TO_POINT
            if self._snapshot.last_task_op == 109
            else CurrentActivity.MOWING
        )
        activity_map: dict[int, CurrentActivity] = {
            1: task_state_1_activity,
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

    # Set of op codes that represent a task leaving the dock (accepted start command).
    # Used by _apply_s2p50_task_envelope to set location=ON_LAWN at command-time.
    # - 100-103: mow variants (globalMower, edge, zone, spot) — all in MOW_MODE_CODES
    # - 108: patrol (blades-up cruise, not a mow but still leaves the dock)
    # - 109: cruise-to-point (startCleanPoint)
    # op=10 (fast mapping) is intentionally absent — its dock-departure semantics
    # are unclear and it has no corresponding user-visible task.
    _TASK_START_OPS: frozenset[int] = frozenset({100, 101, 102, 103, 108, 109})

    def _apply_s2p50_task_envelope(
        self, envelope: Any, now_unix: int
    ) -> StateSnapshot:
        """TASK echo: {t:'TASK', d:{o:<op>, exe:bool, status:bool, ...}}.

        - status=True: dispatch current_activity by op code; mow ops
          (100/101/102/103) also enter mow_session=IN_SESSION.
          Any op in _TASK_START_OPS also sets location=ON_LAWN immediately —
          the mower undocks at command-time, not ~45s later when s1p4 position
          telemetry resumes (the reorientation window where s1p4 is silent).
          This prevents the reconcile rule IN_SESSION+MOWING+AT_DOCK→CHARGE_RESUME
          from corrupting the activity during the silent window.
        - status=False: still record last_task_op for diagnostics, but
          don't change activity or location (firmware rejected the task)
        - op=109 (cruise) and op=10 (fast mapping) do NOT enter mow_session
        """
        from .state_snapshot import CurrentActivity, Location, MowSession
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
            # they stay here. Patrol (108) is intentionally absent from the
            # activity map: it has no distinct ActivityEnum value and maps to
            # no HA-side activity change (it just leaves the dock).
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
            # Command-time location: any accepted task-start op leaves the dock.
            # Set ON_LAWN immediately so:
            #   1. The entity shows the correct location from command-time, not ~45s
            #      later when s1p4 position telemetry resumes (reorientation window).
            #   2. The reconcile rule IN_SESSION+MOWING+AT_DOCK→CHARGE_RESUME in
            #      _reconcile_mow_activity cannot fire — location is already ON_LAWN.
            # Scope: _TASK_START_OPS only (mow 100-103, patrol 108, cruise 109).
            # op=10 (fast mapping) is intentionally excluded (unclear dock semantics).
            # Freshness is stamped so a stale cloud DOCK poll can't immediately
            # revert ON_LAWN to AT_DOCK (the MQTT-primary freshness guard in
            # _apply_cloud_dock only skips when now_unix <= last_mqtt).
            if op in self._TASK_START_OPS and self._snapshot.location != Location.ON_LAWN:
                updates["location"] = Location.ON_LAWN
                freshness["location"] = now_unix
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
        # Clear last_task_op at session-end. The live-map renderer treats a
        # cruise op (108/109) in the snapshot as "a non-mow task is still in
        # progress" and skips the striped pre-start preview. After a to-point
        # run finalizes ON ARRIVAL the session is over but last_task_op stayed
        # at 109, so the map kept showing flat green instead of reverting to
        # the idle stripes. Clearing it here (the single session-end hook used
        # by every finalize path) makes the render revert to the same idle
        # preview it shows at the dock. Safe: the only other reader of the
        # snapshot's last_task_op is the s2p1=1→CRUISING_TO_POINT override,
        # which only matters during an active cruise; the next undock's
        # REPOSITIONING entry re-clears it anyway.
        if self._snapshot.last_task_op is not None:
            updates["last_task_op"] = None
            freshness["last_task_op"] = now_unix
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

        Return-leg REPOSITIONING exit (Bug 3 fix):
          When current_activity==REPOSITIONING and location==AT_POINT, the mower
          is in the return-leg reorientation window.  Once the mower moves more
          than _RETURN_REPOSITION_MOVE_THRESHOLD_M from the snapshot's position
          at REPOSITIONING entry, transition to RETURNING.  This is distinct from
          the undock REPOSITIONING (location==ON_LAWN), which exits via the op
          echo (~42s later), not via position delta.
        """
        from .state_snapshot import CurrentActivity, Location
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

        # Return-leg REPOSITIONING exit: mower entered REPOSITIONING from AT_POINT
        # (s2p1=5 while location==AT_POINT, handled in _apply_s2p1_task_state).
        # Exit to RETURNING when position has moved significantly from the
        # snapshot's last-known position (the AT_POINT standstill coordinates).
        # Gate: location must still be AT_POINT (not ON_LAWN = undock REPOSITIONING).
        if (
            self._snapshot.current_activity == CurrentActivity.REPOSITIONING
            and self._snapshot.location == Location.AT_POINT
            and x_m is not None
            and y_m is not None
        ):
            prev_x = self._snapshot.position_x_m
            prev_y = self._snapshot.position_y_m
            if prev_x is not None and prev_y is not None:
                dx = x_m - prev_x
                dy = y_m - prev_y
                dist_m = (dx * dx + dy * dy) ** 0.5
                if dist_m > self._RETURN_REPOSITION_MOVE_THRESHOLD_M:
                    updates["current_activity"] = CurrentActivity.RETURNING
                    freshness["current_activity"] = now_unix
                    # Update location to ON_LAWN — the mower is now moving home.
                    # Stamped with freshness so stale cloud AT_POINT won't revert.
                    if self._snapshot.location != Location.ON_LAWN:
                        updates["location"] = Location.ON_LAWN
                        freshness["location"] = now_unix

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
