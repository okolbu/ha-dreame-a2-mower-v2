"""cloud_state mixin — extracted from coordinator.py 2026-05-15.

See spec docs/superpowers/specs/2026-05-15-coordinator-decomposition-design.md.
"""
from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
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
    cfg_to_state_updates,
)

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


class _CloudStateMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    async def _refresh_cloud_state(self) -> None:
        """Single-shot fetch of the full cloud state.

        Called every 2 min via the periodic timer. Map data, CFG, MIHIS and
        MAPL active-map detection are all handled here:
        `_apply_mapl(new_state.mapl)` sets the active map, then
        `_apply_cloud_state_to_mower_state` ports MIHIS, per-map SETTINGS and
        CFG (via `cfg_to_state_updates`) onto MowerState.

        Timers that intentionally remain separate: `_refresh_locn` /
        `_refresh_dock` (60 s fast cadence; dock also feeds the state machine),
        `_refresh_net` (1 h), `_refresh_dev` (6 h). LOCN/DOCK are NOT fetched
        here — those timers own them. (`_poll_slow_properties` was removed
        2026-05-26; see _refreshers.py.)

        On success: self.cloud_state is replaced atomically. Entities and
        consumers re-render via async_update_listeners. On failure:
        self.cloud_state is left unchanged.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        try:
            new_state = await self.hass.async_add_executor_job(
                self._cloud.fetch_full_cloud_state
            )
        except Exception as ex:
            LOGGER.warning("[cloud] _refresh_cloud_state raised: %s", ex)
            return
        if new_state is None:
            LOGGER.debug("[cloud] _refresh_cloud_state: fetch returned None")
            return
        self.cloud_state = new_state
        # Active-map detection from the unified fetch (replaces the former
        # _refresh_cfg trailing MAPL poll). Ordered before the MowerState
        # apply so SETTINGS/CFG fields key off the correct active map on
        # cold start.
        self._apply_mapl(new_state.mapl)
        # Re-render PNGs for any map whose md5 changed.
        await self._render_maps_from_cloud_state()
        # Sync HA per-map sub-devices to the freshly-set cloud_state. This
        # is the sole startup/periodic sync; the MQTT MAPL path is push-only.
        self._sync_map_subdevices()
        # Update derived MowerState fields from CFG / SETTINGS / MIHIS.
        self._apply_cloud_state_to_mower_state()
        # Notify entity listeners of the new data.
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    async def _render_maps_from_cloud_state(self) -> None:
        """Render CLEAN base PNGs for each map in cloud_state.maps_by_id.

        `_static_map_pngs_by_id` is the per-map base cache used by
        DreameA2PerMapCamera (Map Selector + Settings & Zones tabs).
        These are picker / overview surfaces — they should show the
        boundary + zones + dock + exclusion/ignore/maintenance
        overlays only. NO historical M_PATH fill, NO live trails.

        The active-map view (Mower tab) gets its own render with
        trails + M_PATH via `_render_main_view()` → `_main_view_png`,
        used exclusively by DreameA2MapCamera.
        """
        if self.cloud_state is None:
            return
        from ..map_render import render_base_map
        for map_id, map_data in self.cloud_state.maps_by_id.items():
            prev_md5 = self._last_map_md5_by_id.get(map_id)
            if prev_md5 == map_data.md5 and map_id in self._static_map_pngs_by_id:
                continue
            png = await self.hass.async_add_executor_job(
                render_base_map, map_data,
            )
            if png:
                self._static_map_pngs_by_id[map_id] = png
                self._last_map_md5_by_id[map_id] = map_data.md5
        # Also populate _main_view_png so DreameA2MapCamera reads a fresh
        # active-map render after every cloud_state refresh.
        await self._render_main_view()
        # And populate _active_map_base_png — the Work Log camera's
        # empty-state image (clean base, no trail, no M_PATH).
        await self._render_active_map_base()

    def _apply_cloud_state_to_mower_state(self) -> None:
        """Push CFG / MIHIS / SETTINGS-derived fields onto MowerState.

        Unified CFG (via cfg_to_state_updates) + MIHIS + SETTINGS port, sourced
        from cloud_state.
        """
        if self.cloud_state is None:
            return
        cs = self.cloud_state
        updates: dict[str, Any] = {}
        # MIHIS lifetime totals
        mihis = cs.mihis or {}
        if "area" in mihis:
            updates["total_mowed_area_m2"] = float(mihis["area"])
        if "time" in mihis:
            updates["total_mowing_time_min"] = int(mihis["time"])
        if "count" in mihis:
            updates["mowing_count"] = int(mihis["count"])
        # SETTINGS-driven per-active-map fields.
        active_id = self._active_map_id
        if active_id is not None:
            sm = cs.settings.by_map_id_canonical.get(active_id) or {}
            for src, dst in (
                ("mowingHeight", "settings_mowing_height"),
                ("mowingDirection", "settings_mowing_direction"),
                ("mowingDirectionMode", "settings_mowing_direction_mode"),
                ("cutterPosition", "settings_cutter_position"),
                ("cutterPositionHeight", "settings_cutter_position_height"),
                ("edgeMowingNum", "settings_edge_mowing_num"),
                ("edgeMowingWalkMode", "settings_edge_mowing_walk_mode"),
                ("obstacleAvoidanceHeight", "settings_obstacle_avoidance_height"),
                ("obstacleAvoidanceDistance", "settings_obstacle_avoidance_distance"),
                ("obstacleAvoidanceSensitivity", "settings_obstacle_avoidance_sensitivity"),
                ("obstacleAvoidanceAi", "settings_obstacle_avoidance_ai"),
            ):
                if src in sm:
                    try:
                        updates[dst] = int(sm[src])
                    except (TypeError, ValueError):
                        pass
            for src, dst in (
                ("edgeMowingAuto", "settings_edge_mowing_auto"),
                ("edgeMowingSafe", "settings_edge_mowing_safe"),
                ("edgeMowingObstacleAvoidance", "settings_edge_mowing_obstacle_avoidance"),
                ("obstacleAvoidanceEnabled", "settings_obstacle_avoidance_enabled"),
            ):
                if src in sm:
                    updates[dst] = bool(sm[src])
        # CFG keys → MowerState (folded from the former _refresh_cfg; uses the
        # safe updates-dict pattern so an absent CFG key never nulls a field).
        updates.update(cfg_to_state_updates(cs.cfg))
        if not updates:
            return
        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)



