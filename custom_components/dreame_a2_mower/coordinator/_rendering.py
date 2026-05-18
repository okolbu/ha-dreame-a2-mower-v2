"""rendering mixin — extracted from coordinator.py 2026-05-15.

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
from ..observability import FreshnessTracker, NovelObservationRegistry
from ..observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from ..protocol import config_s2p51 as _s2p51
from ..protocol import heartbeat as _heartbeat
from ..protocol import session_summary as _session_summary
from ..protocol import telemetry as _telemetry
from ..protocol import wheel_bind as _wheel_bind

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


class _RenderingMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    def _current_mower_position(self) -> tuple[float, float] | None:
        """Return the current mower (x_m, y_m) cloud-frame position, or
        None when either coordinate is unset. Used by the live-map
        renders to draw the position marker.

        P4: prefer the state-machine snapshot (persisted across reboot,
        seeded from the last session archive, and updated on every
        s1p4) over live MowerState. MowerState fields go None when
        telemetry stops, which makes the icon disappear from the map
        between sessions. The snapshot retains the last known fix so
        the icon stays put — matching what the Dreame app shows.
        """
        snap = self.state_machine.snapshot()
        sx = snap.position_x_m
        sy = snap.position_y_m
        if sx is not None and sy is not None:
            return (float(sx), float(sy))
        # Fallback to live MowerState in the rare case the snapshot is
        # somehow empty but MowerState has a fix (e.g. older persisted
        # store predating snapshot.position persistence).
        x = self.data.position_x_m
        y = self.data.position_y_m
        if x is None or y is None:
            return None
        return (float(x), float(y))

    def _current_mower_heading(self) -> float | None:
        """Return the mower's current heading in degrees, or None."""
        h = self.data.position_heading_deg
        return float(h) if h is not None else None

    async def _rerender_live_trail(
        self,
        position: tuple[float, float] | None = None,
        heading: float | None = None,
    ) -> None:
        """Re-render the cached map with the current live trail.

        v1.0.0a19: position + heading are passed explicitly by the
        _on_state_update hook so the icon reflects the SAME push that
        just appended to live_map. Without this, reading self.data
        inside the scheduled task could see either the old or new
        state depending on whether async_set_updated_data has run yet,
        and the icon would lag behind the trail.
        """
        map_data = self._cached_maps_by_id.get(self._active_map_id)
        if map_data is None or not self.live_map.is_active():
            return
        from ..map_render import render_with_trail
        legs = list(self.live_map.legs)
        if position is None:
            position = self._current_mower_position()
        if heading is None:
            heading = self._current_mower_heading()
        png = await self.hass.async_add_executor_job(
            render_with_trail, map_data, legs, None, position, heading,
        )
        LOGGER.debug(
            "[MAP] live trail re-render: legs=%d points=%d bytes=%d pos=%s hdg=%s",
            len(legs), self.live_map.total_points(), len(png) if png else 0,
            position, heading,
        )
        await self._render_main_view()

    async def _render_main_view(self) -> None:
        """Render the active map's Main view (base + live trail + mower icon
        + last-session obstacles overlay).

        Writes the result to self._main_view_png. No-ops gracefully when:
        - _active_map_id is None (active map not yet known)
        - _cached_maps_by_id has no entry for the active map
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self._cached_maps_by_id.get(active_id)
        if map_data is None:
            return
        from functools import partial

        from ..map_render import render_main_view

        legs = list(self.live_map.legs) if self.live_map.is_active() else None
        # P4: prefer snapshot (persisted across reboot + seeded from the
        # last session archive at cold-start) over live MowerState, so
        # the mower icon shows on the map even when no s1p4 telemetry
        # is currently flowing (e.g. mower parked at dock between
        # sessions). MowerState fields go None when telemetry stops;
        # the snapshot retains the last known fix.
        mower_pos = self._current_mower_position()
        heading = self._current_mower_heading()
        # Overlay obstacles captured during the most recent session for
        # this map. Mirrors the Dreame app's "show last-mow obstacles"
        # behavior so users can spot which obstacles to clear before
        # the next mow. Loaded lazily and cached per-map (invalidated
        # on session finalize).
        obstacle_polygons_m = await self._load_last_session_obstacles(active_id)
        # T17: idle pre-start preview — pass current MowerState, active map id,
        # and the state-machine mow_session so render_main_view can dispatch
        # to the stripe/light-green preview when the mower is not in session.
        mow_session = self.state_machine.snapshot().mow_session
        png = await self.hass.async_add_executor_job(
            partial(
                render_main_view,
                map_data,
                legs=legs,
                mower_position_m=mower_pos,
                mower_heading_deg=heading,
                obstacle_polygons_m=obstacle_polygons_m,
                state=self.data,
                map_id=active_id,
                mow_session=mow_session,
                trail_width_px=self.data.trail_render_width,
            )
        )
        if png:
            self._main_view_png = png
        # Also keep the work-log empty-state PNG fresh. Md5-deduped, so
        # the no-op fast-path runs after the first render per map version.
        await self._render_active_map_base()

    async def _load_last_session_obstacles(
        self, map_id: int
    ) -> list[list[tuple[float, float]]] | None:
        """Return the obstacle polygons from the most-recent archived
        session for ``map_id``, or ``None`` if there are none / can't load.

        Cached in ``_last_session_obstacles_by_map`` so the disk read
        only happens once per map (or after a session-finalize
        invalidation). Triangles or larger only — degenerate polygons
        with < 3 points are filtered out (mirrors the work-log replay).
        """
        cached = self._last_session_obstacles_by_map.get(map_id)
        if cached is not None:
            return cached or None

        archive = getattr(self, "session_archive", None)
        if archive is None:
            return None
        # _index is preloaded at boot — but only AFTER ``load_index()`` has
        # run (coordinator setup awaits it). Calls before that finishes
        # (e.g., the MAPL handler kicked off from the first CFG refresh)
        # see an empty ``_index`` and must NOT poison the cache with an
        # empty result. v1.0.11a1 introduced an early _render_main_view
        # task on active-map change that exposed this race; gate the
        # empty-cache write on the archive being fully loaded.
        if not getattr(archive, "_index_loaded", False):
            return None
        index = getattr(archive, "_index", None) or []
        candidates = [s for s in index if getattr(s, "map_id", -1) == map_id]
        if not candidates:
            # Cache the empty result so we don't re-scan on every tick.
            self._last_session_obstacles_by_map[map_id] = []
            return None
        entry = max(candidates, key=lambda s: s.end_ts)

        raw_dict = await self.hass.async_add_executor_job(archive.load, entry)
        if raw_dict is None:
            self._last_session_obstacles_by_map[map_id] = []
            return None
        from ..protocol import session_summary as _session_summary
        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary:
            self._last_session_obstacles_by_map[map_id] = []
            return None
        polygons: list[list[tuple[float, float]]] = [
            list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3
        ]
        self._last_session_obstacles_by_map[map_id] = polygons
        return polygons or None

    async def _render_active_map_base(self) -> None:
        """Render the active map's clean base (no trail, no mower icon, no M_PATH).

        Writes the result to self._active_map_base_png. Used as the Work
        Log camera's empty-state image (when no session is picked) — it
        shows "this is the map your work logs would render on" without
        confusing the user with cumulative mow history.

        Md5-deduped: re-renders only when the active map's MapData.md5
        changes (or when the cache slot is empty). Safe to call from
        every _render_main_view trigger because the actual PIL render
        runs at most once per map version.
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self._cached_maps_by_id.get(active_id)
        if map_data is None:
            return
        current_md5 = getattr(map_data, "md5", None)
        if (
            self._active_map_base_png is not None
            and self._active_map_base_md5 == current_md5
        ):
            return  # already have a fresh render for this md5
        from ..map_render import render_base_map
        png = await self.hass.async_add_executor_job(
            render_base_map, map_data,
        )
        if png:
            self._active_map_base_png = png
            self._active_map_base_md5 = current_md5

