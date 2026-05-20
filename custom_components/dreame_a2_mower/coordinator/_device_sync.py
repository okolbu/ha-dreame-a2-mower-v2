"""device_sync mixin — extracted from coordinator.py 2026-05-15.

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
from ..mower.state import ChargingStatus, MowerState
from ._property_apply import (
    _BLOB_SLOTS,
    _INVENTORY,
    _SESSION_SUMMARY_CHECK,
    _SETTINGS_TRIPWIRE_SLOTS,
    _SUPPRESSED_SLOTS,
    S2P2_NOTIFICATION_MAP,
    S2P2_NOVEL_EVENT_TYPE,
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


class _DeviceSyncMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    def _compute_target_area_m2(self, state: MowerState) -> float | None:
        """Effective area for the current mowing target.

        Behaves like the Dreame app's "this is what will be mowed"
        readout. Source-of-truth order:

        1. Live s1.4 telemetry's per-task area
           (``task_total_area_m2``) when a session is active. This
           is the firmware's own "target" figure; it covers any
           combination of selected zones/spots without the cloud map
           round-trip.
        2. Cloud-map area_m2 of the selected zone(s) or spot(s) when
           the user has picked a target. Used pre-session so the
           dashboard shows the planned target before pressing Start.
        3. Full lawn area otherwise (the sensor's original meaning).
        """
        from ..mower.state import ActionMode

        # Priority 1: live telemetry while mowing.
        # Use live_map.is_active() — session_active was removed from MowerState (SM-14).
        live_task_area = state.task_total_area_m2
        if (
            self.live_map.is_active()
            and live_task_area is not None
            and live_task_area > 0
        ):
            return float(live_task_area)

        _maps = self.cloud_state.maps_by_id if self.cloud_state is not None else {}
        map_data = _maps.get(self._active_map_id)
        mode = state.action_mode
        if map_data is not None:
            if mode == ActionMode.ZONE and state.active_selection_zones:
                wanted = set(state.active_selection_zones)
                total = 0.0
                for z in getattr(map_data, "mowing_zones", ()):
                    if z.zone_id in wanted:
                        total += float(getattr(z, "area_m2", 0.0) or 0.0)
                if total > 0:
                    return total
            if mode == ActionMode.SPOT and state.active_selection_spots:
                wanted = set(state.active_selection_spots)
                total = 0.0
                matched: list[tuple[int, str, float]] = []
                for s in getattr(map_data, "spot_zones", ()):
                    if s.spot_id in wanted:
                        matched.append(
                            (s.spot_id, s.name, float(getattr(s, "area_m2", 0.0) or 0.0))
                        )
                        total += matched[-1][2]
                if total > 0:
                    return total
                # v1.0.0a51: log once when SPOT mode would target a real
                # selection but we can't compute an area — distinguishes
                # "spot not found in cached map" from "spot found but
                # cloud sent area=0".
                if not getattr(self, "_target_area_diagnostics_logged", False):
                    available = [
                        (s.spot_id, s.name, float(getattr(s, "area_m2", 0.0) or 0.0))
                        for s in getattr(map_data, "spot_zones", ())
                    ]
                    LOGGER.warning(
                        "[F5] target_area: SPOT mode wanted=%s matched=%s "
                        "available=%s — falling back to total_lawn_area_m2",
                        list(wanted), matched, available,
                    )
                    self._target_area_diagnostics_logged = True
        # All-areas, edge mode, or no selection / no area data yet:
        # fall back to the full lawn area (the sensor's original
        # meaning).
        return state.total_lawn_area_m2

    def _handle_emergency_stop_transition(
        self, prev: bool | None, new: bool | None,
    ) -> None:
        """Surface a persistent_notification mirroring the Dreame app's
        modal popup when the mower goes into the PIN-required lockout
        state, and dismiss it when the user enters the PIN to clear.

        byte[3] bit 7 (state.emergency_stop) is the load-bearing latch:
        sets on safety event (lid open OR lift), clears ONLY on PIN
        entry. So this notification's lifecycle exactly matches the
        app's "Emergency stop activated. Enter PIN code on the robot
        to unlock it." popup.
        """
        # Treat None (state not yet known) the same as False for trigger
        # purposes — handles the first heartbeat after HA restart where
        # the prior state was None and the mower is already in lockout.
        prev_active = prev is True
        new_active = new is True
        if prev_active and not new_active:
            try:
                from homeassistant.components import persistent_notification as _pn
                _pn.async_dismiss(
                    self.hass,
                    notification_id=f"{DOMAIN}_emergency_stop_{self.entry.entry_id}",
                )
                LOGGER.info("emergency_stop cleared — persistent_notification dismissed")
            except Exception as ex:
                LOGGER.warning("emergency_stop dismiss failed: %s", ex)
            return
        if prev_active or not new_active:
            return
        # Transition (None|False) → True: post the modal-equivalent banner.
        try:
            from homeassistant.components import persistent_notification as _pn
            _pn.async_create(
                self.hass,
                message=(
                    "The mower has triggered its safety lockout. **Enter "
                    "the PIN code on the robot to unlock it.** The mower "
                    "will not mow until the PIN is entered.\n\n"
                    "This notification will dismiss automatically once "
                    "the PIN is accepted."
                ),
                title="Dreame A2 Mower — Emergency stop activated",
                notification_id=f"{DOMAIN}_emergency_stop_{self.entry.entry_id}",
            )
            LOGGER.info("emergency_stop activated — persistent_notification posted")
        except Exception as ex:
            LOGGER.warning("emergency_stop notification create failed: %s", ex)

    def _update_device_registry_serial(self, serial: str) -> None:
        """Reflect the real hardware serial onto the device record."""
        try:
            from homeassistant.helpers import device_registry as dr
        except ImportError:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.entry.entry_id)})
        if device is None:
            LOGGER.debug(
                "hardware_serial fetched but device record not yet registered "
                "(serial=%r) — will pick up on next entity registration",
                serial,
            )
            return
        if device.serial_number == serial:
            return
        registry.async_update_device(device.id, serial_number=serial)
        LOGGER.info("device serial_number updated to %s", serial)

    def _get_device_registry(self) -> object | None:
        """Return the HA device registry, or None if unavailable in this test env."""
        try:
            from homeassistant.helpers import device_registry as dr
        except ImportError:
            return None
        return dr.async_get(self.hass)

    def _sync_map_subdevices(self) -> None:
        """Add HA devices for new map_ids; remove devices for dropped ones.

        Called whenever `cloud_state.maps_by_id` may have changed (after
        `_apply_mapl` and after `_refresh_cloud_state`). No-ops if `self.hass` or
        `self.entry` is missing or None (test stubs may not have them set).
        """
        if not hasattr(self, "hass") or self.hass is None:
            return
        if not hasattr(self, "entry") or self.entry is None:
            return
        if self.cloud_state is None:
            return
        from .._devices import _stable_id, map_device_info

        registry = self._get_device_registry()
        if registry is None:
            return
        stable = _stable_id(self)
        wanted_ids = set(self.cloud_state.maps_by_id.keys())

        for map_id, map_data in self.cloud_state.maps_by_id.items():
            info = map_device_info(self, map_id, getattr(map_data, "name", None))
            registry.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                **info,
            )

        # An empty maps_by_id means "no authoritative map list right now"
        # (transient empty cloud batch), NOT "delete every map". Pruning on
        # empty would wipe all per-map sub-devices; skip it.
        if not wanted_ids:
            return

        # Remove orphan map sub-devices belonging to this entry.
        # HA device identifiers are typed as `set[tuple[str, str]]` but in
        # the wild some integrations store longer tuples. Iterate defensively.
        prefix = f"{stable}_map_"
        for dev in list(registry.devices.values()):
            for ident_tuple in dev.identifiers:
                if len(ident_tuple) < 2 or ident_tuple[0] != DOMAIN:
                    continue
                ident = ident_tuple[1]
                if not isinstance(ident, str) or not ident.startswith(prefix):
                    continue
                try:
                    map_id = int(ident.removeprefix(prefix))
                except ValueError:
                    continue
                if map_id not in wanted_ids:
                    registry.async_remove_device(dev.id)
                break

    def _schedule_cloud_refresh(
        self, *, delay_sec: float = 5.0, reason: str = "tripwire",
    ) -> None:
        """Debounced cloud-state refresh — coalesces bursts of MQTT
        settings tripwires (s6p2 etc.) into a single fetch.

        Called from the MQTT event-loop hop on every tripwire push.
        Each call cancels any pending fire and arms a new timer so a
        burst of settings saves results in exactly one refresh once
        the burst settles. Default delay 5s — short enough that HA
        reflects an app-side edit within a few seconds, long enough
        to coalesce the 1-3 tripwires the firmware tends to emit per
        save (FRAME_INFO + an echo or two).
        """
        loop = self.hass.loop
        if self._cloud_refresh_debounce_handle is not None:
            self._cloud_refresh_debounce_handle.cancel()

        def _fire() -> None:
            self._cloud_refresh_debounce_handle = None
            LOGGER.info(
                "[cloud] settings tripwire (%s) → refreshing cloud state",
                reason,
            )
            self.hass.async_create_task(self._refresh_cloud_state())

        self._cloud_refresh_debounce_handle = loop.call_later(delay_sec, _fire)

    def register_event_entities(self, *, lifecycle: Any, alert: Any) -> None:
        """Called from event.py's async_setup_entry to wire the event
        entities the coordinator's dispatcher fires through.

        Stored as plain attributes (no weakref needed — entities live
        for the integration's lifetime). The lifecycle and alert
        parameters are the EventEntity instances created by
        event.py's setup call.
        """
        self._lifecycle_event = lifecycle
        self._alert_event = alert

    def _fire_lifecycle(
        self, event_type: str, event_data: dict[str, Any] | None = None
    ) -> None:
        """Race-safe dispatcher to the lifecycle event entity.

        Drops the call with a DEBUG log if the entity isn't yet wired
        (transient on startup before event.py's async_setup_entry has
        run). Delegates payload-cleaning to the entity's `trigger`
        wrapper.
        """
        ent = self._lifecycle_event
        if ent is None:
            LOGGER.debug(
                "[event] _fire_lifecycle(%r) dropped — entity not yet registered",
                event_type,
            )
            return
        ent.trigger(event_type, event_data)

    def _fire_mowing_ended(
        self,
        now_unix: int,
        area_mowed_m2: float | None,
        duration_min: int | None,
        completed: bool,
    ) -> None:
        """Fire the mowing_ended lifecycle event AND notify state machine.

        Called from both _do_oss_fetch (FINALIZE_COMPLETE, summary-driven)
        and _run_finalize_incomplete (FINALIZE_INCOMPLETE, best-effort).
        Delegates payload-shape consistency to one place.

        State-machine sync: the finalize gate can fire on a cloud-
        detected task_state transition (prev ∈ {0,4} → new ∈ {2,None})
        without a matching MQTT push. Without this hook the state
        machine stays IN_SESSION + MOWING indefinitely while the
        lifecycle event correctly reports the session ended.
        """
        self._fire_lifecycle(
            EVENT_TYPE_MOWING_ENDED,
            {
                "at_unix": int(now_unix),
                "area_mowed_m2": area_mowed_m2,
                "duration_min": duration_min,
                "completed": bool(completed),
            },
        )
        sm = getattr(self, "state_machine", None)
        if sm is not None:
            try:
                sm.end_session(now_unix=int(now_unix))
            except Exception:
                LOGGER.exception("state_machine.end_session failed")

    def _fire_alert(self, event_type: str, text: str, code: int, now_unix: int) -> None:
        """Race-safe dispatcher to the alert event entity.

        Called from _on_state_update when s2p2 (error_code) transitions to a
        known notification code. Drops the call with a DEBUG log if the alert
        entity is not yet wired (transient on startup before event.py's
        async_setup_entry has run). Also stashes the notification for
        sensor.last_notification.

        NOTE: _fire_alert is called from _on_state_update which is called from
        _apply (already on the event loop via call_soon_threadsafe). The
        sensor.last_notification entity will refresh when _apply subsequently
        calls async_set_updated_data — no extra call needed here.
        """
        self._last_notification = {
            "event_type": event_type,
            "text": text,
            "code": code,
            "fired_at": now_unix,
        }
        LOGGER.warning(
            "[F13] s2p2 alert: code=%d event_type=%r text=%r",
            code, event_type, text,
        )
        ent = self._alert_event
        if ent is None:
            LOGGER.debug(
                "[event] _fire_alert(%r) dropped — alert entity not yet registered",
                event_type,
            )
            return
        ent.trigger(event_type, {"text": text, "code": code, "source": "s2p2"})

    # -----------------------------------------------------------------------
    # F5.7.1 — In-progress restore on HA boot + 30s debounced persist
    # -----------------------------------------------------------------------

