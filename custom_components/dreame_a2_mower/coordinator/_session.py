"""session mixin — extracted from coordinator.py 2026-05-15.

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


class _SessionMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    async def replay_session(self, session_md5: str) -> None:
        """Backwards-compat alias for the Work Log render method.

        Kept so the public dreame_a2_mower.replay_session service (and any
        user automations referencing it) keep working after the rename.
        """
        await self.render_work_log_session(session_md5)

    async def render_work_log_session(self, session_md5: str) -> None:
        """Render an archived session's path into _work_log_png.

        Look up the session by md5 in session_archive, parse its track
        segments via parse_session_summary, then render via
        render_work_log using the archived legs.  Updates
        _work_log_png in-place — the work-log camera entity serves whatever is
        cached, so the replay is immediately visible.

        The replay persists in the work-log camera until the user selects
        the work-log picker's placeholder entry (which sets _work_log_png
        back to None) or the config entry is reloaded.  No periodic refresh
        path touches _work_log_png, so it is not automatically cleared.

        Args:
            session_md5: The md5 string of the archived session.

        Logs a warning and returns early if:
        - The md5 does not match any session in the archive.
        - The raw JSON cannot be loaded from disk.
        - parse_session_summary raises (malformed data).
        - No cloud client is available (not yet initialised).
        """
        import time as _time

        from ..map_decoder import parse_cloud_map
        from ..map_render import render_work_log

        replay_start_unix = _time.monotonic()
        LOGGER.info("[F5.9.1] render_work_log_session: looking up md5=%s", session_md5)

        # --- 1. Find the ArchivedSession entry. The picker passes either:
        #   - the unique filename (post-v1.0.0a53; only key with no
        #     collisions when multiple sessions share an md5), OR
        #   - a 32-char md5 (legacy, also used by the public
        #     dreame_a2_mower.replay_session service). Match either.
        # When multiple entries share an md5 (g2408 reuses md5 across
        # sessions on an unchanged map — see project memo
        # 'g2408 session-archive + target-area quirks'), pick the most
        # recent by end_ts so the user gets the entry they actually
        # see at the top of the picker label list.
        sessions = await self.hass.async_add_executor_job(
            self.session_archive.list_sessions
        )
        by_filename = next(
            (s for s in sessions if s.filename == session_md5), None
        )
        if by_filename is not None:
            entry = by_filename
        else:
            md5_matches = [s for s in sessions if s.md5 == session_md5]
            entry = max(md5_matches, key=lambda s: s.end_ts, default=None)
        if entry is None:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: no session with key=%s in archive "
                "(%d sessions total)", session_md5, len(sessions)
            )
            return

        # --- 2. Load the raw JSON from disk ---
        raw_dict = await self.hass.async_add_executor_job(
            self.session_archive.load, entry
        )
        if raw_dict is None:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: failed to load raw JSON for md5=%s "
                "(filename=%s)", session_md5, entry.filename
            )
            return

        # --- 3. Parse the session summary to extract track_segments ---
        from ..protocol import session_summary as _session_summary
        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary as ex:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: parse_session_summary failed for "
                "md5=%s: %s", session_md5, ex
            )
            return

        # --- 3b. Build the picked-session summary dict (T13) ---
        from ..session_card import build_picked_session_summary, format_session_label
        from ..map_render import extract_projection

        try:
            picker_label = format_session_label(entry)
        except Exception:
            picker_label = (
                getattr(entry, "filename", None)
                or getattr(entry, "md5", None)
                or "(unknown)"
            )
        from ..session_card import derive_render_legs
        from ..live_map.state import track_row_to_dict

        track_rows = raw_dict.get("track") or []
        track = [track_row_to_dict(r) for r in track_rows]
        legs_timeline: list[dict] | None = derive_render_legs(track) or None

        # Replay-only overlay: each Obstacle.polygon is already a tuple
        # of (x_m, y_m) pairs (the protocol decoder handled the cm→m
        # conversion). Pass empty list rather than None when the session
        # has none, so the renderer's branch is consistent.
        obstacle_polygons_m: list[list[tuple[float, float]]] = [
            list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3
        ]

        if not track:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: key=%s has no track data "
                "(archive pre-dates per-point track)", session_md5
            )
            # Fall through — render_work_log handles empty legs gracefully
            # (produces same output as render_base_map).

        # --- 4. Resolve which map to render against (MM Task 11: cross-map replay).
        # Use the map_id stamped on the archived session so replays from a
        # non-active map render against their own base map, not today's active.
        # Fall back to _active_map_id when map_id is -1 (legacy entries).
        session_map_id = getattr(entry, "map_id", -1)
        target_map_id = (
            session_map_id if session_map_id != -1 else self._active_map_id
        )
        map_data = (
            self.cloud_state.maps_by_id.get(target_map_id)
            if target_map_id is not None
            else None
        )
        if map_data is None and self.cloud_state.maps_by_id:
            # No map for the session's stamped id — fall back to any cached map
            # rather than making the replay entirely black. Log a warning so the
            # user knows the render may be wrong.
            fallback_id = min(self.cloud_state.maps_by_id.keys())
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: map_id=%r not in cache (have: %s); "
                "falling back to map_id=%r",
                target_map_id,
                sorted(self.cloud_state.maps_by_id.keys()),
                fallback_id,
            )
            target_map_id = fallback_id
            map_data = self.cloud_state.maps_by_id[fallback_id]
        if map_data is None:
            # Cache entirely empty — try a live fetch as a last resort (slow).
            if not hasattr(self, "_cloud"):
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: cloud client not ready yet; "
                    "cannot fetch map for replay"
                )
                return
            cloud_response = await self.hass.async_add_executor_job(
                self._cloud.fetch_map
            )
            if cloud_response is None:
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: fetch_map returned None; "
                    "cannot render replay for md5=%s", session_md5
                )
                return
            map_data = parse_cloud_map(cloud_response)
            if map_data is None:
                LOGGER.warning(
                    "[F5.9.1] render_work_log_session: parse_cloud_map returned None; "
                    "cannot render replay for md5=%s", session_md5
                )
                return
            # Hydrate the active-map slot so subsequent replays don't re-fetch.
            # cloud_state is the single map store; replace it immutably.
            active_id = self._active_map_id if self._active_map_id is not None else 0
            self.cloud_state = dataclasses.replace(
                self.cloud_state,
                maps_by_id={**self.cloud_state.maps_by_id, active_id: map_data},
            )
            target_map_id = active_id

        # --- 4a. Override with SESSION-TIME no-go zones / spots (Issue 1) ---
        # The replay map's boundary box is stable for a given map, but the
        # exclusion zones / spot areas are user-editable and may have changed
        # since the session ran. Replace the current map's zones with the
        # archived session-time geometry (from the cloud summary's map[]/spot[]
        # layers) so the replay shows what was actually in place during the mow.
        # Trail alignment is unaffected — the boundary box / projection are
        # unchanged; only the overlaid zones differ.
        try:
            from ..map_decoder import apply_session_geometry
            excl_polys = [list(layer.points) for layer in summary.exclusions]
            spot_polys = [list(s.corners) for s in summary.spots]
            if excl_polys or spot_polys:
                map_data = apply_session_geometry(
                    map_data,
                    exclusion_polys_m=excl_polys,
                    spot_polys_m=spot_polys,
                )
        except Exception:
            LOGGER.exception(
                "[F5.9.1] render_work_log_session: session-geometry override "
                "failed for %s — falling back to current-map zones",
                getattr(entry, "filename", "?"),
            )

        # --- 4b. Build the picked-session summary dict (T13) ---
        # Built after map_data is resolved so map_projection can be baked in
        # at construction time (no post-mutation, no transient None state).
        try:
            self._picked_session_summary = build_picked_session_summary(
                raw_dict=raw_dict,
                summary=summary,
                entry=entry,
                picker_label=picker_label,
                map_projection=extract_projection(map_data),
            )
        except Exception:
            LOGGER.exception(
                "[F5.9.1] render_work_log_session: build_picked_session_summary failed "
                "for filename=%s — clearing picked_session",
                getattr(entry, "filename", "?"),
            )
            self._picked_session_summary = None

        # --- 5. Render and cache ---
        # async_add_executor_job only forwards positional args, so use
        # functools.partial to bake obstacle_polygons_m in as a kwarg.
        from functools import partial

        render_kwargs = {"legs_timeline": legs_timeline} if legs_timeline else {}
        png = await self.hass.async_add_executor_job(
            partial(
                render_work_log,
                map_data,
                obstacle_polygons_m=obstacle_polygons_m,
                trail_width_px=self.data.trail_render_width,
                **render_kwargs,
            )
        )
        self._work_log_png = png

        # Render the no-trail base alongside (for replay card background).
        # The replay card draws the trail itself via animated SVG; if the
        # base image already has the trail painted, the user sees both —
        # the static trail flashes before animation begins. The no-trail
        # variant prevents that.
        # Pass obstacle_polygons_m so the base image includes obstacles
        # at the same z-order as render_with_trail; the SVG animated trail
        # then draws on top, giving the animated replay visual parity with
        # the static work_log.png (fix for replay card obstacle parity).
        try:
            from ..map_render import render_base_map
            from functools import partial as _partial
            base_png = await self.hass.async_add_executor_job(
                _partial(
                    render_base_map,
                    map_data,
                    lawn_mode="dark",
                    obstacles=obstacle_polygons_m or None,
                )
            )
            self._work_log_base_png = base_png
        except Exception:
            LOGGER.debug(
                "[F5.9.1] render_work_log_session: render_base_map failed for "
                "no-trail base — replay card will fall back to trail variant"
            )
            self._work_log_base_png = None
        elapsed_ms = int((_time.monotonic() - replay_start_unix) * 1000)
        tl_count = len(legs_timeline) if legs_timeline else 0
        total_pts = sum(len(leg["pts"]) for leg in legs_timeline) if legs_timeline else 0
        LOGGER.warning(
            "[F5.9.1] render_work_log_session: rendered work-log PNG (%d bytes) "
            "for key=%s, track_points=%d, legs=%d, total_leg_points=%d, elapsed=%dms",
            len(png) if png else 0,
            session_md5,
            len(track),
            tl_count,
            total_pts,
            elapsed_ms,
        )
        # Tell HA the camera image changed so it triggers an immediate
        # refresh instead of waiting for the next coordinator tick.
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    def _resolve_finalize_map_id(self) -> int:
        """Map id to stamp on a session being finalized.

        Active-map at finalize time is the canonical answer; if no
        active map yet (rare — MAPL not yet polled), fall back to the
        lowest-id cached map; if no maps cached at all, sentinel -1.
        """
        if self._active_map_id is not None:
            return int(self._active_map_id)
        if self.cloud_state.maps_by_id:
            return min(self.cloud_state.maps_by_id.keys())
        return -1

    async def _periodic_session_retry(self) -> None:
        """Periodic tick (every RETRY_INTERVAL_SECONDS) for session finalization.

        Calls ``finalize.decide(state, prev_task_state, now_unix)`` and
        dispatches the returned action.  All cloud I/O and disk I/O go through
        the executor per spec §3.
        """
        import time as _time
        now_unix = int(_time.time())
        action = _finalize_decide(self.data, self._prev_task_state, now_unix)
        # Boot-stale guard: filter out the gate's false-positive when
        # we just restarted into an MQTT-quiet window mid-session.
        # `_restore_in_progress` seeds `_prev_task_state=0` to support
        # auto-finalize when the mower finished a mow while HA was off
        # — but combined with MowerState.task_state_code's default None
        # (no s2p56 push has landed yet), the gate would otherwise hit
        # FINALIZE_INCOMPLETE on the first retry tick after boot. Skip
        # the dispatch ONLY when the action came from the
        # session_just_ended branch (i.e. no pending OSS object name)
        # AND we haven't observed any real task_state push yet. The
        # max-age / max-attempts FINALIZE_INCOMPLETE path through a
        # known pending OSS key is unaffected.
        # See 2026-05-15 rain-stop incident: HA restarted in a 22-min
        # MQTT-quiet window while the mower was paused-charging; the
        # gate created a phantom (incomplete) session at 0 m² / 337 min.
        if (
            action == FinalizeAction.FINALIZE_INCOMPLETE
            and self.data.task_state_code is None
            and not self._real_task_state_observed
            and not self.data.pending_session_object_name
        ):
            LOGGER.warning(
                "[F5.6.1] _periodic_session_retry: skipping FINALIZE_INCOMPLETE "
                "from boot-stale state (task_state_code still default None, no "
                "fresh MQTT push observed yet, no pending OSS event). "
                "prev_task_state=%r, _real_task_state_observed=%s",
                self._prev_task_state, self._real_task_state_observed,
            )
            return
        if action == FinalizeAction.NOOP:
            return
        # v1.0.0a48: bumped to WARNING so the trail shows up in the
        # default HA log. Only fires on non-NOOP actions, which means
        # at most a handful per mow.
        LOGGER.warning(
            "[F5.6.1] _periodic_session_retry: action=%s "
            "task_state=%r prev=%r pending_oss=%r",
            action.name,
            self.data.task_state_code,
            self._prev_task_state,
            self.data.pending_session_object_name,
        )
        await self._dispatch_finalize_action(action, now_unix)

    async def _wait_for_dock_return(
        self,
        *,
        timeout_s: int = 300,
    ) -> str:
        """Block until the mower has docked or ``timeout_s`` has elapsed.

        Returns one of:
          'charging'   — charging_status flipped to ChargingStatus.CHARGING (1)
          'timeout'    — the dock signal did not fire in time

        The caller logs the reason so the timeout can be tuned later.
        Trail collection continues during the wait because MQTT events keep
        flowing into LiveMapState while we await here.

        Signals are delivered by _on_state_update in _mqtt_handlers.py:
        it checks _pending_finalize_done after each state mutation.

        The finally block clears _pending_finalize_done to None so subsequent
        MQTT pushes don't accidentally set a stale event from a future mow.
        """
        self._pending_finalize_done = asyncio.Event()
        self._pending_finalize_done_reason = None
        try:
            await asyncio.wait_for(
                self._pending_finalize_done.wait(), timeout=timeout_s
            )
            return self._pending_finalize_done_reason or "early"
        except asyncio.TimeoutError:
            return "timeout"
        finally:
            self._pending_finalize_done = None

    async def _finalize_prior_for_new_command(self, now_unix: int) -> None:
        """(c) Finalize the still-active prior session at a new-command boundary.

        Invoked when a DISTINCT new task command begins while the previous
        session is still active (e.g. the user abandoned a manual run on the
        lawn and started a mow from there with no dock between). Unlike the
        normal end-of-session finalize, there is NO dock wait here: the mower
        did not dock — a new command superseded the prior run — so we finalize
        immediately with whatever the prior live_map captured.

        Routes by the prior session's provisional type: a mow finalizes via
        the cloud-summary path if its OSS key already arrived (else locally);
        a non-mow finalizes locally. After this returns the live_map session
        has been ended, so the caller's begin_session starts a clean session.
        """
        if not self.live_map.is_active():
            return
        if self._provisional_session_is_mow() and self.data.pending_session_object_name:
            await self._do_oss_fetch(now_unix)
        else:
            await self._run_finalize_incomplete(now_unix)

    def _provisional_session_is_mow(self) -> bool:
        """Provisional finalize-time classification: is the live_map a MOW?

        Computed from the SAME inputs `_inject_live_map_into_raw_dict` uses so
        the local-finalize decision and the archived `session_type` agree:
        manual_drive (s2p50 op=15) and maintenance_run are NON-mow; a mow is
        any run that saw an s2p2 50/53 start code OR ever had positive area.
        `last_point_end_code` is irrelevant to the mow/non-mow split so we
        pass None.
        """
        from ..live_map.classify import classify_session_type

        lm = self.live_map
        codes = [code for _, code in (lm.error_samples or [])]
        saw_mow_start = any(c in (50, 53) for c in codes)
        session_type, _ = classify_session_type(
            last_task_op=lm.last_task_op,
            saw_mow_start=saw_mow_start,
            area_ever_positive=lm.area_ever_positive,
            last_point_end_code=None,
        )
        return session_type == "mow"

    async def _dispatch_finalize_action(
        self, action: FinalizeAction, now_unix: int
    ) -> None:
        """Dispatch a FinalizeAction from the finalize gate.

        BEGIN_SESSION / BEGIN_LEG: already handled by _on_state_update on every
            property push; nothing to do in the retry path.
        AWAIT_OSS_FETCH / FINALIZE_COMPLETE: fetch the cloud-summary JSON,
            parse it, archive it, and update MowerState.
        FINALIZE_INCOMPLETE: archive whatever live_map has with an "(incomplete)"
            suffix in the md5 field, then clear pending state.
        NOOP: do nothing.

        All blocking I/O runs in the executor per spec §3.

        For AWAIT_OSS_FETCH / FINALIZE_COMPLETE / FINALIZE_INCOMPLETE: enters
        a pending-finalize wait (up to 10 min) so trail collection captures the
        dock-return drive BEFORE the archive write. See _wait_for_dock_return.
        """
        if action in (FinalizeAction.BEGIN_SESSION, FinalizeAction.BEGIN_LEG, FinalizeAction.NOOP):
            return

        if action in (FinalizeAction.AWAIT_OSS_FETCH, FinalizeAction.FINALIZE_COMPLETE):
            # (a) LOCAL FINALIZE FOR NON-MOW. The cloud OSS summary only ever
            # arrives for a mow; a maintenance run / manual drive produces no
            # summary, so awaiting one would hang the finalize (live_map stays
            # active and the NEXT run merges into it). Classify provisionally
            # from the SAME inputs the injector uses; if it is NOT a mow,
            # finalize locally instead of fetching the cloud summary. The mow
            # path below is unchanged.
            if not self._provisional_session_is_mow():
                LOGGER.info(
                    "[F5.6.1] session-done (action=%s) but provisional type is "
                    "NON-MOW — finalizing locally (no cloud-summary await)",
                    action.name,
                )
                reason = await self._wait_for_dock_return(timeout_s=600)
                LOGGER.info(
                    "[F5.6.1] pending-finalize wait ended: reason=%s", reason
                )
                await self._run_finalize_incomplete(now_unix)
                return
            LOGGER.info(
                "[F5.6.1] session-done received (action=%s) — "
                "entering pending-finalize wait (≤10 min)",
                action.name,
            )
            reason = await self._wait_for_dock_return(timeout_s=600)
            LOGGER.info("[F5.6.1] pending-finalize wait ended: reason=%s", reason)
            await self._do_oss_fetch(now_unix)
            return

        if action == FinalizeAction.FINALIZE_INCOMPLETE:
            LOGGER.info(
                "[F5.6.1] session-done received (action=FINALIZE_INCOMPLETE) — "
                "entering pending-finalize wait (≤10 min)"
            )
            reason = await self._wait_for_dock_return(timeout_s=600)
            LOGGER.info("[F5.6.1] pending-finalize wait ended: reason=%s", reason)
            await self._run_finalize_incomplete(now_unix)
            return

        LOGGER.warning("[F5.6.1] _dispatch_finalize_action: unhandled action=%s", action)

    async def _run_finalize_incomplete(self, now_unix: int) -> None:
        """Archive whatever the live_map has as an "(incomplete)" session.

        Builds a minimal ArchivedSession directly from LiveMapState (no cloud
        summary), archives it, then clears pending state and ends the session.

        The archived entry has md5="(incomplete)" so callers can distinguish it
        from a cloud-fetched session.

        Called from two paths:
          - ``_dispatch_finalize_action(FinalizeAction.FINALIZE_INCOMPLETE)``
            (periodic retry gate, F5.6.1)
          - ``dispatch_action(MowerAction.FINALIZE_SESSION, ...)``
            (manual escape hatch, F5.10.1)
        """

        LOGGER.info(
            "[F5.6.1] _do_finalize_incomplete: giving up on cloud summary; "
            "archiving incomplete session (started_unix=%s, points=%d)",
            self.live_map.started_unix,
            self.live_map.total_points(),
        )

        # Build a minimal ArchivedSession from whatever we have.
        # v1.0.0a24: if live_map is empty (session already ended but
        # in_progress.json wasn't promoted because the cloud summary
        # never arrived), fall back to the on-disk in_progress.json.
        # Without this, pressing the "Finalize stuck session" button
        # after a session ended would either silently no-op or write
        # a 0-area / 0-duration bogus entry.
        if self.live_map.is_active() or self.live_map.track:
            start_ts = self.live_map.started_unix or now_unix
            end_ts = now_unix
            area = self.data.area_mowed_m2 or 0.0
        else:
            # Try the disk fallback.
            try:
                disk_data = await self.hass.async_add_executor_job(
                    self.session_archive.read_in_progress
                )
            except Exception as ex:
                LOGGER.warning("finalize_incomplete: read_in_progress failed: %s", ex)
                disk_data = None
            if disk_data:
                start_ts = int(disk_data.get("session_start_ts", 0)) or now_unix
                end_ts = int(disk_data.get("last_update_ts", now_unix)) or now_unix
                area = float(disk_data.get("area_mowed_m2", 0.0))
                LOGGER.info(
                    "finalize_incomplete: live_map empty; rebuilt from on-disk "
                    "in_progress.json (start_ts=%s, end_ts=%s, area=%.1f m²)",
                    start_ts, end_ts, area,
                )
            else:
                LOGGER.info(
                    "finalize_incomplete: no live session and no on-disk in_progress; "
                    "nothing to finalize — exiting"
                )
                return
        duration_min = max(0, (end_ts - start_ts) // 60)

        # Write a minimal JSON to disk so the session isn't silently lost.
        # Uses the same archive() mechanism but with a synthesised summary-like dict.
        incomplete_payload: dict[str, Any] = {
            "start": start_ts,
            "end": end_ts,
            "time": duration_min,
            "areas": area,
            "md5": "(incomplete)",
            "_note": "Cloud summary fetch expired; this entry was generated locally.",
        }
        # v1.0.12a2+: include telemetry sample buffers, legs, and
        # settings_snapshot when present. Delegates to the shared helper
        # in _LidarOssMixin so both paths stay in sync.
        self._inject_live_map_into_raw_dict(incomplete_payload)

        # Recorder-merge safety net (2026-05-16 spec) — same layer
        # _do_oss_fetch uses, applied to the FINALIZE_INCOMPLETE
        # payload before it gets archived.
        try:
            from ._recorder_merge import merge_recorder_samples

            _start_ts = int(incomplete_payload.get("start") or 0)
            _end_ts = int(incomplete_payload.get("end") or 0)
            if _start_ts > 0 and _end_ts > _start_ts:
                _counts = await merge_recorder_samples(
                    self.hass, incomplete_payload, _start_ts, _end_ts,
                )
                LOGGER.info(
                    "[recorder_merge] FINALIZE_INCOMPLETE: "
                    "battery=%d, wifi=%d, state=%d, charging=%d, error=%d "
                    "samples merged from recorder for session [%d, %d]",
                    _counts["battery_recorder_count"],
                    _counts["wifi_recorder_count"],
                    _counts["state_recorder_count"],
                    _counts["charging_recorder_count"],
                    _counts["error_recorder_count"],
                    _start_ts, _end_ts,
                )
        except Exception:
            LOGGER.exception(
                "[recorder_merge] FINALIZE_INCOMPLETE: merge failed; "
                "using in_progress samples only"
            )

        # Apply smoothing-only classify so incomplete-session archives get role
        # refinement (cloud_track=[] → smoothing still runs on track points).
        try:
            from ._lidar_oss import finalize_classify_raw_dict
            finalize_classify_raw_dict(incomplete_payload, [])
        except Exception:
            LOGGER.debug(
                "[F5.6.1] _do_finalize_incomplete: classify failed; "
                "incomplete archive will have stage-1 roles only"
            )

        # Build a duck-typed proxy that satisfies SessionArchive.archive(summary).
        # We use a SimpleNamespace because class-level attribute assignments can't
        # reference the enclosing function's local variables in Python.
        import types as _types
        proxy = _types.SimpleNamespace(
            md5="(incomplete)",
            end_ts=end_ts,
            start_ts=start_ts,
            duration_min=duration_min,
            area_mowed_m2=area,
            map_area_m2=0,
            mode=0,
            result=0,
            stop_reason=0,
        )

        try:
            await self.hass.async_add_executor_job(
                self.session_archive.archive, proxy, incomplete_payload,
                self._resolve_finalize_map_id()
            )
        except Exception as ex:
            LOGGER.warning("[F5.6.1] _do_finalize_incomplete: archive raised: %s", ex)

        # Without this, the synthesized in-progress entry keeps
        # reappearing in the picker after every finalize, leaving the
        # archived entry _and_ a phantom "in progress" row side-by-side.
        try:
            await self.hass.async_add_executor_job(
                self.session_archive.delete_in_progress
            )
        except Exception as ex:
            LOGGER.warning("[F5.6.1] _do_finalize_incomplete: delete_in_progress raised: %s", ex)

        # Clear pending state, end live_map session.
        self._fire_mowing_ended(
            now_unix=now_unix,
            area_mowed_m2=area,
            duration_min=(
                int((now_unix - start_ts) / 60)
                if start_ts > 0
                else None
            ),
            completed=False,
        )
        self.live_map.end_session()
        new_count = self.session_archive.count
        self.async_set_updated_data(
            dataclasses.replace(
                self.data,
                pending_session_object_name=None,
                pending_session_first_event_unix=None,
                pending_session_last_attempt_unix=None,
                pending_session_attempt_count=None,
                archived_session_count=new_count,
                session_started_unix=None,
                session_track_segments=(),
            )
        )

    async def _restore_in_progress(self) -> None:
        """Restore a live session from sessions/in_progress.json on HA boot.

        Uses restore-then-merge: always reads disk FIRST, merges with the
        current in-memory state (which may already contain MQTT-pushed data
        if a broker-retained push beat us here), then hydrates live_map from
        the merged result. Either side's data survives the race.

        Prior behaviour bailed out when live_map.is_active() was True,
        causing the 2026-05-15 19h-session data-loss: an MQTT push arriving
        before restore left 8.5h of persisted samples silently overwritten
        by the next _persist_in_progress tick.

        Early-return only when disk is empty AND live_map has no session —
        i.e. nothing to restore on either side.
        """
        from ._restore_merge import merge_in_progress_payloads

        LOGGER.info("[F5.7.1] _restore_in_progress: starting (restore-then-merge)")

        try:
            disk_payload: dict | None = await self.hass.async_add_executor_job(
                self.session_archive.read_in_progress
            )
        except Exception as ex:
            LOGGER.warning("[F5.7.1] _restore_in_progress: read_in_progress raised: %s", ex)
            disk_payload = None

        if disk_payload is None and not self.live_map.is_active():
            LOGGER.debug(
                "[F5.7.1] _restore_in_progress: no disk payload and no live session"
                " — nothing to restore"
            )
            return

        # Snapshot in-memory state as a payload so merge_in_progress_payloads
        # can compare apples-to-apples with the disk payload.
        memory_payload = self.live_map.dump_to_payload()
        merged = merge_in_progress_payloads(disk=disk_payload, memory=memory_payload)

        # Validate merged result has a usable session_start_ts.
        try:
            merged_start = int(merged.get("session_start_ts", 0) or 0)
        except (TypeError, ValueError):
            merged_start = 0

        if merged_start <= 0:
            LOGGER.warning(
                "[F5.7.1] _restore_in_progress: merged payload has no valid"
                " session_start_ts — discarding"
            )
            return

        # Hydrate live_map from the merged payload.
        self.live_map.hydrate_from_payload(merged)

        # Restore last_telemetry_unix from whichever payload has it.  This
        # field is written to disk as "last_update_ts" by _persist_in_progress
        # (legacy key) — not part of the merge contract, so patch it here.
        for src in (disk_payload, memory_payload):
            if src is None:
                continue
            raw_ts = src.get("last_update_ts", 0)
            try:
                ts = int(raw_ts or 0) or None
            except (TypeError, ValueError):
                ts = None
            if ts is not None:
                if (
                    self.live_map.last_telemetry_unix is None
                    or ts > self.live_map.last_telemetry_unix
                ):
                    self.live_map.last_telemetry_unix = ts

        LOGGER.info(
            "[F5.7.1] _restore_in_progress: restore-merged:"
            " started_unix=%s, track_points=%d,"
            " battery_samples=%d, wifi_samples=%d, state_samples=%d",
            self.live_map.started_unix,
            self.live_map.total_points(),
            len(self.live_map.battery_samples),
            len(self.live_map.wifi_samples),
            len(self.live_map.state_samples),
        )

        # Seed state machine: an in_progress.json on disk proves a real
        # mow session was active. Without this, the state machine would
        # stay BETWEEN_SESSIONS until the next start event — which only
        # fires on the NEXT session, not the current one.
        sm = getattr(self, "state_machine", None)
        if sm is not None:
            try:
                import time as _time
                sm.seed_in_session(now_unix=int(_time.time()))
            except Exception:
                LOGGER.exception(
                    "state_machine.seed_in_session failed during restore"
                )

        # Seed _prev_task_state to "running" so the finalize gate's
        # session-end detection (prev ∈ {0,4} → new ∈ {2,None}) fires on
        # the next MQTT tick if the mower has actually gone idle while
        # HA was off. Without this, prev stays None at boot and the
        # idle-while-off case wouldn't trigger FINALIZE_INCOMPLETE.
        self._prev_task_state = 0

        # Restore last_all_area_mow_direction_deg from merged payload.
        # JSON round-trips int keys as strings — normalise back to int.
        raw_dir_map = merged.get("last_all_area_mow_direction_deg") or {}
        restored_dir_map: dict[int, int] = {
            int(k): int(v) for k, v in raw_dir_map.items() if v is not None
        }

        # Sync MowerState (fold both fields into one replace to avoid
        # firing two consecutive update signals).
        new_state = dataclasses.replace(
            self.data,
            session_started_unix=merged_start,
            # Single flat segment holding all restored track points — same
            # shape _mqtt_handlers.py emits under the track model.
            session_track_segments=(
                (tuple((p.x_m, p.y_m) for p in self.live_map.track),)
                if self.live_map.track else ()
            ),
            last_all_area_mow_direction_deg=restored_dir_map,
        )
        self.async_set_updated_data(new_state)
        LOGGER.info("[F5.7.1] _restore_in_progress: MowerState updated (session restored from disk)")

    async def _persist_in_progress(self, _now: Any = None) -> None:
        """Write the current live_map state to sessions/in_progress.json.

        Scheduled every 30 seconds via async_track_time_interval.  Only
        writes when the session is active AND the dirty flag is set
        (i.e. at least one new point has been appended since the last write).
        This debounces the persist: if the mower is idle no new points arrive
        so no unnecessary disk I/O occurs.

        All blocking I/O goes through hass.async_add_executor_job per spec §3.
        """
        if not self.live_map.is_active():
            return
        if not self._live_map_dirty:
            LOGGER.debug("[F5.7.1] _persist_in_progress: live_map not dirty — skipping")
            return

        # The wire-shape payload (session_start_ts, session_ending, track,
        # wifi/battery/charging/state/error samples, charge_at_start,
        # settings_snapshot) is produced by live_map.dump_to_payload().
        # Add the three coordinator-only keys that live on MowerState.
        payload: dict[str, Any] = self.live_map.dump_to_payload()
        payload["area_mowed_m2"] = self.data.area_mowed_m2 or 0.0
        payload["map_area_m2"] = 0
        # Per-map last all-area mow direction — shallow copy guards
        # against post-write mutation bleeding into the persisted payload.
        payload["last_all_area_mow_direction_deg"] = dict(
            self.data.last_all_area_mow_direction_deg
        )
        try:
            await self.hass.async_add_executor_job(
                self.session_archive.write_in_progress, payload
            )
            # Clear the dirty flag only on successful write.
            self._live_map_dirty = False
            LOGGER.debug(
                "[F5.7.1] _persist_in_progress: wrote in_progress.json "
                "(started_unix=%s, points=%d)",
                self.live_map.started_unix,
                self.live_map.total_points(),
            )
        except Exception as ex:
            # Non-fatal — next tick will retry.
            LOGGER.warning("[F5.7.1] _persist_in_progress: write failed: %s", ex)

