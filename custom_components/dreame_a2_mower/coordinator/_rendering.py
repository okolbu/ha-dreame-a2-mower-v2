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
)

if TYPE_CHECKING:
    pass  # cross-mixin type imports added as needed


# ---------------------------------------------------------------------------
# Module-level constants for between-session re-render throttle
# ---------------------------------------------------------------------------

#: Minimum seconds between between-session icon re-renders.  The mower pushes
#: s1p4 every ~5 s; a 5-second floor means at most one re-render per push
#: cycle without flooding the PIL thread.  One render per ~5 s over a typical
#: 1-2 minute return-to-dock drive ≈ 12-24 renders total — acceptable.
_BETWEEN_SESSION_RENDER_MIN_INTERVAL_S: float = 5.0

#: Minimum position delta (metres) to trigger a between-session re-render.
#: Keeps the docked/parked mower (noisy GPS jitter ≪ this) from triggering
#: renders; a moving mower advances several tens of cm per push.
_BETWEEN_SESSION_MOVE_THRESHOLD_M: float = 0.3


async def _maybe_rerender_between_session_icon(coord: Any, *, now_unix: float) -> None:
    """Re-render the main view if the mower has moved significantly between sessions.

    Called from `_on_state_update` every time an s1p4 telemetry push arrives
    while `live_map.is_active()` is False.  Prevents the mower icon from
    freezing at the session-end position during the return-to-dock drive (or
    any other between-session movement).

    Guards:
    - live_map must be INACTIVE (active-session rendering is handled by the
      existing trail re-render path).
    - Snapshot must have a valid position (x_m, y_m).
    - Position must have moved more than ``_BETWEEN_SESSION_MOVE_THRESHOLD_M``
      since the last render to avoid spurious re-renders on GPS jitter.
    - At most one render per ``_BETWEEN_SESSION_RENDER_MIN_INTERVAL_S`` seconds
      (reuses ``coord._last_live_render_unix`` — the same throttle clock used
      by the live-trail path).
    """
    if coord.live_map.is_active():
        return  # active session handled by trail re-render path

    snap = coord.state_machine.snapshot()
    cur_x = snap.position_x_m
    cur_y = snap.position_y_m
    if cur_x is None or cur_y is None:
        return  # no position fix — nothing to render

    # Throttle: at most one render per _BETWEEN_SESSION_RENDER_MIN_INTERVAL_S.
    elapsed = now_unix - coord._last_live_render_unix
    if elapsed < _BETWEEN_SESSION_RENDER_MIN_INTERVAL_S:
        return

    # Position-delta gate: only render when the mower has actually moved.
    prev_x = coord._last_between_session_render_x
    prev_y = coord._last_between_session_render_y
    if prev_x is not None and prev_y is not None:
        delta = math.hypot(cur_x - prev_x, cur_y - prev_y)
        if delta < _BETWEEN_SESSION_MOVE_THRESHOLD_M:
            return  # stationary or jitter — skip

    # Update throttle clock and last-rendered position BEFORE the await so
    # concurrent callers (shouldn't happen, but guard for safety) don't pile up.
    coord._last_live_render_unix = now_unix
    coord._last_between_session_render_x = float(cur_x)
    coord._last_between_session_render_y = float(cur_y)

    LOGGER.debug(
        "[MAP] between-session icon re-render: pos=(%.2f, %.2f) prev=(%.2f, %.2f) "
        "elapsed=%.1fs",
        cur_x, cur_y,
        prev_x if prev_x is not None else float("nan"),
        prev_y if prev_y is not None else float("nan"),
        elapsed,
    )
    await coord._render_main_view()


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
        map_data = self.cloud_state.maps_by_id.get(self._active_map_id)
        if map_data is None or not self.live_map.is_active():
            return
        from functools import partial
        from ..map_render import render_with_trail
        if position is None:
            position = self._current_mower_position()
        if heading is None:
            heading = self._current_mower_heading()
        from ..session_card import derive_render_legs
        legs_timeline = derive_render_legs(
            [p.as_dict() for p in self.live_map.track]
        )
        png = await self.hass.async_add_executor_job(
            partial(
                render_with_trail,
                map_data,
                None,
                None,
                position,
                heading,
                None,
                legs_timeline=legs_timeline,
            )
        )
        LOGGER.debug(
            "[MAP] live trail re-render: legs_timeline=%d points=%d bytes=%d pos=%s hdg=%s",
            len(legs_timeline),
            self.live_map.total_points(), len(png) if png else 0,
            position, heading,
        )
        await self._render_main_view()

    async def _render_main_view(self) -> None:
        """Render the active map's Main view (base + live trail + mower icon
        + last-session obstacles overlay).

        Writes the result to self._main_view_png. No-ops gracefully when:
        - _active_map_id is None (active map not yet known)
        - cloud_state.maps_by_id has no entry for the active map
        """
        active_id = self._active_map_id
        if active_id is None:
            return
        map_data = self.cloud_state.maps_by_id.get(active_id)
        if map_data is None:
            return
        from functools import partial

        from ..map_render import render_main_view

        # Track-derived render legs (Task 9): derive_render_legs splits the
        # per-point track on role flips + pen-up gaps so render_with_trail
        # paints mowing legs in light-green and traversal legs in grey-on-top
        # without post-hoc fuzzy matching against cloud track_segments.
        from ..session_card import derive_render_legs
        legs_timeline = (
            derive_render_legs([p.as_dict() for p in self.live_map.track])
            if self.live_map.is_active() else None
        )
        # P4: prefer snapshot (persisted across reboot + seeded from the
        # last session archive at cold-start) over live MowerState, so
        # the mower icon shows on the map even when no s1p4 telemetry
        # is currently flowing (e.g. mower parked at dock between
        # sessions). MowerState fields go None when telemetry stops;
        # the snapshot retains the last known fix.
        mower_pos = self._current_mower_position()
        heading = self._current_mower_heading()
        # T17: idle pre-start preview — pass current MowerState, active map id,
        # and the state-machine mow_session so render_main_view can dispatch
        # to the stripe/light-green preview when the mower is not in session.
        _sm_snap = self.state_machine.snapshot()
        mow_session = _sm_snap.mow_session
        # last_task_op is retained for diagnostics only — render_main_view no
        # longer keys the idle-vs-active decision on it (it's a PERSISTED field
        # that survives reboots as a stale 109, which used to force the
        # flat-green cruise view at a maintenance point). The actual
        # "session active now" signal is live_map.is_active().
        last_task_op = _sm_snap.last_task_op
        # Reboot-survival fix: pass the ACTUAL active-session signal so the
        # renderer skips the idle pre-start preview only during a genuinely
        # active session (e.g. a to-point cruise), not when a finished run's
        # op was merely restored from disk.
        live_map_active = self.live_map.is_active()
        # Bug 1 fix: current_activity lives on StateSnapshot (the state machine),
        # NOT on MowerState.  render_main_view checks `getattr(state,
        # "current_activity", None)` to detect REPOSITIONING and skip the
        # striped pre-start preview.  Without this, passing `state=self.data`
        # (MowerState, which has no current_activity) means `_is_repositioning`
        # is always False and the stripe preview is NEVER suppressed during the
        # ~42s reorientation window.
        #
        # Fix: build a thin proxy that delegates all attribute access to
        # self.data (MowerState) but overrides `current_activity` with the
        # state machine's snapshot value.
        class _StateProxy:
            """Thin proxy: MowerState + state-machine current_activity."""
            __slots__ = ("_base", "current_activity")
            def __init__(self, base, activity):
                object.__setattr__(self, "_base", base)
                object.__setattr__(self, "current_activity", activity)
            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_base"), name)
        _render_state = _StateProxy(self.data, _sm_snap.current_activity)
        # Overlay obstacles captured during the most recent session for
        # this map. Mirrors the Dreame app's "show last-mow obstacles"
        # behavior so users can spot which obstacles to clear before the
        # next mow. HIDDEN during an active mow: last-session obstacles may
        # not be in place for the new session and would be visually
        # misleading. Between sessions (idle) they're shown as a garden-state
        # reminder. (Fix 3 — v1.0.16a3)
        from ..mower.state_snapshot import MowSession as _MowSession
        if mow_session == _MowSession.IN_SESSION:
            obstacle_polygons_m = None
        else:
            obstacle_polygons_m = await self._load_last_session_obstacles(active_id)
        png = await self.hass.async_add_executor_job(
            partial(
                render_main_view,
                map_data,
                legs_timeline=legs_timeline,
                mower_position_m=mower_pos,
                mower_heading_deg=heading,
                obstacle_polygons_m=obstacle_polygons_m,
                state=_render_state,
                map_id=active_id,
                mow_session=mow_session,
                last_task_op=last_task_op,
                live_map_active=live_map_active,
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
            LOGGER.info(
                "[obstacles] map_id=%d: archive index not yet loaded — skipping; "
                "next tick will retry.", map_id,
            )
            return None
        index = getattr(archive, "_index", None) or []
        candidates = [s for s in index if getattr(s, "map_id", -1) == map_id]
        if not candidates:
            # Cache the empty result so we don't re-scan on every tick.
            LOGGER.info(
                "[obstacles] map_id=%d: no archived sessions for this map_id "
                "(index has map_ids=%s).", map_id,
                sorted({s.map_id for s in index}),
            )
            self._last_session_obstacles_by_map[map_id] = []
            return None
        entry = max(candidates, key=lambda s: s.end_ts)

        raw_dict = await self.hass.async_add_executor_job(archive.load, entry)
        if raw_dict is None:
            LOGGER.info(
                "[obstacles] map_id=%d: latest session %s failed to load "
                "(archive.load() returned None).",
                map_id, getattr(entry, "filename", "?"),
            )
            self._last_session_obstacles_by_map[map_id] = []
            return None
        from ..protocol import session_summary as _session_summary
        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary as e:
            LOGGER.info(
                "[obstacles] map_id=%d: latest session %s failed to parse "
                "(InvalidSessionSummary: %s).",
                map_id, getattr(entry, "filename", "?"), str(e),
            )
            self._last_session_obstacles_by_map[map_id] = []
            return None
        polygons: list[list[tuple[float, float]]] = [
            list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3
        ]
        self._last_session_obstacles_by_map[map_id] = polygons
        if not polygons:
            LOGGER.info(
                "[obstacles] map_id=%d: latest session %s archived with "
                "0 obstacles (cloud reported none for this run).",
                map_id, getattr(entry, "filename", "?"),
            )
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
        map_data = self.cloud_state.maps_by_id.get(active_id)
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

