"""cloud_state mixin — extracted from coordinator.py 2026-05-15.

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


class _CloudStateMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    async def _refresh_cloud_state(self) -> None:
        """Single-shot fetch of the full cloud state.

        Called every 2 min via the periodic timer. Replaces the
        previous _refresh_cfg + _refresh_map + _refresh_mihis +
        _refresh_locn + _refresh_dock + _refresh_net + _refresh_dev
        + _poll_slow_properties series.

        On success: self.cloud_state is replaced atomically. Entities
        and consumers re-render via async_update_listeners.
        On failure: self.cloud_state is left unchanged.
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
        # Mirror legacy attributes that downstream code reads. These
        # become inert once all consumers move to cloud_state directly,
        # but the migration is staged across Task 7+ steps.
        self._cached_maps_by_id = new_state.maps_by_id
        # Re-render PNGs for any map whose md5 changed.
        await self._render_maps_from_cloud_state()
        # Sync HA per-map sub-devices to the freshly-set cloud_state. This
        # is the sole startup/periodic sync now that _refresh_map is gone
        # (the MQTT MAPL path is push-only).
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

        Mirrors what _refresh_cfg / _refresh_mihis used to do, now
        sourcing from cloud_state. SETTINGS-driven MowerState fields
        added in Task 8.
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
        # CFG keys → MowerState (same fields as _refresh_cfg used to set;
        # the existing _refresh_cfg stays for now to do the heavy lifting,
        # see Task 7 step 6).
        if not updates:
            return
        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _load_persisted_maps(self) -> None:
        """Restore `_cached_maps_by_id` from the on-disk cache.

        Reads the raw fetch_map dict last persisted by `_save_persisted_maps`,
        parses it via `parse_cloud_maps`, and populates the cache + sub-
        device registry so map-metadata sensors light up immediately on
        reload. The subsequent `_refresh_map` will overwrite with fresh
        data; this just removes the empty-cache gap.

        Silently no-ops when no cache exists or the stored payload is
        unusable. Per-map PNGs are not pre-rendered (the cloud-driven
        refresh handles those).
        """
        if self._maps_cache_store is None:
            return
        raw = await self._maps_cache_store.async_load()
        if not isinstance(raw, dict):
            return
        # Store-loaded dicts have str keys; re-cast map_id back to int.
        try:
            cloud_response = {int(k): v for k, v in raw.items()}
        except (TypeError, ValueError):
            LOGGER.warning("[map] persisted map cache has unparsable keys; ignoring")
            return
        if not cloud_response:
            return
        from ..map_decoder import parse_cloud_maps
        parsed_by_id = parse_cloud_maps(cloud_response)
        if not parsed_by_id:
            LOGGER.debug("[map] _load_persisted_maps: parse returned empty")
            return
        self._cached_maps_by_id = parsed_by_id
        self._sync_map_subdevices()
        LOGGER.info(
            "[map] _load_persisted_maps: restored %d map(s) from cache",
            len(parsed_by_id),
        )

    async def _save_persisted_maps(self, cloud_response: dict[int, Any]) -> None:
        """Write the raw fetch_map dict to disk so next reload is instant."""
        if self._maps_cache_store is None:
            return
        # Store serialises via JSON; int keys become str on roundtrip.
        await self._maps_cache_store.async_save(cloud_response)


