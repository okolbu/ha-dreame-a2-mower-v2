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

        This is one-shot: the next _refresh_map tick (every 6 hours, or
        sooner on map-data change) restores the live view.

        Args:
            session_md5: The md5 string of the archived session.

        Logs a warning and returns early if:
        - The md5 does not match any session in the archive.
        - The raw JSON cannot be loaded from disk.
        - parse_session_summary raises (malformed data).
        - _refresh_map hasn't fetched map data yet (no cloud client).
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

        # track_segments is tuple[tuple[tuple[float,float],...],...]
        # render_work_log expects list[list[tuple[float,float]]]
        legs: list[list[tuple[float, float]]] = [
            list(seg) for seg in summary.track_segments
        ]

        # Replay-only overlay: each Obstacle.polygon is already a tuple
        # of (x_m, y_m) pairs (the protocol decoder handled the cm→m
        # conversion). Pass empty list rather than None when the session
        # has none, so the renderer's branch is consistent.
        obstacle_polygons_m: list[list[tuple[float, float]]] = [
            list(o.polygon) for o in summary.obstacles if len(o.polygon) >= 3
        ]

        # v1.0.0a54 fallback: g2408 omits `track` / `old_track` from
        # spot/zone session_summary JSONs entirely, so summary.track_segments
        # is empty. The auto-finalize path now stores the locally-collected
        # legs under `_local_legs` so the replay can still draw a path.
        if not legs:
            local = raw_dict.get("_local_legs") or []
            if isinstance(local, list):
                rebuilt: list[list[tuple[float, float]]] = []
                for leg in local:
                    pts = [
                        (float(p[0]), float(p[1]))
                        for p in leg
                        if isinstance(p, (list, tuple)) and len(p) >= 2
                    ]
                    if pts:
                        rebuilt.append(pts)
                if rebuilt:
                    legs = rebuilt

        if not legs:
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: key=%s has no track segments "
                "(no cloud track + no _local_legs fallback)", session_md5
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
            self._cached_maps_by_id.get(target_map_id)
            if target_map_id is not None
            else None
        )
        if map_data is None and self._cached_maps_by_id:
            # No map for the session's stamped id — fall back to any cached map
            # rather than making the replay entirely black. Log a warning so the
            # user knows the render may be wrong.
            fallback_id = min(self._cached_maps_by_id.keys())
            LOGGER.warning(
                "[F5.9.1] render_work_log_session: map_id=%r not in cache (have: %s); "
                "falling back to map_id=%r",
                target_map_id,
                sorted(self._cached_maps_by_id.keys()),
                fallback_id,
            )
            target_map_id = fallback_id
            map_data = self._cached_maps_by_id[fallback_id]
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
            active_id = self._active_map_id if self._active_map_id is not None else 0
            self._cached_maps_by_id[active_id] = map_data
            target_map_id = active_id

        # --- 5. Render and cache ---
        # async_add_executor_job only forwards positional args, so use
        # functools.partial to bake obstacle_polygons_m in as a kwarg.
        from functools import partial

        png = await self.hass.async_add_executor_job(
            partial(
                render_work_log,
                map_data,
                legs=legs,
                obstacle_polygons_m=obstacle_polygons_m,
            )
        )
        self._work_log_png = png
        elapsed_ms = int((_time.monotonic() - replay_start_unix) * 1000)
        LOGGER.warning(
            "[F5.9.1] render_work_log_session: rendered work-log PNG (%d bytes) "
            "for key=%s, legs=%d, total_points=%d, elapsed=%dms",
            len(png) if png else 0,
            session_md5,
            len(legs),
            sum(len(leg) for leg in legs),
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
        if self._cached_maps_by_id:
            return min(self._cached_maps_by_id.keys())
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
        """
        if action in (FinalizeAction.BEGIN_SESSION, FinalizeAction.BEGIN_LEG, FinalizeAction.NOOP):
            return

        if action in (FinalizeAction.AWAIT_OSS_FETCH, FinalizeAction.FINALIZE_COMPLETE):
            await self._do_oss_fetch(now_unix)
            return

        if action == FinalizeAction.FINALIZE_INCOMPLETE:
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
            "archiving incomplete session (started_unix=%s, legs=%d)",
            self.live_map.started_unix,
            len(self.live_map.legs),
        )

        # Build a minimal ArchivedSession from whatever we have.
        # v1.0.0a24: if live_map is empty (session already ended but
        # in_progress.json wasn't promoted because the cloud summary
        # never arrived), fall back to the on-disk in_progress.json.
        # Without this, pressing the "Finalize stuck session" button
        # after a session ended would either silently no-op or write
        # a 0-area / 0-duration bogus entry.
        if self.live_map.is_active() or self.live_map.legs:
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
        # v1.0.12a2+: include telemetry sample buffers when present so an
        # incomplete-finalize archive entry still carries the SoC/state
        # curves. Mirrors the OSS-fetch injection in _lidar_oss.py.
        if self.live_map.wifi_samples:
            incomplete_payload["wifi_samples"] = [
                list(s) for s in self.live_map.wifi_samples
            ]
        if self.live_map.battery_samples:
            incomplete_payload["battery_samples"] = [
                list(s) for s in self.live_map.battery_samples
            ]
        if self.live_map.charging_status_samples:
            incomplete_payload["charging_status_samples"] = [
                list(s) for s in self.live_map.charging_status_samples
            ]
        if self.live_map.state_samples:
            incomplete_payload["state_samples"] = [
                list(s) for s in self.live_map.state_samples
            ]
        if self.live_map.error_samples:
            incomplete_payload["error_samples"] = [
                list(s) for s in self.live_map.error_samples
            ]
        if self.live_map.charge_at_start is not None:
            incomplete_payload["charge_at_start"] = int(self.live_map.charge_at_start)
        if self.live_map.legs and any(self.live_map.legs):
            incomplete_payload["_local_legs"] = [
                [[float(x), float(y)] for (x, y) in leg]
                for leg in self.live_map.legs
                if leg
            ]

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

        Called once from _async_update_data's first-refresh path, AFTER
        cloud auth but BEFORE _init_mqtt subscribes. Running before MQTT
        ensures broker-retained s2p56 pushes can't beat us into
        _on_state_update and call begin_session(now_unix), which would
        clobber the disk-restored legs and started_unix.

        Reads the in-progress entry via executor (blocking disk I/O). If a
        previous session was still active when HA shut down, repopulates
        LiveMapState.legs + started_unix and syncs MowerState fields
        (session_active=True, session_started_unix, session_track_segments).
        Also seeds _prev_task_state=0 so the finalize gate's session-end
        detection works on the next MQTT tick.

        Defensive guard: if for any reason live_map is already active when
        we get here, skip the restore so we don't stomp a freshly-started
        session. With the pre-MQTT ordering this branch is unreachable in
        normal operation, but the guard is kept as belt-and-suspenders.
        """
        data: dict | None = await self.hass.async_add_executor_job(
            self.session_archive.read_in_progress
        )
        if data is None:
            LOGGER.debug("[F5.7.1] _restore_in_progress: no in-progress file on disk")
            return

        # If the MQTT push for a new session already started live_map before
        # we got here, don't stomp the fresh session with the old disk data.
        if self.live_map.is_active():
            LOGGER.info(
                "[F5.7.1] _restore_in_progress: live_map already active "
                "(MQTT arrived before restore); skipping disk restore"
            )
            return

        try:
            started_unix = int(data.get("session_start_ts", 0) or 0)
        except (TypeError, ValueError):
            started_unix = 0

        if started_unix <= 0:
            LOGGER.warning(
                "[F5.7.1] _restore_in_progress: in-progress entry has no "
                "valid session_start_ts — discarding"
            )
            return

        # Restore legs: list[list[[x_m, y_m]]] on disk → list[list[tuple]]
        raw_legs = data.get("legs", [])
        legs: list[list[tuple[float, float]]] = []
        try:
            for raw_leg in raw_legs:
                legs.append([(float(pt[0]), float(pt[1])) for pt in raw_leg])
        except (TypeError, ValueError, IndexError) as ex:
            LOGGER.warning(
                "[F5.7.1] _restore_in_progress: legs decode error %s — "
                "starting with empty legs",
                ex,
            )
            legs = []

        LOGGER.info(
            "[F5.7.1] _restore_in_progress: restoring session started_unix=%d, "
            "legs=%d, total_points=%d",
            started_unix,
            len(legs),
            sum(len(leg) for leg in legs),
        )

        # Restore wifi_samples (v1.0.10a6+). Legacy in_progress.json
        # blobs from earlier versions lack this key; default to empty.
        raw_wifi = data.get("wifi_samples", [])
        wifi_samples: list[tuple[float, float, int, int]] = []
        if isinstance(raw_wifi, list):
            for s in raw_wifi:
                try:
                    wifi_samples.append(
                        (float(s[0]), float(s[1]), int(s[2]), int(s[3]))
                    )
                except (TypeError, ValueError, IndexError):
                    continue

        # Restore telemetry sample buffers (v1.0.12a2+). Legacy blobs
        # lack these keys; default to empty so restore is a no-op.
        def _restore_samples(key: str) -> list[tuple[int, int]]:
            raw = data.get(key, [])
            out: list[tuple[int, int]] = []
            if isinstance(raw, list):
                for s in raw:
                    try:
                        out.append((int(s[0]), int(s[1])))
                    except (TypeError, ValueError, IndexError):
                        continue
            return out

        battery_samples = _restore_samples("battery_samples")
        charging_status_samples = _restore_samples("charging_status_samples")
        state_samples = _restore_samples("state_samples")
        error_samples = _restore_samples("error_samples")
        charge_at_start_raw = data.get("charge_at_start")
        charge_at_start: int | None
        try:
            charge_at_start = (
                int(charge_at_start_raw) if charge_at_start_raw is not None else None
            )
        except (TypeError, ValueError):
            charge_at_start = None

        raw_settings = data.get("settings_snapshot")
        settings_snapshot: dict[str, Any] | None = (
            dict(raw_settings) if isinstance(raw_settings, dict) else None
        )

        # Populate LiveMapState.
        self.live_map.started_unix = started_unix
        self.live_map.legs = legs if legs else [[]]
        self.live_map.last_telemetry_unix = int(data.get("last_update_ts", 0) or 0) or None
        self.live_map.wifi_samples = wifi_samples
        self.live_map.battery_samples = battery_samples
        self.live_map.charging_status_samples = charging_status_samples
        self.live_map.state_samples = state_samples
        self.live_map.error_samples = error_samples
        self.live_map.charge_at_start = charge_at_start
        self.live_map.settings_snapshot = settings_snapshot

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

        # Sync MowerState.
        new_state = dataclasses.replace(
            self.data,
            session_started_unix=started_unix,
            session_track_segments=tuple(tuple(leg) for leg in self.live_map.legs),
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

        payload: dict[str, Any] = {
            "session_start_ts": self.live_map.started_unix,
            # legs: serialise as list[list[list[float]]] so JSON round-trips cleanly.
            "legs": [list(list(pt) for pt in leg) for leg in self.live_map.legs],
            # wifi_samples: list of (x_m, y_m, rssi_dbm, ts_unix) tuples.
            # Serialised as list[list] so JSON round-trip preserves shape.
            # See LiveMapState.wifi_samples and the heatmap matcher
            # in wifi_match.py for the consumer side.
            "wifi_samples": [list(s) for s in self.live_map.wifi_samples],
            # Telemetry sample buffers (v1.0.12a2+). Each entry is
            # [ts_unix, value]. See LiveMapState for capture sources.
            "battery_samples": [list(s) for s in self.live_map.battery_samples],
            "charging_status_samples": [
                list(s) for s in self.live_map.charging_status_samples
            ],
            "state_samples": [list(s) for s in self.live_map.state_samples],
            "error_samples": [list(s) for s in self.live_map.error_samples],
            "charge_at_start": self.live_map.charge_at_start,
            "settings_snapshot": self.live_map.settings_snapshot,
            "area_mowed_m2": self.data.area_mowed_m2 or 0.0,
            "map_area_m2": 0,
        }
        try:
            await self.hass.async_add_executor_job(
                self.session_archive.write_in_progress, payload
            )
            # Clear the dirty flag only on successful write.
            self._live_map_dirty = False
            LOGGER.debug(
                "[F5.7.1] _persist_in_progress: wrote in_progress.json "
                "(started_unix=%s, legs=%d, points=%d)",
                self.live_map.started_unix,
                len(self.live_map.legs),
                self.live_map.total_points(),
            )
        except Exception as ex:
            # Non-fatal — next tick will retry.
            LOGGER.warning("[F5.7.1] _persist_in_progress: write failed: %s", ex)

