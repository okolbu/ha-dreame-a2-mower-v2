"""mqtt_handlers mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..archive.lidar import LidarArchive
from ..archive.session import ArchivedSession, SessionArchive
from ..wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from ..cloud_client import DreameA2CloudClient
from ..const import (
    CONF_COUNTRY,
    CONF_LIDAR_ARCHIVE_KEEP,
    CONF_LIDAR_ARCHIVE_MAX_MB,
    CONF_PASSWORD,
    CONF_SESSION_ARCHIVE_KEEP,
    CONF_STATION_BEARING_DEG,
    CONF_USERNAME,
    DEFAULT_LIDAR_ARCHIVE_KEEP,
    DEFAULT_LIDAR_ARCHIVE_MAX_MB,
    DEFAULT_SESSION_ARCHIVE_KEEP,
    DOMAIN,
    EVENT_TYPE_DOCK_ARRIVED,
    EVENT_TYPE_DOCK_DEPARTED,
    EVENT_TYPE_MOWING_ENDED,
    EVENT_TYPE_MOWING_PAUSED,
    EVENT_TYPE_MOWING_RESUMED,
    EVENT_TYPE_MOWING_STARTED,
    LOG_NOVEL_KEY_SESSION_SUMMARY,
    LOG_NOVEL_PROPERTY,
    LOG_NOVEL_VALUE,
    LOGGER,
)
from ..inventory.loader import load_inventory
from ..live_map.finalize import RETRY_INTERVAL_SECONDS, FinalizeAction
from ..live_map.finalize import decide as _finalize_decide
from ..live_map.state import LiveMapState
from ..mower.actions import ACTION_TABLE, MowerAction
from ..mower.property_mapping import PROPERTY_MAPPING, resolve_field
from ..mower.state import ChargingStatus, MowerState
from ..mower.state_machine import MowerStateMachine
from ..mqtt_client import DreameA2MqttClient
from ..observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from ._snapshot import build_settings_snapshot_v2
from ..protocol import heartbeat as _heartbeat

from ._property_apply import (
    _BLOB_SLOTS,
    _INVENTORY,
    _SESSION_SUMMARY_CHECK,
    _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_EVENT_TYPES,
    S2P2_UNKNOWN_EVENT_TYPE,
    _apply_consumables,
    _apply_s1p1_heartbeat,
    _apply_s1p4_telemetry,
    _apply_s2p51_settings,
    _coerce_blob,
    _consumable_pct_remaining,
    _project_north_east,
    apply_property_to_state,
)

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _MqttHandlersMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    def _apply_mapl(self, mapl: Any) -> None:
        """Update _active_map_id from a MAPL response.

        MAPL is a list of rows, each row is `[map_id, is_active, ?, ?, ?]`.
        Sets `_active_map_id` to the row whose col 1 == 1. If no row
        matches (transient), keep the previous value. Bad payloads are
        ignored.

        When `_active_map_id` actually changes, fires `async_update_listeners`
        so camera + select entities push their new state to the frontend
        without waiting for the next full coordinator broadcast.
        """
        if not isinstance(mapl, list):
            return
        prev_active = self._active_map_id
        for row in mapl:
            if not isinstance(row, list) or len(row) < 2:
                continue
            try:
                if int(row[1]) == 1:
                    new_active = int(row[0])
                    if new_active != prev_active:
                        self._active_map_id = new_active
                        # Re-apply cloud_state → MowerState so SETTINGS-keyed
                        # fields (settings_mowing_height, settings_edge_mowing_*,
                        # settings_obstacle_avoidance_*, settings_obstacle_avoidance_ai)
                        # populate now that we know which map is active. On cold
                        # start _refresh_cloud_state runs first and sees
                        # _active_map_id=None, so without this re-apply the
                        # SETTINGS-driven entities stay unavailable until the
                        # next 2-min refresh.
                        if getattr(self, "cloud_state", None) is not None:
                            self._apply_cloud_state_to_mower_state()
                        # Re-render the live-map PNG so DreameA2MapCamera
                        # serves the new active map immediately. Without
                        # this, _main_view_png stays at the previous map's
                        # render until the next 2-min cloud refresh or a
                        # live-trail event — observed as ~1-minute lag
                        # between app-side map flip and the dashboard
                        # live-map card updating (2026-05-14).
                        hass = getattr(self, "hass", None)
                        if hass is not None:
                            hass.async_create_task(self._render_main_view())
                        # Fire listeners so camera + select push state to the
                        # frontend without waiting for the next coordinator
                        # broadcast.
                        update_listeners = getattr(self, "async_update_listeners", None)
                        if callable(update_listeners):
                            update_listeners()
                    self._sync_map_subdevices()
                    return
            except (TypeError, ValueError):
                continue
        # No row matched; keep previous _active_map_id (do nothing).
        self._sync_map_subdevices()

    def _on_mqtt_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Dispatcher for inbound MQTT messages.

        Handles two method types:
        - ``properties_changed`` — individual property pushes (siid/piid/value).
        - ``event_occured`` — event notifications (siid/eiid + arguments list).
          siid=4 eiid=1 carries the OSS object name in arguments[piid=9].
        """
        method = payload.get("method")
        if method == "properties_changed":
            params = payload.get("params") or []
            for p in params:
                if "siid" in p and "piid" in p:
                    self.handle_property_push(
                        siid=int(p["siid"]),
                        piid=int(p["piid"]),
                        value=p.get("value"),
                    )
                    import time as _time
                    _now_unix = int(_time.time())
                    _sm_siid = int(p["siid"])
                    _sm_piid = int(p["piid"])
                    _sm_value = p.get("value")
                    if (_sm_siid, _sm_piid) == (1, 1):
                        # s1p1 heartbeat — decode and route to handle_heartbeat.
                        try:
                            _blob = _coerce_blob(_sm_value, "s1.1")
                            if _blob is not None:
                                _hb = _heartbeat.decode_s1p1(_blob)
                                self.state_machine.handle_heartbeat(
                                    hb=_hb, now_unix=_now_unix
                                )
                                # WiFi fingerprint capture (v1.0.10a6+):
                                # pair the heartbeat's wifi_rssi_dbm with
                                # the most recent live position so the
                                # heatmap→map_id matcher has per-session
                                # (x_m, y_m, rssi_dbm, ts) tuples to score
                                # against incoming heatmaps. Gate on
                                # is_active() so we don't pollute the
                                # next session with idle-time samples.
                                try:
                                    _rssi = getattr(_hb, "wifi_rssi_dbm", None)
                                    _px = self.data.position_x_m
                                    _py = self.data.position_y_m
                                    if (
                                        _rssi is not None
                                        and _px is not None
                                        and _py is not None
                                        and self.live_map.is_active()
                                    ):
                                        if self.live_map.append_wifi_sample(
                                            _px, _py, _rssi, _now_unix
                                        ):
                                            self._live_map_dirty = True
                                except Exception:
                                    LOGGER.exception("append_wifi_sample failed")
                        except Exception:
                            LOGGER.exception("state_machine.handle_heartbeat failed")
                    else:
                        try:
                            self.state_machine.handle_mqtt_property(
                                siid=_sm_siid,
                                piid=_sm_piid,
                                value=_sm_value,
                                now_unix=_now_unix,
                            )
                        except Exception:
                            LOGGER.exception("state_machine.handle_mqtt_property failed")
        elif method == "event_occured":
            # F5.6.1: capture OSS object name from siid=4 eiid=1
            params = payload.get("params") or {}
            siid = int(params.get("siid", 0))
            eiid = int(params.get("eiid", 0))
            if siid == 4 and eiid == 1:
                arguments = params.get("arguments") or []
                self.hass.loop.call_soon_threadsafe(
                    lambda args=arguments: self.hass.loop.create_task(
                        self._handle_event_occured(args)
                    )
                )

    def _on_state_update(self, new_state: MowerState, now_unix: int) -> MowerState:
        """Hook fired after apply_property_to_state. Updates LiveMapState
        based on s2p56 transitions and appends s1p4 positions to the
        current leg.

        Returns a possibly-modified MowerState (with session_active /
        session_started_unix / session_track_segments synced from LiveMapState).
        """
        new_task_state = new_state.task_state_code
        prev = self._prev_task_state

        # Mark that we've now seen a real task_state from MQTT so the
        # finalize gate can distinguish "task is genuinely idle/end"
        # from "task_state_code defaulted to None because we just
        # booted into an MQTT-quiet window". Latches once observed —
        # subsequent transitions to None are then legitimately a
        # session-end signal.
        if new_task_state is not None:
            self._real_task_state_observed = True

        # v1.0.0a18: task_state_code semantics changed when the s2.56
        # extract_value was fixed to read status[0][1] (the sub-state).
        # New mapping: 0 = running, 4 = paused-pending-resume,
        # None = no task (status: []). begin_session fires on any
        # transition from None to a non-None task; the 4 → 0 recharge
        # resume just continues appending to the track (the pause→resume
        # time gap becomes a pen-up boundary at render/finalize time).
        if new_task_state != prev:
            # v1.0.0a48: bumped to WARNING so the trail is visible in
            # the HA default log without enabling DEBUG. Each mow only
            # produces a handful of these so noise stays low.
            LOGGER.warning(
                "[F5] task_state_code transition %r → %r (live_map.is_active=%s)",
                prev, new_task_state, self.live_map.is_active(),
            )
        # Begin a session whenever we transition from a non-active code
        # (None=idle, 2=complete) to an active code (0=running,
        # 4=paused). prev=4→new=0 is the recharge-resume case which
        # starts a new leg rather than a new session.
        is_active_now = new_task_state in (0, 4)
        was_active_before = prev in (0, 4)
        if is_active_now and not was_active_before and not self.live_map.is_active():
            # Skip begin_session when live_map is already active — that
            # means _restore_in_progress repopulated legs/started_unix
            # from disk (mid-mow HA restart). begin_session would clear
            # legs to [[]] and reset started_unix to now_unix, abandoning
            # the pre-restart trail. Just continue appending to the
            # restored leg.
            self.live_map.begin_session(now_unix)
            # Snapshot battery % at session start so the archive consumer
            # has a cheap start/end SoC pair without scanning the full
            # battery_samples list. None when battery_level isn't known
            # yet — the first s3p1 push will still populate samples.
            if new_state.battery_level is not None:
                try:
                    self.live_map.charge_at_start = int(new_state.battery_level)
                except (TypeError, ValueError):
                    pass
            # Snapshot the FULL firmware state at session start (settings_snapshot v2 —
            # per_map + device_wide + peripheral + forensic). Replaces the v1 narrow
            # per-map-only dict; v1 archive consumers continue to read the per_map
            # subsection via the v1-fallback path in session_card.py.
            self.live_map.settings_snapshot = build_settings_snapshot_v2(
                self, captured_at_unix=int(now_unix)
            )
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_STARTED,
                {
                    "at_unix": int(now_unix),
                    "action_mode": (
                        new_state.action_mode.value
                        if new_state.action_mode is not None
                        else None
                    ),
                    "target_area_m2": new_state.target_area_m2,
                },
            )
            # Re-poll MAPL so the live trail lands on the firmware's
            # current active map, even if the last 2-min cloud refresh was
            # before the user switched maps.
            hass = getattr(self, "hass", None)
            if hass is not None:
                hass.async_create_task(self._refresh_mapl())
        elif (
            new_task_state == 4
            and prev != 4
            and self.live_map.is_active()
        ):
            # Mid-mow pause. Previously gated on `prev == 0` exactly,
            # but a transient `0 → None` observation (occasional MQTT
            # parse blip; system_log shows "[F5] task_state_code
            # transition 0 → None" entries) overwrites _prev_task_state
            # to None, after which the true `0 → 4` pause arrives as
            # `None → 4` and the strict prev==0 check skips it.
            # Resume still fires (prev becomes 4 when pause finally
            # latches) but the pause event was lost.
            #
            # Generalise: pause fires on any "was-not-already-paused"
            # → "now paused" transition while the live_map is active
            # (i.e., we're genuinely mid-session). Live_map.is_active
            # gates against firing pause when the integration first
            # observes task_state=4 on boot before any session is
            # running.
            #
            # Reason is best-effort: if the current MowerState exposes
            # an obvious cause use it, otherwise "unknown".
            reason = "unknown"
            if new_state.battery_level is not None and new_state.battery_level <= 20:
                reason = "recharge_required"
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_PAUSED,
                {
                    "at_unix": int(now_unix),
                    "area_mowed_m2": new_state.area_mowed_m2,
                    "reason": reason,
                },
            )
        elif prev == 4 and new_task_state == 0:
            # Recharge-resume. No explicit leg break needed in the track
            # model: the pause→resume time gap naturally creates a pen-up
            # boundary that derive_render_legs() splits on at render time.
            self._fire_lifecycle(
                EVENT_TYPE_MOWING_RESUMED,
                {
                    "at_unix": int(now_unix),
                    "area_mowed_m2": new_state.area_mowed_m2,
                },
            )

        # Telemetry append: if session is active and a position is available
        # and something changed this tick, append the current position.
        if (
            self.live_map.is_active()
            and new_state.position_x_m is not None
            and new_state.position_y_m is not None
            and (new_state != self.data)  # something changed
        ):
            import time as _time
            before_pts = self.live_map.total_points()
            self.live_map.append_point(
                t=_time.time(),
                x_m=new_state.position_x_m,
                y_m=new_state.position_y_m,
                area_m2=(new_state.area_mowed_m2 or 0.0),
                heading_deg=new_state.position_heading_deg,
            )
            # Mark dirty if a point was actually added (dedup may have skipped it).
            if self.live_map.total_points() > before_pts:
                self._live_map_dirty = True
                # v1.0.0a18: throttle live-trail re-renders to ~1/s so
                # the camera entity reflects the moving mower without
                # PIL re-rendering on every 5-Hz s1.4 push.
                self._live_trail_dirty = True
                if now_unix - self._last_live_render_unix >= 1.0:
                    self._last_live_render_unix = float(now_unix)
                    self._live_trail_dirty = False
                    hass = getattr(self, "hass", None)
                    if hass is not None:
                        # v1.0.0a19: pass the live position + heading
                        # from new_state so the icon lands at the END
                        # of the just-appended path, not at whatever
                        # self.data happened to be when the scheduled
                        # task runs.
                        hass.async_create_task(
                            self._rerender_live_trail(
                                position=(
                                    float(new_state.position_x_m),
                                    float(new_state.position_y_m),
                                ),
                                heading=(
                                    float(new_state.position_heading_deg)
                                    if new_state.position_heading_deg is not None
                                    else None
                                ),
                            )
                        )

        # Sync MowerState's session view from LiveMapState. session_distance_m
        # is integrated from the track (sum of segment lengths, pen-up gaps
        # excluded) — see LiveMapState.total_distance_m(). session_track_segments
        # is a flat tuple of the captured (x_m, y_m) points (one segment) so the
        # session-points sensor has a count to report; the per-leg split now
        # lives in derive_render_legs() at render time.
        # Cleared to None when no session is active so the sensor goes
        # unavailable between mows rather than persisting the last value.
        new_state = dataclasses.replace(
            new_state,
            session_started_unix=self.live_map.started_unix,
            session_track_segments=(
                tuple((p.x_m, p.y_m) for p in self.live_map.track),
            ),
            session_distance_m=(
                self.live_map.total_distance_m() if self.live_map.is_active() else None
            ),
            target_area_m2=self._compute_target_area_m2(new_state),
        )

        self._prev_task_state = new_task_state

        # Dock arrival/departure rising/falling edges. Read current dock
        # state from the state machine (SM-14: mower_in_dock removed from
        # MowerState; Location.AT_DOCK is the canonical source). Explicit
        # `is True` / `is False` on _prev_in_dock so the boot-time None
        # doesn't fire a spurious arrived/departed event.
        # Defensive: test fixtures construct via __new__ without __init__,
        # so state_machine may be missing; treat as "not at dock" then.
        from ..mower.state_snapshot import Location as _Location
        _sm = getattr(self, "state_machine", None)
        _sm_at_dock: bool = (
            _sm is not None and _sm.snapshot().location == _Location.AT_DOCK
        )
        if self._prev_in_dock is False and _sm_at_dock:
            self._fire_lifecycle(
                EVENT_TYPE_DOCK_ARRIVED, {"at_unix": int(now_unix)}
            )
        elif self._prev_in_dock is True and not _sm_at_dock:
            self._fire_lifecycle(
                EVENT_TYPE_DOCK_DEPARTED, {"at_unix": int(now_unix)}
            )
        self._prev_in_dock = _sm_at_dock

        # F13 — s2p2 notification synthesis. Fire dreame_a2_mower_alert on
        # transitions to known notification codes. The first push on HA boot
        # is intentionally suppressed (_prev_error_code starts as None so
        # the FIRST observed value just primes the tracker without firing
        # — we don't want to re-emit a stale alert for whatever code was
        # active at restart).
        #
        # Critical: only update _prev_error_code when we observe a non-None
        # value. s2p2 occasionally goes through transient None states
        # (the property push doesn't always carry the slot). If we
        # overwrite prev to None during a transient, the next real
        # transition (e.g., None → 70) gets suppressed by the
        # `old_code is not None` boot-guard. This was the cause of the
        # alert event entity having ZERO entries despite 70 firing
        # multiple times in the probe log. Same bug pattern as the
        # mowing_paused fix in commit 87e2bbe.
        new_error_code = new_state.error_code
        old_error_code = self._prev_error_code
        if (
            new_error_code is not None
            and new_error_code != old_error_code
            and old_error_code is not None  # suppress first-push-after-boot
        ):
            # 2026-05-26: cloud-driven notification. The hardcoded
            # (event_type, text) tuple is gone — we kick off an async
            # resolver that fetches the authoritative text from
            # /dreame-messaging/user/device-messages/v2 after a short
            # delay (~10s, to let the cloud finish writing its push
            # record) and fires the event ONLY if the cloud actually
            # pushed for this transition. Unknown codes (not in
            # S2P2_EVENT_TYPES) still fire — with slug "unknown_s2p2"
            # — and a WARNING is logged so the maintainer can extend
            # the slug table.
            hass = getattr(self, "hass", None)
            if hass is not None:
                hass.async_create_task(
                    self._resolve_s2p2_notification(
                        siid=2, piid=2, value=int(new_error_code),
                        now_unix=now_unix,
                    )
                )
        if new_error_code is not None:
            self._prev_error_code = new_error_code

        # F6 review fix #1: record freshness AFTER all derivations so
        # session-derived fields (session_active, session_started_unix,
        # session_track_segments) are stamped with accurate timestamps.
        self.freshness.record(self.data, new_state, now_unix=now_unix)

        # F7.2.2: kick off LiDAR fetch when object_name flips to a new key.
        prev_lidar = getattr(self.data, "latest_lidar_object_name", None)
        if (
            new_state.latest_lidar_object_name is not None
            and new_state.latest_lidar_object_name != prev_lidar
        ):
            self.hass.async_create_task(
                self._handle_lidar_object_name(
                    new_state.latest_lidar_object_name, now_unix
                )
            )

        # Pending-finalize dock-return signal.
        # If _wait_for_dock_return is currently blocking, check whether
        # this state update represents the mower physically docking.
        # Signal fires ONLY when:
        #   - charging_status == ChargingStatus.CHARGING (value 1, docked+charging)
        # We deliberately do NOT fire on task_idle (task_state_code is None):
        # that condition becomes true the instant the session ends, before the
        # mower drives home — firing there would cut off dock-return capture.
        # The wait therefore completes only on physical dock (charging) or
        # timeout. The event is cleared to None by _wait_for_dock_return's
        # finally block so this guard is harmless outside of an active wait.
        done_event = getattr(self, "_pending_finalize_done", None)
        if done_event is not None and not done_event.is_set():
            is_charging = False
            cs = new_state.charging_status
            if cs is not None:
                # ChargingStatus is IntEnum; .value extracts the int.
                cs_val = cs.value if hasattr(cs, "value") else int(cs)
                is_charging = cs_val == 1  # ChargingStatus.CHARGING
            if is_charging:
                self._pending_finalize_done_reason = "charging"
                done_event.set()

        return new_state

    # -----------------------------------------------------------------------
    # F5.6.1 — event_occured handler + periodic retry
    # -----------------------------------------------------------------------

    async def _handle_event_occured(self, arguments: list[dict[str, Any]]) -> None:
        """Handle an event_occured (siid=4 eiid=1) message.

        Extracts the OSS object name from ``arguments[piid=9]`` and stores it
        as ``pending_session_object_name`` + ``pending_session_first_event_unix``
        on MowerState so the periodic retry loop can pick it up.

        Called on the event loop (via call_soon_threadsafe) — safe to call
        async_set_updated_data directly.
        """
        import time as _time
        object_name: str | None = None
        for arg in arguments:
            if int(arg.get("piid", -1)) == 9:
                object_name = str(arg.get("value", "")) or None
                break

        if not object_name:
            LOGGER.warning(
                "[F5.6.1] event_occured (siid=4 eiid=1): no piid=9 argument "
                "or empty value — arguments=%r",
                arguments,
            )
            return

        LOGGER.info(
            "[F5.6.1] event_occured: OSS object_name=%r — scheduling fetch",
            object_name,
        )
        now_unix = int(_time.time())
        new_state = dataclasses.replace(
            self.data,
            pending_session_object_name=object_name,
            pending_session_first_event_unix=now_unix,
            pending_session_last_attempt_unix=None,
            pending_session_attempt_count=0,
        )
        self.async_set_updated_data(new_state)

    # -----------------------------------------------------------------------
    # F7.2.2 — LiDAR scan fetch + archive
    # -----------------------------------------------------------------------

    def _capture_telemetry_sample(
        self, key: tuple[int, int], value: Any, now_unix: int
    ) -> None:
        """Append a raw telemetry value to the matching LiveMapState
        sample buffer. Runs on the event loop (hop done by caller).

        Only fires while a session is active. The raw int wire value
        is captured verbatim — interpretation (charging-status enum,
        s2p2 notification map) happens at archive-consumer time.
        """
        if not self.live_map.is_active():
            return
        try:
            v_int = int(value)
        except (TypeError, ValueError):
            return
        lm = self.live_map
        if key == (3, 1):
            buf = lm.battery_samples
        elif key == (3, 2):
            buf = lm.charging_status_samples
        elif key == (2, 1):
            lm.update_task_state(float(now_unix), v_int)
            self._live_map_dirty = True
            return
        elif key == (2, 2):
            buf = lm.error_samples
        else:
            return
        if lm.append_telemetry_sample(buf, v_int, now_unix):
            self._live_map_dirty = True

    def handle_property_push(self, siid: int, piid: int, value: Any) -> None:
        """Apply a property push and notify entities. Called from the
        MQTT message callback (which runs on paho's background thread).

        Per spec §3 async-first commitment: state updates must reach
        HA's coordinator on the event loop. We hop the thread boundary
        via call_soon_threadsafe; the actual async_set_updated_data
        call lands on the event loop's next iteration.
        """
        import time as _time
        now = int(_time.time())

        # Novelty checks BEFORE the early-return: unmapped slots produce
        # `new_state == self.data` (no field touched), so they must be
        # logged here or they'd be silently dropped. Blob-payload slots
        # (s1.1, s1.4, s2.51) are dispatched in apply_property_to_state
        # via dedicated handlers; treat them as known to avoid the
        # per-tick novelty noise their varying payloads would generate.
        key = (int(siid), int(piid))
        if key in _SETTINGS_TRIPWIRE_SLOTS:
            # Firmware-saved-settings tripwire (s6p2 etc.) — schedule a
            # debounced cloud refresh so app/BT-side edits surface in HA
            # within seconds instead of waiting for the next 2-min poll.
            # Continues into the normal mapping path below: tripwire
            # slots also carry decoded state (e.g. s6p2 frame elements).
            self.hass.loop.call_soon_threadsafe(
                lambda k=key: self._schedule_cloud_refresh(
                    reason=f"s{k[0]}p{k[1]}"
                ),
            )
        # Telemetry-stream capture (v1.0.12a2+). Accumulate the four
        # scalar streams that aren't otherwise persisted alongside the
        # session trail (battery_level, charging_status, mower-state,
        # error_code) so the finalized archive can reconstruct the
        # SoC + state curves without correlating against HA's entity
        # history. Capture must run BEFORE the early-return paths
        # below: s2p1 (state) is a state-machine no-op in
        # apply_property_to_state so it never reaches the _apply hop,
        # and same-value re-emits on s3p1/s3p2/s2p2 dedup against
        # self.data and likewise short-circuit. Hop to the loop because
        # LiveMapState lists must not be mutated from paho's bg thread.
        if key in {(3, 1), (3, 2), (2, 1), (2, 2)}:
            self.hass.loop.call_soon_threadsafe(
                lambda k=key, v=value, t=now: self._capture_telemetry_sample(k, v, t),
            )
        if key in _SUPPRESSED_SLOTS:
            # s1p50 is the firmware's "something changed" empty-ping. For
            # multi-map, every map-swap fires it (confirmed 2026-05-07).
            # Treat it as a MAPL-repoll trigger so active-map detection has
            # sub-second latency instead of waiting for the next 2-min
            # cloud refresh. Other s1p50 cases (zone-edits, maintenance saves)
            # benefit from the cheap re-poll too — MAPL is a ~100 ms RPC.
            if key == (1, 50):
                self.hass.loop.call_soon_threadsafe(
                    lambda: self.hass.async_create_task(self._refresh_mapl())
                )
            return  # echo of our own command; nothing to record
        if key in _BLOB_SLOTS:
            pass  # handled by dedicated blob applier; suppress novelty
        elif key in PROPERTY_MAPPING:
            if self.novel_registry.record_value(siid, piid, value, now):
                # First-time value for an already-mapped slot is informational
                # (e.g. s1p53 obstacle_flag toggling True for the first time
                # after install); the slot is recognised so there is nothing
                # for the user to action. Keep [NOVEL/property] at WARN since
                # that one signals a protocol gap.
                LOGGER.info(
                    "%s siid=%s piid=%s value=%r — first-time value for known slot",
                    LOG_NOVEL_VALUE, siid, piid, value,
                )
        elif key in _INVENTORY.apk_known_never_seen:
            # The slot is in the inventory as APK-KNOWN but seen_on_wire:false.
            # Now that we've observed it, prompt the contributor to upgrade the
            # inventory row to seen_on_wire:true. Logged at INFO since the slot
            # is "known" in the data sense — the contributor action is to
            # update the row, not to file a new protocol gap.
            if self.novel_registry.saw_property(siid, piid):
                LOGGER.info(
                    "[PROTOCOL_NOVEL/apk-confirmed] siid=%s piid=%s value=%r "
                    "— APK-known slot now observed on wire; consider upgrading "
                    "inventory row to seen_on_wire:true",
                    siid, piid, value,
                )
        else:
            if self.novel_registry.record_property(siid, piid, now):
                LOGGER.warning(
                    "%s siid=%s piid=%s value=%r — unmapped slot, please file a protocol gap",
                    LOG_NOVEL_PROPERTY, siid, piid, value,
                )

        # Catalog-miss check runs regardless of whether the slot is mapped or
        # apk-known: any property with a value_catalog in the inventory should
        # have its observed values cross-checked. Misses log at WARNING since
        # they likely indicate a protocol gap (firmware emitting a value the
        # catalog hasn't enumerated yet).
        catalog = _INVENTORY.value_catalogs.get(key)
        if catalog is not None and value not in catalog:
            if self.novel_registry.record_value(siid, piid, value, now):
                LOGGER.warning(
                    "[NOVEL/value/catalog-miss] siid=%s piid=%s value=%r "
                    "— not in catalog %r; please file a protocol gap",
                    siid, piid, value, sorted(catalog.keys()),
                )

        new_state = apply_property_to_state(self.data, siid, piid, value)
        if new_state == self.data:
            return

        # SM-mutator (R6): persist position across reboot. s1p4 is the only
        # slot that writes position_x_m/position_y_m on MowerState; route
        # those writes through the state machine so the StateSnapshot
        # cold-boot restore picks up the last-known pose.
        # Position-fix P3: project dock-frame (x_m, y_m) into compass-frame
        # (north_m, east_m) using the user-set station_bearing_deg option.
        # When the option is unset, _project_north_east returns (None, None)
        # and handle_position no-ops those fields, leaving the N/E sensors
        # Unknown.
        if (int(siid), int(piid)) == (1, 4):
            sm = getattr(self, "state_machine", None)
            if sm is not None and new_state.position_x_m is not None:
                x_m = new_state.position_x_m
                y_m = new_state.position_y_m
                north_m, east_m = _project_north_east(
                    x_m, y_m, self.station_bearing_deg,
                )
                try:
                    sm.handle_position(
                        x_m=x_m,
                        y_m=y_m,
                        north_m=north_m,
                        east_m=east_m,
                        now_unix=now,
                    )
                except Exception:
                    LOGGER.exception("state_machine.handle_position failed")

        # Persist mowing_phase / task_state_code / slam_task_label in the
        # snapshot so they survive HA restart (per user feedback: showing
        # last-known is more useful than Unknown). Read whichever fields
        # this slot's apply_property_to_state may have updated.
        if (int(siid), int(piid)) in {(1, 4), (2, 56), (2, 65)}:
            sm = getattr(self, "state_machine", None)
            if sm is not None:
                try:
                    sm.handle_misc_persisted(
                        mowing_phase=new_state.mowing_phase,
                        task_state_code=new_state.task_state_code,
                        slam_task_label=new_state.slam_task_label,
                        now_unix=now,
                    )
                except Exception:
                    LOGGER.exception("state_machine.handle_misc_persisted failed")

        # Per-map shadow update: s6.2 carries the active map's full PRE
        # profile at the moment of save in the Dreame app. Tag with
        # current active map_id (from MAPL poll cache). See
        # `docs/research/g2408-protocol.md` § s6.2 for the per-map model.
        if (int(siid), int(piid)) == (6, 2):
            sm = getattr(self, "state_machine", None)
            active_map = getattr(self, "_active_map_id", None)
            if sm is not None and active_map is not None:
                try:
                    sm.handle_pre_shadow_update(
                        map_id=int(active_map),
                        mowing_height_mm=new_state.pre_mowing_height_mm,
                        mowing_efficiency=new_state.pre_mowing_efficiency,
                        edgemaster=new_state.pre_edgemaster,
                        now_unix=now,
                    )
                except Exception:
                    LOGGER.exception("state_machine.handle_pre_shadow_update failed")

        def _apply() -> None:
            # _on_state_update mutates live_map (legs, started_unix, etc.) and
            # updates _prev_task_state / _live_map_dirty.  It must run on the
            # event loop so those shared objects are never mutated from paho's
            # background thread while the loop is iterating them.
            hopped = self._on_state_update(new_state, now)
            # Surface the persistent_notification banner that mirrors the
            # Dreame app's modal popup. Fires on emergency_stop transition
            # (byte[3] bit 7), the load-bearing PIN-required latch.
            self._handle_emergency_stop_transition(
                self.data.emergency_stop, hopped.emergency_stop,
            )
            self.async_set_updated_data(hopped)

        self.hass.loop.call_soon_threadsafe(_apply)

    # -----------------------------------------------------------------------
    # Settings write surface (F4.5.1)
    # -----------------------------------------------------------------------

    #: CFG keys whose wire value is passed directly to set_cfg().
    #: All multi-field CFG keys (DND, LIT, BAT, WRP, LOW, ATA, REC) are
    #: also in this set — the entity layer builds the full array/dict value
    #: and passes it here; the coordinator relays verbatim.
    _CFG_SINGLE_KEYS: frozenset[str] = frozenset(
        {
            "CLS", "VOL", "LANG", "DND", "WRP", "LOW", "BAT", "LIT", "ATA", "REC",
            # AMBIGUOUS_TOGGLE single-int keys (a62 — toggle-confirmed 2026-04-30):
            "FDP", "STUN", "AOP", "PROT",
            # AMBIGUOUS_4LIST 4-bool keys (a62 — slot-confirmed 2026-04-30):
            "MSG_ALERT", "VOICE",
        }
    )

