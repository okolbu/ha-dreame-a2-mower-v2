"""lidar_oss mixin — extracted from coordinator.py 2026-05-15.

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
from ..mower.state import ActionMode, ChargingStatus, MowerState
from .._render_direction import infer_mow_direction
from ..mower.state_machine import MowerStateMachine
from ..mqtt_client import DreameA2MqttClient
from ..observability import FreshnessTracker, NovelObservationRegistry
from ..observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from ..protocol import session_summary as _session_summary

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


class _LidarOssMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    def _inject_live_map_into_raw_dict(self, raw_dict: dict[str, Any]) -> None:
        """Add LiveMapState-tracked fields to a cloud-OSS raw_dict before archive.

        Mutates raw_dict in place. Called from _do_oss_fetch and from the
        FINALIZE_INCOMPLETE path. Skips fields whose source is empty so
        older cloud blobs aren't polluted with empty arrays.
        """
        if self.live_map.legs and any(self.live_map.legs):
            raw_dict["_local_legs"] = [
                [[float(x), float(y)] for (x, y) in leg]
                for leg in self.live_map.legs
                if leg
            ]
            # Mowing-vs-traversal split captured at append-point time
            # (v1.0.16a6+). Renderers consume these directly; falls
            # back to fuzzy splitter on older archives that only have
            # _local_legs. Empty arrays still written so the schema is
            # detectable.
            raw_dict["_mowing_legs"] = [
                [[float(x), float(y)] for (x, y) in leg]
                for leg, mowing in zip(self.live_map.legs, self.live_map.leg_is_mowing)
                if leg and mowing
            ]
            raw_dict["_traversal_legs"] = [
                [[float(x), float(y)] for (x, y) in leg]
                for leg, mowing in zip(self.live_map.legs, self.live_map.leg_is_mowing)
                if leg and not mowing
            ]
            # Per-leg metadata (role + start_ts + end_ts). Documented in
            # inventory.yaml under summary_legs_meta (Task 12).
            raw_dict["_legs_meta"] = [
                {
                    "role": "mowing" if mowing else "traversal",
                    "start_ts": int(st),
                    "end_ts": int(en),
                }
                for leg, mowing, st, en in zip(
                    self.live_map.legs,
                    self.live_map.leg_is_mowing,
                    self.live_map.leg_start_ts,
                    self.live_map.leg_end_ts,
                )
                if leg
            ]
        if self.live_map.wifi_samples:
            raw_dict["wifi_samples"] = [
                [float(x), float(y), int(r), int(t)]
                for (x, y, r, t) in self.live_map.wifi_samples
            ]
        if self.live_map.battery_samples:
            raw_dict["battery_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.battery_samples
            ]
        if self.live_map.charging_status_samples:
            raw_dict["charging_status_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.charging_status_samples
            ]
        if self.live_map.state_samples:
            raw_dict["state_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.state_samples
            ]
        if self.live_map.error_samples:
            raw_dict["error_samples"] = [
                [int(t), int(v)] for (t, v) in self.live_map.error_samples
            ]
        if self.live_map.charge_at_start is not None:
            raw_dict["charge_at_start"] = int(self.live_map.charge_at_start)
        if self.live_map.settings_snapshot is not None:
            raw_dict["settings_snapshot"] = dict(self.live_map.settings_snapshot)

    def lidar_archive_for(self, map_id: int) -> LidarArchive:
        """Return (or lazily create) the LidarArchive for *map_id*.

        Creates a new :class:`LidarArchive` under
        ``<_lidar_archive_root>/<map_id>/`` on first access and caches it
        in :attr:`lidar_archives`.  The per-archive retention and size caps
        are inherited from the coordinator's option values.
        """
        if map_id not in self.lidar_archives:
            self.lidar_archives[map_id] = LidarArchive(
                self._lidar_archive_root,
                retention=self._lidar_archive_retention,
                max_bytes=self._lidar_archive_max_bytes,
                map_id=map_id,
            )
        return self.lidar_archives[map_id]

    def list_lidar_archive_entries(self) -> list[tuple[int, Any]]:
        """Aggregate all LiDAR scans across maps, newest first.

        Returns list of (map_id, ArchivedLidarScan) tuples. Used by the
        cross-map LiDAR archive picker (``select.dreame_a2_mower_lidar_archive``).
        """
        out: list[tuple[int, Any]] = []
        for map_id, archive in self.lidar_archives.items():
            for entry in archive.entries():
                out.append((map_id, entry))
        out.sort(key=lambda x: x[1].unix_ts, reverse=True)
        return out

    def set_lidar_render_entry(self, map_id: int | None, filename: str | None) -> None:
        """Set which LiDAR scan the selected-camera renders. None resets to default."""
        if map_id is None or filename is None:
            self._lidar_render_entry = None
        else:
            self._lidar_render_entry = (map_id, filename)
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    def _build_map_extents(self) -> dict[int, tuple[float, float, float, float]]:
        """Build map_id → (bx1, by1, bx2, by2) in cm for all cached maps.

        Used by refresh_wifi_archive to pass geometry hints to
        cloud_client.list_wifi_candidates for cross-map heatmap matching.
        Falls back to empty dict when no maps are cached or extent fields
        are unavailable.
        """
        extents: dict[int, tuple[float, float, float, float]] = {}
        for map_id, map_data in self._cached_maps_by_id.items():
            try:
                bx1 = float(getattr(map_data, "bx1", 0.0))
                by1 = float(getattr(map_data, "by1", 0.0))
                bx2 = float(getattr(map_data, "bx2", 0.0))
                by2 = float(getattr(map_data, "by2", 0.0))
                extents[map_id] = (bx1, by1, bx2, by2)
            except (TypeError, ValueError, AttributeError):
                continue
        return extents

    def _get_wifi_body_cached(self, object_name: str) -> "dict | None":
        """Return the cached decoded wifi-body for ``object_name``, or None.

        Never touches the disk; callers that need the body to be present
        should await ``_async_load_wifi_body`` first, or rely on the
        task scheduled by ``set_wifi_render_entry``.
        """
        return self._wifi_body_cache.get(object_name)

    async def _async_load_wifi_body(self, object_name: str) -> None:
        """Executor-side load of a wifi body; populates ``_wifi_body_cache``.

        Safe to call multiple times for the same object_name — the cache
        acts as a dedup guard.  After loading, notifies all listeners so
        the camera's ``available`` property re-evaluates with the new data.
        """
        store = getattr(self, "_wifi_archive_store", None)
        if store is None:
            return
        body = await self.hass.async_add_executor_job(
            store.load_body, object_name
        )
        self._wifi_body_cache[object_name] = body
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    def set_wifi_render_entry(
        self, map_id: int | None, object_name: str | None
    ) -> None:
        """Set which WiFi heatmap the archive camera renders.

        ``object_name`` is the only identity used now (since the
        archive picker always passes ``map_id=None``: heatmap →
        map_id correlation is unsolved — see
        ``docs/research/wifi-heatmap-todo.md``). Pass
        ``object_name=None`` to clear the selection.

        If the body for ``object_name`` is not yet cached, schedules an
        async load via ``hass.async_create_task``.  The camera's
        ``available`` returns False until the load completes; a subsequent
        listener notification makes it True.
        """
        if object_name is None:
            self._wifi_render_entry = None
        else:
            self._wifi_render_entry = (map_id, object_name)
            # Pre-warm the body cache if not already present.
            if object_name not in self._wifi_body_cache:
                self.hass.async_create_task(
                    self._async_load_wifi_body(object_name)
                )
        update_listeners = getattr(self, "async_update_listeners", None)
        if callable(update_listeners):
            update_listeners()

    async def _handle_lidar_object_name(
        self, object_name: str, now_unix: int
    ) -> None:
        """Fetch and archive a LiDAR PCD scan announced via s99p20.

        Called from `_on_state_update` whenever
        `MowerState.latest_lidar_object_name` flips to a new key.
        Idempotent: caches the last-handled object_name to avoid
        re-fetching while the property re-asserts.

        Failures are logged at WARNING and swallowed — observability
        never breaks telemetry, and the user can re-trigger the upload
        from the app.
        """
        if not object_name or object_name == self._last_lidar_object_name:
            return
        self._last_lidar_object_name = object_name
        LOGGER.info("[LIDAR] s99p20 announced object_name=%r", object_name)

        # T12: route to the per-map archive for the currently active map.
        active_id = getattr(self, "_active_map_id", None)
        if active_id is None:
            LOGGER.debug(
                "[LIDAR] push received but _active_map_id unknown — dropping %s",
                object_name,
            )
            return

        cloud = getattr(self, "_cloud", None)
        if cloud is None:
            LOGGER.warning(
                "[LIDAR] fetch skipped (no cloud client): %s", object_name
            )
            return

        try:
            url = await self.hass.async_add_executor_job(
                cloud.get_interim_file_url, object_name
            )
        except Exception as ex:
            LOGGER.warning(
                "[LIDAR] get_interim_file_url failed for %s: %s",
                object_name, ex,
            )
            return
        if not url:
            LOGGER.warning(
                "[LIDAR] get_interim_file_url returned None for %s",
                object_name,
            )
            return

        try:
            raw = await self.hass.async_add_executor_job(cloud.get_file, url)
        except Exception as ex:
            LOGGER.warning(
                "[LIDAR] get_file failed for %s: %s", object_name, ex
            )
            return
        if not raw:
            LOGGER.warning(
                "[LIDAR] get_file returned empty for %s", object_name
            )
            return

        archive = self.lidar_archive_for(active_id)

        entry = await self.hass.async_add_executor_job(
            archive.archive, object_name, now_unix, raw
        )
        if entry is None:
            LOGGER.debug(
                "[LIDAR] dedup hit (md5 already archived): %s", object_name
            )
            return

        LOGGER.info(
            "[LIDAR] archived %s (%d bytes) in map %d, total=%d",
            entry.filename, entry.size_bytes, active_id, archive.count,
        )
        # Update archived_lidar_count on the state for the count sensor.
        self.async_set_updated_data(
            dataclasses.replace(
                self.data, archived_lidar_count=archive.count
            )
        )

    async def _do_oss_fetch(self, now_unix: int) -> None:
        """Attempt to download and archive the cloud-summary JSON.

        1. call ``cloud_client.get_interim_file_url(object_name)`` to get a
           signed URL (blocking — executor).
        2. call ``cloud_client.get_file(url)`` to download the raw bytes
           (blocking — executor).
        3. Parse via ``protocol.session_summary.parse_session_summary``.
        4. Archive via ``SessionArchive.archive`` (blocking — executor).
        5. On success: clear pending fields, populate latest_session_*, call
           ``live_map.end_session()``.
        6. On failure: increment ``pending_session_attempt_count``.

        All blocking I/O goes through hass.async_add_executor_job per spec §3.
        """
        object_name = self.data.pending_session_object_name
        if not object_name:
            return

        # Guard: cloud client may not be ready during early boot.
        if not hasattr(self, "_cloud") or self._cloud is None:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: cloud client not ready; "
                "object_name=%r — will retry next tick",
                object_name,
            )
            return

        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: fetching object_name=%r (attempt #%s)",
            object_name,
            (self.data.pending_session_attempt_count or 0) + 1,
        )

        # Increment attempt count and record last_attempt_unix before the fetch
        # so retries are tracked even if the fetch hangs or raises.
        new_count = (self.data.pending_session_attempt_count or 0) + 1
        self.async_set_updated_data(
            dataclasses.replace(
                self.data,
                pending_session_attempt_count=new_count,
                pending_session_last_attempt_unix=now_unix,
            )
        )

        # Step 1: get signed URL (blocking).
        try:
            signed_url: str | None = await self.hass.async_add_executor_job(
                self._cloud.get_interim_file_url, object_name
            )
        except Exception as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: get_interim_file_url raised: %s", ex
            )
            return

        if not signed_url:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: get_interim_file_url returned None "
                "for object_name=%r",
                object_name,
            )
            return

        # Step 2: download raw bytes (blocking).
        try:
            raw_bytes: bytes | None = await self.hass.async_add_executor_job(
                self._cloud.get_file, signed_url
            )
        except Exception as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: get_file raised: %s", ex
            )
            return

        if not raw_bytes:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: get_file returned None for url=%r",
                signed_url,
            )
            return

        # Step 3: parse JSON.
        try:
            raw_dict: dict[str, Any] = json.loads(raw_bytes)
        except (json.JSONDecodeError, ValueError) as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: JSON decode failed: %s — raw[:200]=%r",
                ex,
                raw_bytes[:200],
            )
            return

        # F6.4.1: schema-validate the JSON shape. Each novel key fires
        # [NOVEL_KEY/session_summary] WARNING once per process via the
        # registry's record_key gate.
        for key in _SESSION_SUMMARY_CHECK.diff_keys(raw_dict):
            if self.novel_registry.record_key("session_summary", key, now_unix):
                LOGGER.warning(
                    "%s key=%s — JSON shape drift, parser may need an update",
                    LOG_NOVEL_KEY_SESSION_SUMMARY, key,
                )

        # v1.0.0a54+: inject locally-tracked fields (legs, WiFi samples,
        # telemetry streams, settings_snapshot) into the raw JSON before
        # archiving. Extracted into _inject_live_map_into_raw_dict so the
        # FINALIZE_INCOMPLETE path can reuse the same logic.
        self._inject_live_map_into_raw_dict(raw_dict)

        # Recorder-merge safety net (2026-05-16 spec): fill gaps in the
        # battery/wifi sample arrays from HA's recorder history. Idempotent;
        # any failure leaves the in_progress samples untouched.
        try:
            from ._recorder_merge import merge_recorder_samples

            _start_ts = int(raw_dict.get("start") or 0)
            _end_ts = int(raw_dict.get("end") or 0)
            if _start_ts > 0 and _end_ts > _start_ts:
                _counts = await merge_recorder_samples(
                    self.hass, raw_dict, _start_ts, _end_ts,
                )
                LOGGER.info(
                    "[recorder_merge] OSS-fetch finalize: "
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
                "[recorder_merge] OSS-fetch finalize: merge failed; "
                "using in_progress samples only"
            )

        try:
            summary = _session_summary.parse_session_summary(raw_dict)
        except _session_summary.InvalidSessionSummary as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: parse_session_summary failed: %s", ex
            )
            return

        # Step 4: archive (blocking disk I/O).
        # Stamp the map_id so the replay picker can show [Map N] prefix.
        finalize_map_id = self._resolve_finalize_map_id()
        try:
            archived_entry: ArchivedSession | None = await self.hass.async_add_executor_job(
                self.session_archive.archive, summary, raw_dict, finalize_map_id
            )
        except Exception as ex:
            LOGGER.warning("[F5.6.1] _do_oss_fetch: archive raised: %s", ex)
            return

        LOGGER.warning(
            "[F5.6.1] _do_oss_fetch: archived session md5=%r area=%.1fm² "
            "duration=%dmin (already_exists=%s)",
            summary.md5,
            summary.area_mowed_m2,
            summary.duration_min,
            archived_entry is None,
        )
        # Invalidate the per-map "last-session obstacles" overlay cache
        # for this map, so the next Main-view render picks up the
        # freshly-archived session's obstacles.
        self._last_session_obstacles_by_map.pop(finalize_map_id, None)
        # v1.0.0a50: when md5 dedup hits we silently land on an
        # already-archived entry — picker will not show a new row.
        # Surface object_name + parsed start/end so the cloud's
        # md5-recycling can be diagnosed and (if needed) the dedup
        # rule reworked to use object_name or start_ts instead.
        if archived_entry is None:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: md5 dedup hit — "
                "object_name=%r start_ts=%s end_ts=%s area=%.1f map_area=%s "
                "(picker will NOT show a new row; cloud reused md5)",
                object_name,
                summary.start_ts,
                summary.end_ts,
                summary.area_mowed_m2,
                summary.map_area_m2,
            )

        # Step 5: update MowerState — clear pending, populate latest_session_*,
        # increment archived_session_count, end the live_map session.
        # The in_progress.json file must be removed too; without that, the
        # picker keeps synthesizing a phantom "in progress" entry from disk
        # alongside the freshly-archived row (same bug v1.0.0a25 fixed for
        # the manual Finalize path; v1.0.0a42 closes the auto-finalize hole).
        try:
            await self.hass.async_add_executor_job(
                self.session_archive.delete_in_progress
            )
        except Exception as ex:
            LOGGER.warning(
                "[F5.6.1] _do_oss_fetch: delete_in_progress raised: %s", ex
            )
        self._fire_mowing_ended(
            now_unix=now_unix,
            area_mowed_m2=summary.area_mowed_m2,
            duration_min=summary.duration_min,
            completed=True,
        )
        self.live_map.end_session()
        new_count = self.session_archive.count

        # P3 render-styling: infer dominant mow-stripe direction and record
        # it per-map. Only for ALL_AREAS / ZONE (edge/spot have no stripes).
        # summary.track_segments is in metres; infer_mow_direction expects mm.
        new_direction_map: dict[int, int] = dict(self.data.last_all_area_mow_direction_deg)
        if (
            self.data.action_mode in (ActionMode.ALL_AREAS, ActionMode.ZONE)
            and self._active_map_id is not None
        ):
            track_segs_mm = [
                [(x * 1000.0, y * 1000.0) for x, y in seg]
                for seg in summary.track_segments
            ]
            angle = infer_mow_direction(track_segs_mm)
            if angle is not None:
                new_direction_map[int(self._active_map_id)] = angle
                LOGGER.debug(
                    "[F5.6.1] _do_oss_fetch: inferred mow direction=%d° "
                    "for map_id=%r (action_mode=%s)",
                    angle, self._active_map_id, self.data.action_mode,
                )

        self.async_set_updated_data(
            dataclasses.replace(
                self.data,
                pending_session_object_name=None,
                pending_session_first_event_unix=None,
                pending_session_last_attempt_unix=None,
                pending_session_attempt_count=None,
                latest_session_unix_ts=summary.end_ts,
                latest_session_area_m2=summary.area_mowed_m2,
                latest_session_duration_min=summary.duration_min,
                # v1.0.0a22: pull total lawn area from the session
                # summary's `map_area` field. s2.66 (the MQTT push that
                # also carries this value) fires rarely on g2408, so
                # session-summary is the more reliable source of truth.
                # Only update when the summary has a non-zero map_area
                # (some incomplete entries set it to 0).
                total_lawn_area_m2=(
                    float(summary.map_area_m2)
                    if summary.map_area_m2 else self.data.total_lawn_area_m2
                ),
                archived_session_count=new_count,
                session_started_unix=None,
                session_track_segments=(),
                last_all_area_mow_direction_deg=new_direction_map,
            )
        )

