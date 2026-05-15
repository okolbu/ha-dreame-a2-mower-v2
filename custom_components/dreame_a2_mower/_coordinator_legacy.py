"""Coordinator for the Dreame A2 Mower integration.

Per spec §3 layer 3: owns the MQTT + cloud clients, the typed
MowerState, and the dispatch from inbound MQTT pushes to state
updates. Entities subscribe to coordinator updates and read from
``coordinator.data`` (the MowerState).
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .archive.lidar import LidarArchive
from .archive.session import ArchivedSession, SessionArchive
from .wifi_archive_store import WifiArchiveEntry, WifiArchiveStore
from .cloud_client import DreameA2CloudClient
from .const import (
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
from .inventory.loader import load_inventory
from .live_map.finalize import RETRY_INTERVAL_SECONDS, FinalizeAction
from .live_map.finalize import decide as _finalize_decide
from .live_map.state import LiveMapState
from .mower.actions import ACTION_TABLE, MowerAction
from .mower.property_mapping import PROPERTY_MAPPING, resolve_field
from .mower.state import ChargingStatus, MowerState
from .mower.state_machine import MowerStateMachine
from .mqtt_client import DreameA2MqttClient
from .observability import FreshnessTracker, NovelObservationRegistry
from .observability.schemas import SCHEMA_SESSION_SUMMARY, SchemaCheck
from .protocol import config_s2p51 as _s2p51
from .protocol import heartbeat as _heartbeat
from .protocol import session_summary as _session_summary
from .protocol import telemetry as _telemetry
from .protocol import wheel_bind as _wheel_bind



# Module-level helpers + constants moved to coordinator/_property_apply.py
# (refactor 2026-05-15 — see docs/superpowers/specs/2026-05-15-coordinator-
# decomposition-design.md). Re-imported into this module's namespace so
# the class body's bare-name references resolve unchanged.
from .coordinator._property_apply import (
    _INVENTORY,
    _SESSION_SUMMARY_CHECK,
    _BLOB_SLOTS,
    _SUPPRESSED_SLOTS,
    _SETTINGS_TRIPWIRE_SLOTS,
    S2P2_NOTIFICATION_MAP,
    S2P2_NOVEL_EVENT_TYPE,
    _coerce_blob,
    _apply_s1p1_heartbeat,
    _apply_s1p4_telemetry,
    _project_north_east,
    _apply_s2p51_settings,
    _consumable_pct_remaining,
    _apply_consumables,
    apply_property_to_state,
)

from .coordinator._wifi_archive import _WifiArchiveMixin
from .coordinator._device_sync import _DeviceSyncMixin
from .coordinator._lidar_oss import _LidarOssMixin
from .coordinator._rendering import _RenderingMixin
from .coordinator._session import _SessionMixin
from .coordinator._writes import _WritesMixin
from .coordinator._mqtt_handlers import _MqttHandlersMixin


class DreameA2MowerCoordinator(
    _MqttHandlersMixin,
    _WritesMixin,
    _SessionMixin,
    _RenderingMixin,
    _LidarOssMixin,
    _DeviceSyncMixin,
    _WifiArchiveMixin,
    DataUpdateCoordinator[MowerState],
):
    """Coordinates MQTT + cloud clients and the typed MowerState."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=None,  # push-based; we don't poll
        )
        self.entry = entry
        self._username = entry.data[CONF_USERNAME]
        self._password = entry.data[CONF_PASSWORD]
        self._country = entry.data[CONF_COUNTRY]

        # Initialize empty MowerState — fields fill in as MQTT pushes arrive
        self.data = MowerState()

        # Live session state machine (F5.3.1).
        self.live_map = LiveMapState()
        self._prev_task_state: int | None = None
        # Event-entity refs populated by event.py's async_setup_entry.
        # Coordinator's _fire_lifecycle dispatcher calls these to surface
        # transitions to HA. None until the platform setup completes;
        # _fire_lifecycle race-skips with a DEBUG log when not yet wired.
        self._lifecycle_event: Any = None
        self._alert_event: Any = None
        # Tracks the previous mower_in_dock value for rising/falling edge
        # detection of dock_arrived / dock_departed events. None at
        # startup; explicit `is True` / `is False` comparisons in
        # _on_state_update mean the first push doesn't fire spuriously.
        self._prev_in_dock: bool | None = None
        # Tracks the previous s2p2 / error_code value for notification-event
        # synthesis. Fires dreame_a2_mower_alert events on transitions to
        # known codes (S2P2_NOTIFICATION_MAP). None at startup so the first
        # push doesn't fire spuriously on HA boot.
        self._prev_error_code: int | None = None
        # Stores the most-recent fired notification for sensor.last_notification.
        # Shape: {"event_type": str, "text": str, "code": int, "fired_at": int}
        self._last_notification: dict | None = None

        # Session archive — persists completed sessions to disk (F5.4.1, F5.6.1).
        # <config>/dreame_a2_mower/sessions/ — matches legacy layout.
        sessions_dir = hass.config.path(DOMAIN, "sessions")
        self.session_archive = SessionArchive(Path(sessions_dir))
        # F7.7.1: apply retention from options (if set), else use default.
        opts = getattr(entry, "options", {}) or {}
        session_keep = int(
            opts.get(CONF_SESSION_ARCHIVE_KEEP, DEFAULT_SESSION_ARCHIVE_KEEP)
        )
        if hasattr(self.session_archive, "set_retention"):
            self.session_archive.set_retention(session_keep)

        # F7.2.2: LiDAR archive — persists PCD scans announced via s99p20.
        # Layout: <config>/dreame_a2_mower/lidar/<map_id>/  (per-map subdirs).
        # F7.7.1: retention and max_bytes read from entry.options at startup.
        # T12: per-map archive dict; lazy-init via lidar_archive_for(map_id).
        lidar_dir = hass.config.path(DOMAIN, "lidar")
        self._lidar_archive_root: Path = Path(lidar_dir)
        self._lidar_archive_root.mkdir(parents=True, exist_ok=True)
        self._lidar_archive_retention: int = int(
            opts.get(CONF_LIDAR_ARCHIVE_KEEP, DEFAULT_LIDAR_ARCHIVE_KEEP)
        )
        self._lidar_archive_max_bytes: int = (
            int(opts.get(CONF_LIDAR_ARCHIVE_MAX_MB, DEFAULT_LIDAR_ARCHIVE_MAX_MB))
            * 1024 * 1024
        )
        # dict[int, LidarArchive] — populated lazily by lidar_archive_for().
        self.lidar_archives: dict[int, LidarArchive] = {}
        self._last_lidar_object_name: str | None = None

        # WiFi archive — persists heatmap objects fetched from OSS.
        # Layout: <config>/dreame_a2_mower/wifi_archive/
        # Store is created here; index loaded from disk at startup.
        wifi_archive_dir = Path(hass.config.path(DOMAIN, "wifi_archive"))
        self._wifi_archive_store: WifiArchiveStore = WifiArchiveStore(wifi_archive_dir)
        self._wifi_archive_index: list[WifiArchiveEntry] = self._wifi_archive_store.load_index()

        # Unified cloud state — populated by _refresh_cloud_state every 10 min.
        # All cloud-fetched data (maps, settings, schedule, mow paths, etc.)
        # lives here. Properties below maintain backwards-compat for entities
        # that were written against the previous _cached_* attributes.
        self.cloud_state: Any = None  # CloudState | None — actual import deferred

        # Multi-map cache — populated by _refresh_map.
        self._cached_maps_by_id: dict[int, Any] = {}  # dict[int, MapData]
        # Four independent PNG cache slots, one per render pipeline:
        #   _main_view_png         — active map + live trail (Main view)
        #   _static_map_pngs_by_id — per-map static base + M_PATH (cumulative)
        #   _work_log_png          — picker-selected archived session
        #   _active_map_base_png   — active map base only (no trail, no M_PATH);
        #                            shown as the Work Log camera's empty state
        # Each slot is owned by one render path; no shared mutability.
        self._main_view_png: bytes | None = None
        self._work_log_png: bytes | None = None
        self._active_map_base_png: bytes | None = None
        # Tracks the active map's md5 the last time we rendered
        # _active_map_base_png — used by _render_active_map_base to dedup.
        self._active_map_base_md5: str | None = None
        # Per-map cache of last-session obstacle polygons (cloud-frame metres).
        # Populated lazily on first `_render_main_view` per map_id by reading
        # the most-recent ArchivedSession for that map from disk; invalidated
        # to None whenever a new session is archived so the next render picks
        # up fresh obstacles. Value of `[]` means "loaded, but no obstacles" —
        # distinct from `None` ("not yet loaded"). The renderer treats both
        # the same, but the sentinel avoids re-loading disk on every tick.
        self._last_session_obstacles_by_map: dict[
            int, list[list[tuple[float, float]]]
        ] = {}
        # Single coordinator-wide mutex serializing all chunked-batch
        # cloud writes (SETTINGS / SCHEDULE / AI_HUMAN). Each per-domain
        # helper acquires this around the read-modify-write sequence so
        # two near-simultaneous entity writes can't race on the same blob.
        # Hold time per write is sub-second; cross-blob writes are rare
        # so a single mutex (vs per-blob) keeps reasoning simple.
        self._chunked_write_lock: asyncio.Lock = asyncio.Lock()
        # Debounce timer for tripwire-driven cloud refreshes.
        # When the firmware pushes a "settings-saved" MQTT slot
        # (see _SETTINGS_TRIPWIRE_SLOTS), we schedule a deferred
        # _refresh_cloud_state. Bursts coalesce: each fresh tripwire
        # cancels any pending fire and pushes the deadline back, so
        # one final refresh runs after the burst settles.
        self._cloud_refresh_debounce_handle: asyncio.TimerHandle | None = None
        self._static_map_pngs_by_id: dict[int, bytes] = {}
        self._last_map_md5_by_id: dict[int, str] = {}
        # Active map (from MAPL polling). None until first MAPL response.
        self._active_map_id: int | None = None
        # Cross-map LiDAR archive selection — drives DreameA2LidarSelectedCamera.
        # Tuple of (map_id, filename) — None means "show latest scan from active map".
        self._lidar_render_entry: tuple[int, str] | None = None
        # WiFi archive selection — drives DreameA2WifiSelectedCamera.
        # Tuple of (map_id, object_name) — None means "latest from active map".
        self._wifi_render_entry: tuple[int, str] | None = None
        # Last archive refresh result — updated by refresh_wifi_archive.
        self._wifi_archive_last_refresh: dict = {}
        # Throttle live re-renders to at most one per N seconds; the
        # mower pushes s1.4 every ~5s during a mow which would otherwise
        # cause one PIL render per push. Burst-coalesce via a dirty flag.
        self._live_trail_dirty: bool = False
        self._last_live_render_unix: float = 0.0

        # Dirty flag for in-progress persistence (F5.7.1).
        # Set by _on_state_update after every append_point; cleared by
        # _persist_in_progress after a successful disk write.
        self._live_map_dirty: bool = False

        # Novel-observation registry (F6.2.1).
        # Tracks first-sightings of unknown protocol tokens so the watchdog
        # WARNING fires only once per token per process lifetime.
        self.novel_registry = NovelObservationRegistry()
        # Per-field freshness tracker (F6.6.1).
        # Records the last unix timestamp each MowerState field changed.
        self.freshness = FreshnessTracker()

        # Multi-dimensional state machine — canonical source of behavioural
        # state (activity, location, session). Entities read from
        # state_machine.snapshot().
        self.state_machine = MowerStateMachine()
        self._state_store: Store | None = None  # initialised in _async_update_data
        # Map cache persistence — stores the raw fetch_map dict (JSON-able)
        # so map metadata sensors populate immediately on reload instead of
        # waiting for the first cloud roundtrip. Initialised in
        # _async_update_data alongside _state_store.
        self._maps_cache_store: Store | None = None

    @property
    def sn(self) -> str | None:
        """Hardware serial number — preferred over `entry_id` for stable HA identifiers.

        Two sources, in priority order:
          1. `_cloud.serial_number` — set by `_handle_device_info` if the
             cloud's device-info response carried `sn`. Reliable when the
             device-info call returns the field, which `get_devices()`
             frequently does NOT.
          2. `data.hardware_serial` — set by `_refresh_dev()` from the
             routed-action s2.50 `{m:'g', t:'DEV'}` payload, which
             *always* carries `sn` on g2408. This runs synchronously
             during `async_config_entry_first_refresh`, so it's
             reliably populated by the time the migration retry checks.
        """
        client = self._cloud if hasattr(self, "_cloud") else None
        from_cloud = getattr(client, "serial_number", None) if client is not None else None
        if from_cloud:
            return from_cloud
        data = getattr(self, "data", None)
        return getattr(data, "hardware_serial", None) if data is not None else None

    @property
    def station_bearing_deg(self) -> float | None:
        """Compass bearing (degrees CW from north) of the dock's local X axis.

        User-set via config flow options. ``None`` when unset, in which
        case the N/E projection is skipped (position_north_m /
        position_east_m sensors stay Unknown).

        CFG.DOCK.yaw is unreliable on this firmware (drifts even when the
        dock has not physically moved), so we don't read it from the
        device — this option is the canonical source.
        """
        val = self.entry.options.get(CONF_STATION_BEARING_DEG)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    async def _async_update_data(self) -> MowerState:
        """First-refresh path — auth, device discovery, MQTT subscribe.

        Subsequent refreshes are push-driven via the MQTT callback;
        this method only re-runs if the user manually refreshes the
        integration.
        """
        if not hasattr(self, "_cloud"):
            # Restore the state machine from disk before any new signals arrive.
            if self._state_store is None:
                self._state_store = Store(
                    self.hass,
                    version=1,
                    key=f"dreame_a2_mower_state_{self.entry.entry_id}",
                )
            try:
                await self.state_machine.load_persisted(self._state_store)
            except Exception:
                LOGGER.exception(
                    "state_machine.load_persisted failed; continuing with initial snapshot"
                )

            self._cloud = await self.hass.async_add_executor_job(
                self._init_cloud
            )

            # Restore any in-progress session BEFORE _init_mqtt subscribes
            # to the mower's status topic. If we restored after MQTT, the
            # broker's retained s2p56 message could land between any of the
            # subsequent `await`s, fire begin_session(now_unix), and clobber
            # the disk-persisted legs with the current restart timestamp.
            # See coordinator.py:_restore_in_progress for the full race
            # narrative; pairing this with the `not live_map.is_active()`
            # guard in _on_state_update is the trail-loss-on-restart fix.
            await self._restore_in_progress()

            await self.hass.async_add_executor_job(self._init_mqtt)

            # Periodic cloud-state refresh. The MQTT-driven s6p2 tripwire
            # (see _SETTINGS_TRIPWIRE_SLOTS) catches most app-side saves
            # within ~5 s, but some BT-only settings (obstacleAvoidanceHeight,
            # mowing direction, edge mowing toggles, AI bits) don't push
            # any MQTT signal. The periodic poll is the fallback for those.
            # 2 min gives a tight worst-case latency without hammering the
            # cloud — a full refresh costs ~6 RPCs, so 3 RPC/min average.
            async def _periodic_cloud_state(_now: Any) -> None:
                await self._refresh_cloud_state()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_cloud_state, timedelta(minutes=2)
                )
            )
            await self._refresh_cloud_state()

            # Schedule CFG refresh every 10 minutes; also fire one immediately
            # so blade-life / side-brush-life are populated at startup.
            async def _periodic_cfg(_now: Any) -> None:
                await self._refresh_cfg()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_cfg, timedelta(minutes=10)
                )
            )
            await self._refresh_cfg()

            # Schedule LOCN refresh every 60 seconds; also fire one immediately
            # so GPS position is populated at startup.
            async def _periodic_locn(_now: Any) -> None:
                await self._refresh_locn()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_locn, timedelta(seconds=60)
                )
            )
            await self._refresh_locn()

            # Schedule DEV refresh every 6 hours; also fire one immediately
            # so the hardware serial / firmware version land at startup
            # (the s1p5 fallback path mostly returns 80001).
            async def _periodic_dev(_now: Any) -> None:
                await self._refresh_dev()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_dev, timedelta(hours=6)
                )
            )
            await self._refresh_dev()

            # Schedule NET refresh every hour; also fire one immediately
            # so wifi_ssid / wifi_ip / wifi_rssi_dbm have values at boot
            # (otherwise the RSSI sensor sits Unknown for ~45 s waiting
            # for the first s1p1 heartbeat).
            async def _periodic_net(_now: Any) -> None:
                await self._refresh_net()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_net, timedelta(hours=1)
                )
            )
            await self._refresh_net()

            # Schedule DOCK refresh every 60s; mower-in-dock is the
            # most useful field and benefits from quicker updates so
            # automations can trigger on dock arrival/departure.
            async def _periodic_dock(_now: Any) -> None:
                await self._refresh_dock()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_dock, timedelta(seconds=60)
                )
            )
            await self._refresh_dock()

            # Schedule MIHIS refresh every 10 min; also fire one
            # immediately so the lifetime-totals sensors switch from
            # the local-archive seed to the cloud-authoritative numbers
            # right after HA reload.
            async def _periodic_mihis(_now: Any) -> None:
                await self._refresh_mihis()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_mihis, timedelta(minutes=10)
                )
            )
            await self._refresh_mihis()

            # Schedule MAP refresh every 6 hours; also fire one immediately
            # so the camera entity has a PNG at startup.
            async def _periodic_map(_now: Any) -> None:
                await self._refresh_map()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_map, timedelta(hours=6)
                )
            )
            # Restore the parsed map cache from disk before the first cloud
            # fetch so map-metadata sensors populate immediately on reload.
            # The subsequent _refresh_map will overwrite with fresh data
            # once the cloud responds.
            if self._maps_cache_store is None:
                self._maps_cache_store = Store(
                    self.hass,
                    version=1,
                    key=f"dreame_a2_mower_maps_{self.entry.entry_id}",
                )
            try:
                await self._load_persisted_maps()
            except Exception:
                LOGGER.exception(
                    "_load_persisted_maps failed; continuing with empty cache"
                )
            await self._refresh_map()

            # Seed the WiFi archive picker cache so select.wifi_archive has
            # options immediately (before the user presses any refresh button).
            # Best-effort: failures are non-fatal; the picker stays empty and
            # the user can trigger a refresh manually.
            try:
                await self.refresh_wifi_archive()
            except Exception as _ex:
                LOGGER.debug("Initial WiFi archive fetch failed: %s", _ex)

            # Schedule session-finalize retry every RETRY_INTERVAL_SECONDS (60s).
            # Consults finalize.decide() each tick; dispatches AWAIT_OSS_FETCH /
            # FINALIZE_INCOMPLETE / NOOP as appropriate.
            async def _periodic_session(_now: Any) -> None:
                await self._periodic_session_retry()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
                    _periodic_session,
                    timedelta(seconds=RETRY_INTERVAL_SECONDS),
                )
            )

            # v1.0.0a43: hourly cloud-property poll for slow-changing slots
            # the mower never (or rarely) pushes spontaneously. Today this
            # only targets s6.3 (cloud_connected + wifi_rssi_dbm) so the
            # signal-strength sensor doesn't sit Unknown forever between
            # the mower's sparse pushes. Fails silently on 80001 (the
            # standard g2408 cloud-RPC rejection) — no log spam.
            async def _periodic_slow_poll(_now: Any) -> None:
                await self._poll_slow_properties()

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass, _periodic_slow_poll, timedelta(hours=1)
                )
            )
            await self._poll_slow_properties()

            # Load session archive index from disk (non-blocking via executor).
            await self.hass.async_add_executor_job(self.session_archive.load_index)
            archived_count = self.session_archive.count
            # Re-render the live map now that the archive is available so
            # the last-session obstacle overlay appears immediately. The
            # earlier _refresh_cloud_state / _refresh_cfg passes already
            # rendered _main_view_png but at that point
            # _load_last_session_obstacles short-circuited on the unloaded
            # archive (returning None without caching, per the guard added
            # in v1.0.11a2). Without this explicit re-render the overlay
            # wouldn't appear until the next 10-min cloud refresh or the
            # next live-trail event — observed in v1.0.11a1.
            await self._render_main_view()
            if archived_count:
                # v1.0.0a22 / a23: seed total_lawn_area_m2 from the most
                # recent archived session's map_area_m2 so the user sees
                # a value at boot (s2.66 pushes rarely on g2408). Run
                # list_sessions through the executor — it touches
                # in_progress.json synchronously and would otherwise trip
                # HA's blocking-I/O detector and silently raise. (a22
                # called it from the event loop and the seed never fired.)
                seed_lawn = None
                seed_latest_md5: str | None = None
                seed_latest_unix: int | None = None
                seed_latest_area: float | None = None
                seed_latest_duration: int | None = None
                # v1.0.0a42: seed first_mowing_date from the local
                # archive at boot. mowing_count / total_mowing_time_min
                # / total_mowed_area_m2 are now provided by MIHIS via
                # _apply_cloud_state_to_mower_state (Task 17); the
                # lifetime accumulators for those three were dropped.
                # first_mowing_date has no MIHIS equivalent so it
                # remains archive-sourced here.
                #   - first_mowing_date (unix ts)
                first_ts: int | None = None
                try:
                    sessions = await self.hass.async_add_executor_job(
                        self.session_archive.list_sessions
                    )
                    for s in sorted(sessions, key=lambda x: x.end_ts, reverse=True):
                        if seed_lawn is None and getattr(s, "map_area_m2", 0):
                            seed_lawn = float(s.map_area_m2)
                        # Pick the most-recent NON in-progress entry to seed
                        # Latest session area / duration / time. Without this
                        # seed those entities go Unknown after every HA
                        # reload until the next session finalizes.
                        if (
                            seed_latest_md5 is None
                            and not getattr(s, "still_running", False)
                            and getattr(s, "md5", "")
                        ):
                            seed_latest_md5 = str(s.md5)
                            seed_latest_unix = int(s.end_ts)
                            seed_latest_area = float(s.area_mowed_m2 or 0.0)
                            seed_latest_duration = int(s.duration_min or 0)
                        # Track first non-in-progress session start for
                        # first_mowing_date (no cloud equivalent — keep
                        # local-archive sourcing). MIHIS now provides
                        # mowing_count / total_mowing_time_min /
                        # total_mowed_area_m2 via _apply_cloud_state_to_mower_state
                        # at startup, so the lifetime accumulators were
                        # dropped in Task 17.
                        if not getattr(s, "still_running", False):
                            start_ts = int(getattr(s, "start_ts", 0) or 0)
                            if start_ts > 0 and (first_ts is None or start_ts < first_ts):
                                first_ts = start_ts
                except Exception as _ex:
                    LOGGER.warning(
                        "Could not seed session-summary fields from archive: %s", _ex
                    )
                seed_updates: dict[str, Any] = {
                    "archived_session_count": archived_count,
                }
                if seed_lawn is not None:
                    seed_updates["total_lawn_area_m2"] = seed_lawn
                if seed_latest_md5 is not None:
                    # `seed_latest_md5` is used purely as a "we found a
                    # finalized session" sentinel; the md5 itself is no
                    # longer surfaced (latest_session_md5 was pruned in
                    # F10 — see docs/research/state-machines/orphan-fields.md).
                    seed_updates["latest_session_unix_ts"] = seed_latest_unix
                    seed_updates["latest_session_area_m2"] = seed_latest_area
                    seed_updates["latest_session_duration_min"] = seed_latest_duration
                if first_ts is not None and self.data.first_mowing_date is None:
                    # Field is typed `str | None` and surfaced as a sensor
                    # value. Format as a local-tz YYYY-MM-DD so users see a
                    # date rather than a raw unix timestamp.
                    from datetime import datetime
                    try:
                        seed_updates["first_mowing_date"] = (
                            datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d")
                        )
                    except (OSError, OverflowError, ValueError):
                        pass
                self.data = dataclasses.replace(self.data, **seed_updates)

            # F7.2.2: same pattern for the LiDAR archive.
            # Load index for all existing per-map subdirs so the count
            # sensor populates on first refresh.
            # iterdir() does blocking scandir under the hood — must run in
            # an executor or HA logs a "blocking call inside event loop"
            # warning at every startup.
            def _list_lidar_subdirs() -> list[tuple[int, "Path"]]:
                out: list[tuple[int, "Path"]] = []
                for sub in self._lidar_archive_root.iterdir():
                    if sub.is_dir() and sub.name.isdigit():
                        try:
                            out.append((int(sub.name), sub))
                        except ValueError:
                            pass
                return out
            _lidar_count = 0
            try:
                _subdirs = await self.hass.async_add_executor_job(
                    _list_lidar_subdirs
                )
            except (OSError, FileNotFoundError):
                _subdirs = []
            for _map_id, _sub in _subdirs:
                try:
                    _arch = self.lidar_archive_for(_map_id)
                    await self.hass.async_add_executor_job(_arch.load_index)
                    _lidar_count += _arch.count
                except Exception as _ex:
                    LOGGER.debug(
                        "[LIDAR] startup index load failed for %s: %s", _sub, _ex
                    )
            if _lidar_count:
                self.data = dataclasses.replace(
                    self.data, archived_lidar_count=_lidar_count
                )

            # _restore_in_progress already ran above (before _init_mqtt).

            # Schedule 30-second debounced persist of the in-progress trail.
            # Only writes when live_map is active AND dirty (new point appended).
            async def _periodic_persist(_now: Any) -> None:
                await self._persist_in_progress(_now)

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
                    _periodic_persist,
                    timedelta(seconds=30),
                )
            )

            # Schedule state-machine tick every 10 seconds. Handles HB
            # staleness checks, s2p2=71 disambiguation, and debounced persist.
            @callback
            def _state_machine_tick(_now: Any) -> None:
                import time as _time
                now_unix = int(_time.time())
                try:
                    self.state_machine.tick(now_unix=now_unix)
                except Exception:
                    LOGGER.exception("state_machine.tick failed")
                # Cold-boot telemetry reconciliation. MQTT properties_changed
                # only fires on change, so a mid-session integration restart
                # never receives the start events. Use continuous telemetry
                # (area_mowed + position) to infer the right state.
                try:
                    data = self.data
                    self.state_machine.reconcile_from_telemetry(
                        live_map_active=self.live_map.is_active(),
                        area_mowed_m2=getattr(data, "area_mowed_m2", None),
                        position_x_m=getattr(data, "position_x_m", None),
                        position_y_m=getattr(data, "position_y_m", None),
                        dock_x_mm=getattr(data, "dock_x_mm", None),
                        dock_y_mm=getattr(data, "dock_y_mm", None),
                        now_unix=now_unix,
                    )
                except Exception:
                    LOGGER.exception("state_machine.reconcile_from_telemetry failed")
                # Sync snapshot.charging back to coord.data.charging_status
                # so the charging_status sensor reflects the state machine's
                # inferred state (e.g. battery-rise → charging=True after a
                # reload that missed the explicit s3p2 push).
                try:
                    from .mower.state import ChargingStatus
                    snap_charging = self.state_machine.snapshot().charging
                    inferred = (
                        ChargingStatus.CHARGING if snap_charging
                        else ChargingStatus.NOT_CHARGING
                    )
                    if self.data.charging_status != inferred:
                        self.async_set_updated_data(
                            dataclasses.replace(
                                self.data, charging_status=inferred,
                            )
                        )
                except Exception:
                    LOGGER.exception("charging_status sync failed")
                # Debounced save: only write if dirty and store is ready.
                if self.state_machine.is_dirty() and self._state_store is not None:
                    self.hass.async_create_task(
                        self.state_machine.save_persisted(self._state_store)
                    )

            self.entry.async_on_unload(
                async_track_time_interval(
                    self.hass,
                    _state_machine_tick,
                    timedelta(seconds=10),
                )
            )

        return self.data


    async def _refresh_mapl(self) -> None:
        """Re-poll MAPL only (no full CFG refresh)."""
        if not hasattr(self, "_cloud") or self._cloud is None:
            return
        try:
            mapl_resp = await self.hass.async_add_executor_job(
                self._cloud.fetch_mapl
            )
        except Exception as ex:
            LOGGER.debug("[map] _refresh_mapl raised: %s", ex)
            return
        if isinstance(mapl_resp, dict):
            inner = (mapl_resp.get("ok") or {}).get("d") or mapl_resp.get("ok") or mapl_resp
            self._apply_mapl(inner if isinstance(inner, list) else None)
        elif isinstance(mapl_resp, list):
            # fetch_mapl can return a bare list per Task 7 implementation.
            self._apply_mapl(mapl_resp)

    async def _refresh_cfg(self) -> None:
        """Fetch CFG via routed-action and update MowerState.

        Extracts blade / side-brush wear percentages from CFG.CMS plus all
        other settings fields added in F4.1.1: child lock, volume, language,
        DND, PRE (mowing prefs), WRP (rain protection), LOW (low-speed night),
        BAT (charging config), LIT (LED/headlight config), ATA (anti-theft),
        REC (human presence alert).

        The g2408 CFG dict does not contain cleaning-history keys
        (TC / TT / CN / FCD are not present in the confirmed 24-key
        schema — see docs/research/g2408-protocol.md §6.2 alpha.85 dump).
        Those MowerState fields remain None until a source is identified.

        All blocking I/O runs in the executor per spec §3.
        """
        if not hasattr(self, "_cloud"):
            return

        cfg = await self.hass.async_add_executor_job(self._cloud.fetch_cfg)
        if cfg is None:
            return

        # ---- CMS: per-consumable wear ----
        # Same shape as the s2p51 CONSUMABLES push:
        # [blades_min, cleaning_brush_min, robot_maintenance_min, link_module]
        # Thresholds + slot identity come from protocol/config_s2p51.py so
        # there's a single source of truth between this CFG path and the
        # live CONSUMABLES path. `-1` in any slot means "no timer applies".
        blades_life_pct: float | None = None
        cleaning_brush_life_pct: float | None = None
        robot_maintenance_life_pct: float | None = None
        cms = cfg.get("CMS")
        if isinstance(cms, list) and len(cms) >= 3:
            try:
                blades_life_pct = _consumable_pct_remaining(
                    int(cms[0]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[0]
                )
                cleaning_brush_life_pct = _consumable_pct_remaining(
                    int(cms[1]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[1]
                )
                robot_maintenance_life_pct = _consumable_pct_remaining(
                    int(cms[2]), _s2p51.CONSUMABLE_THRESHOLDS_MIN[2]
                )
            except (TypeError, ValueError, ZeroDivisionError) as ex:
                LOGGER.warning("[CFG] CMS decode error: %s — cms=%r", ex, cms)

        # ---- CLS: child lock ----
        # CFG.CLS = int {0, 1}. Confirmed on g2408 (docs/research §6.2).
        child_lock_enabled: bool | None = None
        cls_raw = cfg.get("CLS")
        if cls_raw is not None:
            try:
                child_lock_enabled = bool(int(cls_raw))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] CLS decode error: %s — cls=%r", ex, cls_raw)

        # ---- VOL: voice volume ----
        # CFG.VOL = int 0..100. Confirmed on g2408.
        volume_pct: int | None = None
        vol_raw = cfg.get("VOL")
        if vol_raw is not None:
            try:
                volume_pct = int(vol_raw)
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] VOL decode error: %s — vol=%r", ex, vol_raw)

        # ---- LANG: language indices ----
        # CFG.LANG = list(2) [text_idx, voice_idx]. Confirmed on g2408.
        # language_code stores a human-readable key like "text=2,voice=7";
        # language_text_idx / language_voice_idx carry the raw indices.
        language_code: str | None = None
        language_text_idx: int | None = None
        language_voice_idx: int | None = None
        lang_raw = cfg.get("LANG")
        if isinstance(lang_raw, list) and len(lang_raw) >= 2:
            try:
                language_text_idx = int(lang_raw[0])
                language_voice_idx = int(lang_raw[1])
                language_code = f"text={language_text_idx},voice={language_voice_idx}"
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] LANG decode error: %s — lang=%r", ex, lang_raw)

        # ---- DND: do-not-disturb ----
        # CFG.DND = list(3) [enabled, start_min, end_min] where start_min and
        # end_min are integer minutes-from-midnight (confirmed via iobroker
        # cross-ref: [0, 1200, 480] = off, 20:00→08:00).
        dnd_enabled: bool | None = None
        dnd_start_min: int | None = None
        dnd_end_min: int | None = None
        dnd_raw = cfg.get("DND")
        if isinstance(dnd_raw, list) and len(dnd_raw) >= 3:
            try:
                dnd_enabled = bool(int(dnd_raw[0]))
                dnd_start_min = int(dnd_raw[1])
                dnd_end_min = int(dnd_raw[2])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] DND decode error: %s — dnd=%r", ex, dnd_raw)

        # ---- PRE: mowing preferences ----
        # On g2408 PRE is list(2) [zone_id, mode] — NOT the full 10-element APK
        # schema (docs/research §6.2 §PRE-schema). Elements 2..9 do not exist on
        # this firmware version; pre_mowing_height_mm and pre_edgemaster come from
        # s6.2 push events instead.
        pre_zone_id: int | None = None
        pre_mowing_efficiency: int | None = None
        pre_mowing_height_mm: int | None = None  # only set if PRE has >=3 elements
        pre_edgemaster: bool | None = None  # only set if PRE has >=9 elements
        pre_raw = cfg.get("PRE")
        if isinstance(pre_raw, list):
            try:
                if len(pre_raw) >= 1:
                    pre_zone_id = int(pre_raw[0])
                if len(pre_raw) >= 2:
                    pre_mowing_efficiency = int(pre_raw[1])
                if len(pre_raw) >= 3:
                    pre_mowing_height_mm = int(pre_raw[2])
                if len(pre_raw) >= 9:
                    pre_edgemaster = bool(pre_raw[8])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] PRE decode error: %s — pre=%r", ex, pre_raw)

        # ---- WRP: rain protection ----
        # CFG.WRP = list(2) [enabled, resume_hours]. Confirmed on g2408 (isolated
        # toggle 2026-04-24). resume_hours=0 → "Don't Mow After Rain" (no auto-resume).
        rain_protection_enabled: bool | None = None
        rain_protection_resume_hours: int | None = None
        wrp_raw = cfg.get("WRP")
        if isinstance(wrp_raw, list) and len(wrp_raw) >= 2:
            try:
                rain_protection_enabled = bool(int(wrp_raw[0]))
                rain_protection_resume_hours = int(wrp_raw[1])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] WRP decode error: %s — wrp=%r", ex, wrp_raw)

        # ---- LOW: low-speed nighttime mode ----
        # CFG.LOW = list(3) [enabled, start_min, end_min]. Confirmed on g2408
        # (live toggle 2026-04-24). Same shape as DND. Example: [1, 1200, 480].
        low_speed_at_night_enabled: bool | None = None
        low_speed_at_night_start_min: int | None = None
        low_speed_at_night_end_min: int | None = None
        low_raw = cfg.get("LOW")
        if isinstance(low_raw, list) and len(low_raw) >= 3:
            try:
                low_speed_at_night_enabled = bool(int(low_raw[0]))
                low_speed_at_night_start_min = int(low_raw[1])
                low_speed_at_night_end_min = int(low_raw[2])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] LOW decode error: %s — low=%r", ex, low_raw)

        # ---- BAT: charging config ----
        # CFG.BAT = list(6) [recharge_pct, resume_pct, unknown_flag,
        #                     custom_charging, start_min, end_min].
        # Confirmed on g2408 (docs/research §6.2). Matches s2.51 CHARGING decoder.
        auto_recharge_battery_pct: int | None = None
        resume_battery_pct: int | None = None
        custom_charging_enabled: bool | None = None
        charging_start_min: int | None = None
        charging_end_min: int | None = None
        bat_raw = cfg.get("BAT")
        if isinstance(bat_raw, list) and len(bat_raw) >= 6:
            try:
                auto_recharge_battery_pct = int(bat_raw[0])
                resume_battery_pct = int(bat_raw[1])
                # bat_raw[2] = unknown_flag (consistently 1; semantic TBD)
                custom_charging_enabled = bool(int(bat_raw[3]))
                charging_start_min = int(bat_raw[4])
                charging_end_min = int(bat_raw[5])
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] BAT decode error: %s — bat=%r", ex, bat_raw)

        # ---- LIT: headlight / LED config ----
        # CFG.LIT = list(8) [enabled, start_min, end_min, standby, working,
        #                     charging, error, unknown].
        # Confirmed on g2408 (docs/research §6.2). Matches s2.51 LED_PERIOD decoder.
        led_period_enabled: bool | None = None
        led_in_standby: bool | None = None
        led_in_working: bool | None = None
        led_in_charging: bool | None = None
        led_in_error: bool | None = None
        lit_raw = cfg.get("LIT")
        if isinstance(lit_raw, list) and len(lit_raw) >= 7:
            try:
                led_period_enabled = bool(int(lit_raw[0]))
                # lit_raw[1] = start_min (charging-schedule; not in MowerState F4)
                # lit_raw[2] = end_min   (charging-schedule; not in MowerState F4)
                led_in_standby = bool(int(lit_raw[3]))
                led_in_working = bool(int(lit_raw[4]))
                led_in_charging = bool(int(lit_raw[5]))
                led_in_error = bool(int(lit_raw[6]))
                # lit_raw[7] = unknown trailing toggle (not yet characterised)
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] LIT decode error: %s — lit=%r", ex, lit_raw)

        # ---- ATA: anti-theft alarm ----
        # CFG.ATA = list(3) [lift_alarm, offmap_alarm, realtime_location].
        # Confirmed on g2408 (all 3 indices individually verified 2026-04-27).
        anti_theft_lift_alarm: bool | None = None
        anti_theft_offmap_alarm: bool | None = None
        anti_theft_realtime_location: bool | None = None
        ata_raw = cfg.get("ATA")
        if isinstance(ata_raw, list) and len(ata_raw) >= 3:
            try:
                anti_theft_lift_alarm = bool(int(ata_raw[0]))
                anti_theft_offmap_alarm = bool(int(ata_raw[1]))
                anti_theft_realtime_location = bool(int(ata_raw[2]))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] ATA decode error: %s — ata=%r", ex, ata_raw)

        # ---- REC: human presence alert ----
        # CFG.REC = list(9) [enabled, sensitivity, standby, mowing, recharge,
        #                     patrol, alert, photo_consent, push_min].
        # Confirmed on g2408 (docs/research §6.2). Matches s2.51
        # HUMAN_PRESENCE_ALERT decoder.
        # REC[7] is `photo_consent` — privacy-policy acceptance for the
        # "Capture Photos of AI-Detected Obstacles" feature (CFG.AOP).
        # See MowerState.photo_consent docstring + binary_sensor.photo_consent.
        human_presence_alert_enabled: bool | None = None
        human_presence_alert_sensitivity: int | None = None
        photo_consent: bool | None = None
        rec_raw = cfg.get("REC")
        if isinstance(rec_raw, list) and len(rec_raw) >= 2:
            try:
                human_presence_alert_enabled = bool(int(rec_raw[0]))
                human_presence_alert_sensitivity = int(rec_raw[1])
                if len(rec_raw) >= 8:
                    photo_consent = bool(int(rec_raw[7]))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] REC decode error: %s — rec=%r", ex, rec_raw)


        # ---- AMBIGUOUS_TOGGLE shape members (single-int CFG keys) ----
        # All four use CFG int {0, 1}. Confirmed 2026-04-30 via toggle tests;
        # these CFG keys were previously read but never plumbed to MowerState.
        def _cfg_bool(name: str) -> bool | None:
            raw = cfg.get(name)
            if raw is None:
                return None
            try:
                return bool(int(raw))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] %s decode error: %s — raw=%r", name, ex, raw)
                return None

        frost_protection_enabled = _cfg_bool("FDP")
        auto_recharge_standby_enabled = _cfg_bool("STUN")
        ai_obstacle_photos_enabled = _cfg_bool("AOP")
        # CFG.PROT mapping: {0: direct, 1: smart}. We store True iff smart.
        navigation_path_smart = _cfg_bool("PROT")

        # ---- MSG_ALERT (Notification Preferences, 4-bool list) ----
        # Slots: [anomaly, error, task, consumables_messages].
        msg_alert_anomaly: bool | None = None
        msg_alert_error: bool | None = None
        msg_alert_task: bool | None = None
        msg_alert_consumables: bool | None = None
        msg_alert_raw = cfg.get("MSG_ALERT")
        if isinstance(msg_alert_raw, list) and len(msg_alert_raw) >= 4:
            try:
                msg_alert_anomaly = bool(int(msg_alert_raw[0]))
                msg_alert_error = bool(int(msg_alert_raw[1]))
                msg_alert_task = bool(int(msg_alert_raw[2]))
                msg_alert_consumables = bool(int(msg_alert_raw[3]))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] MSG_ALERT decode error: %s — raw=%r", ex, msg_alert_raw)

        # ---- VOICE (Voice Prompt Modes, 4-bool list) ----
        # Slots: [regular_notification, work_status, special_status, error_status].
        voice_regular_notification: bool | None = None
        voice_work_status: bool | None = None
        voice_special_status: bool | None = None
        voice_error_status: bool | None = None
        voice_raw = cfg.get("VOICE")
        if isinstance(voice_raw, list) and len(voice_raw) >= 4:
            try:
                voice_regular_notification = bool(int(voice_raw[0]))
                voice_work_status = bool(int(voice_raw[1]))
                voice_special_status = bool(int(voice_raw[2]))
                voice_error_status = bool(int(voice_raw[3]))
            except (TypeError, ValueError) as ex:
                LOGGER.warning("[CFG] VOICE decode error: %s — raw=%r", ex, voice_raw)

        new_state = dataclasses.replace(
            self.data,
            # CMS — wear percentages
            blades_life_pct=blades_life_pct,
            cleaning_brush_life_pct=cleaning_brush_life_pct,
            robot_maintenance_life_pct=robot_maintenance_life_pct,
            # total_mowing_time_min, total_mowed_area_m2, mowing_count,
            # first_mowing_date: not present in g2408 CFG (24-key schema).
            # Leave unchanged (None) until a source is identified.
            # CLS — child lock
            child_lock_enabled=child_lock_enabled,
            # VOL — voice volume
            volume_pct=volume_pct,
            # LANG — language indices
            language_code=language_code,
            language_text_idx=language_text_idx,
            language_voice_idx=language_voice_idx,
            # DND — do-not-disturb (integer minutes-from-midnight on wire)
            dnd_enabled=dnd_enabled,
            dnd_start_min=dnd_start_min,
            dnd_end_min=dnd_end_min,
            # PRE — mowing preferences (g2408: only [0]=zone_id, [1]=mode;
            #        height + edgemaster come from s6.2 push instead)
            pre_zone_id=pre_zone_id,
            pre_mowing_efficiency=pre_mowing_efficiency,
            pre_mowing_height_mm=pre_mowing_height_mm,
            pre_edgemaster=pre_edgemaster,
            # WRP — rain protection
            rain_protection_enabled=rain_protection_enabled,
            rain_protection_resume_hours=rain_protection_resume_hours,
            # LOW — low-speed nighttime
            low_speed_at_night_enabled=low_speed_at_night_enabled,
            low_speed_at_night_start_min=low_speed_at_night_start_min,
            low_speed_at_night_end_min=low_speed_at_night_end_min,
            # BAT — charging config
            auto_recharge_battery_pct=auto_recharge_battery_pct,
            resume_battery_pct=resume_battery_pct,
            custom_charging_enabled=custom_charging_enabled,
            charging_start_min=charging_start_min,
            charging_end_min=charging_end_min,
            # LIT — headlight / LED config
            led_period_enabled=led_period_enabled,
            led_in_standby=led_in_standby,
            led_in_working=led_in_working,
            led_in_charging=led_in_charging,
            led_in_error=led_in_error,
            # ATA — anti-theft alarm
            anti_theft_lift_alarm=anti_theft_lift_alarm,
            anti_theft_offmap_alarm=anti_theft_offmap_alarm,
            anti_theft_realtime_location=anti_theft_realtime_location,
            # REC — human presence alert
            human_presence_alert_enabled=human_presence_alert_enabled,
            human_presence_alert_sensitivity=human_presence_alert_sensitivity,
            photo_consent=photo_consent,
            # AMBIGUOUS_TOGGLE single-int settings
            frost_protection_enabled=frost_protection_enabled,
            auto_recharge_standby_enabled=auto_recharge_standby_enabled,
            ai_obstacle_photos_enabled=ai_obstacle_photos_enabled,
            navigation_path_smart=navigation_path_smart,
            # MSG_ALERT — notification preferences (4 toggles)
            msg_alert_anomaly=msg_alert_anomaly,
            msg_alert_error=msg_alert_error,
            msg_alert_task=msg_alert_task,
            msg_alert_consumables=msg_alert_consumables,
            # VOICE — voice prompt modes (4 toggles)
            voice_regular_notification=voice_regular_notification,
            voice_work_status=voice_work_status,
            voice_special_status=voice_special_status,
            voice_error_status=voice_error_status,
        )
        if new_state != self.data:
            self.async_set_updated_data(new_state)

        # Poll MAPL for active-map detection.
        try:
            mapl_resp = await self.hass.async_add_executor_job(
                self._cloud.fetch_mapl
            )
        except Exception as ex:
            LOGGER.debug("[map] _refresh_cfg: MAPL poll raised: %s", ex)
            mapl_resp = None
        self._apply_mapl(mapl_resp if isinstance(mapl_resp, list) else None)


    async def _refresh_locn(self) -> None:
        """Fetch LOCN and update MowerState.position_lat/lon."""
        if not hasattr(self, "_cloud"):
            return
        locn = await self.hass.async_add_executor_job(self._cloud.fetch_locn)
        if locn is None:
            return
        pos = locn.get("pos") if isinstance(locn, dict) else None
        if not isinstance(pos, list) or len(pos) != 2:
            return
        lon, lat = pos
        if lon == -1 and lat == -1:
            # Sentinel — dock origin not configured. Leave fields as None.
            new_state = dataclasses.replace(self.data, position_lat=None, position_lon=None)
        else:
            new_state = dataclasses.replace(
                self.data, position_lat=float(lat), position_lon=float(lon)
            )
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_mihis(self) -> None:
        """Fetch CFG.MIHIS → authoritative lifetime mowing totals.

        Returns ``{area: m², count: sessions, start: unix_ts, time: minutes}``
        matching the app's Work Logs header. v1.0.0a75 attempted to read
        this from the all-keys CFG dump but MIHIS is a separate
        `getCFG t:'MIHIS'` endpoint, so that path always returned None
        and the local-archive seed was never overridden. Fixed in a79.

        The local-archive aggregation at startup remains as a fallback
        — if the cloud RPC fails for any reason the entities stay on
        the local sums until the next refresh succeeds.
        """
        if not hasattr(self, "_cloud"):
            return
        mihis = await self.hass.async_add_executor_job(self._cloud.fetch_mihis)
        if not isinstance(mihis, dict):
            return

        updates: dict[str, Any] = {}
        try:
            if "area" in mihis:
                updates["total_mowed_area_m2"] = float(mihis["area"])
            if "time" in mihis:
                updates["total_mowing_time_min"] = int(mihis["time"])
            if "count" in mihis:
                updates["mowing_count"] = int(mihis["count"])
            # MIHIS.start is a firmware-hardcoded sentinel (1704038400 =
            # 2023-12-31 00:00:00 UTC) that is identical across every cloud
            # dump regardless of mowing activity. Confirmed against 5 dumps
            # 2026-05-04..06: count/area/time evolved while start stayed
            # constant. It is NOT the user's first mow, so do not surface
            # it as first_mowing_date — the local-archive seed at boot
            # (coordinator.py: archived sessions sweep) provides the real
            # earliest-session date.
        except (TypeError, ValueError) as ex:
            LOGGER.warning("[MIHIS] decode error: %s — raw=%r", ex, mihis)
            return

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_dock(self) -> None:
        """Fetch CFG.DOCK → populate dock-state fields on MowerState.

        DOCK returns ``{dock: {connect_status, in_region, x, y, yaw,
        near_x, near_y, near_yaw, path_connect}}``. We pull the inner
        dict and map each field 1:1 onto MowerState. `mower_in_dock`
        is the only one labelled with semantic meaning; the rest are
        named with the `dock_*` prefix and surfaced for diagnostics.
        """
        if not hasattr(self, "_cloud"):
            return
        dock_outer = await self.hass.async_add_executor_job(self._cloud.fetch_dock)
        if not isinstance(dock_outer, dict):
            return
        dock = dock_outer.get("dock") if isinstance(dock_outer.get("dock"), dict) else dock_outer
        if not isinstance(dock, dict):
            return

        def _i(name: str) -> int | None:
            v = dock.get(name)
            if v is None:
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        connect_status = dock.get("connect_status")
        in_region = dock.get("in_region")

        updates: dict[str, Any] = {}
        # mower_in_dock was removed from MowerState (SM-14); dock location is
        # now owned by the state machine via handle_cloud_poll below.
        if in_region is not None:
            updates["dock_in_lawn_region"] = bool(in_region)
        for src, dst in (
            ("x", "dock_x_mm"),
            ("y", "dock_y_mm"),
            ("yaw", "dock_yaw"),
        ):
            v = _i(src)
            if v is not None:
                updates[dst] = v

        if not updates:
            return

        # Feed the dock dict to the state machine before committing the
        # legacy MowerState update so SM sees the same signal source.
        import time as _time
        try:
            self.state_machine.handle_cloud_poll(
                source="DOCK", payload=dock, now_unix=int(_time.time())
            )
        except Exception:
            LOGGER.exception("state_machine.handle_cloud_poll(DOCK) failed")

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_net(self) -> None:
        """Fetch CFG.NET → populate wifi_ssid / wifi_ip / wifi_rssi_dbm.

        NET returns ``{current: ssid, list: [{ip, rssi, ssid}, …]}``.
        We pull the matching entry from `list` (where `ssid == current`)
        and populate the three fields. The s1p1 byte[17] live RSSI
        overrides this once heartbeats start flowing — but until then
        the sensor would otherwise sit Unknown for ~45 s after HA boot.
        """
        if not hasattr(self, "_cloud"):
            return
        net = await self.hass.async_add_executor_job(self._cloud.fetch_net)
        if not isinstance(net, dict):
            return

        current_ssid = net.get("current")
        ap_list = net.get("list") if isinstance(net.get("list"), list) else []
        match = next(
            (
                ap for ap in ap_list
                if isinstance(ap, dict) and ap.get("ssid") == current_ssid
            ),
            None,
        )

        updates: dict[str, Any] = {}
        if isinstance(current_ssid, str) and current_ssid:
            updates["wifi_ssid"] = current_ssid
        if match is not None:
            ip = match.get("ip")
            rssi = match.get("rssi")
            if isinstance(ip, str) and ip:
                updates["wifi_ip"] = ip
            if isinstance(rssi, int):
                # Only seed the RSSI if the heartbeat hasn't already
                # populated it — avoid overwriting a live value with a
                # potentially stale catalogue entry.
                if self.data.wifi_rssi_dbm is None:
                    updates["wifi_rssi_dbm"] = rssi

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)

    async def _refresh_dev(self) -> None:
        """Fetch DEV {fw, mac, ota, sn} and update MowerState.

        DEV is the authoritative source for hardware_serial — the s1p5
        cloud `get_properties` path is unreliable on g2408 (mostly returns
        80001). Once DEV has populated `hardware_serial` we can drop s1p5
        from the slow-poll list. firmware_version source could also move
        here in a future change; today we leave the cloud-record path
        alone since DEV.fw matched it in the 2026-05-04 dump.

        DEV.ota's semantic is unconfirmed (user has Auto-update Firmware
        OFF in the app but DEV.ota = 1). Provisionally surfaced as
        `ota_capable_raw` while we figure out what it actually represents.
        """
        if not hasattr(self, "_cloud"):
            return
        dev = await self.hass.async_add_executor_job(self._cloud.fetch_dev)
        if not isinstance(dev, dict):
            return

        new_serial = dev.get("sn")
        new_fw = dev.get("fw")
        new_ota = dev.get("ota")

        updates: dict[str, Any] = {}
        if isinstance(new_serial, str) and new_serial:
            updates["hardware_serial"] = new_serial
        if isinstance(new_fw, str) and new_fw:
            updates["firmware_version"] = new_fw
        if new_ota is not None:
            try:
                updates["ota_capable_raw"] = int(new_ota)
            except (TypeError, ValueError):
                pass

        if not updates:
            return

        new_state = dataclasses.replace(self.data, **updates)
        if new_state != self.data:
            self.async_set_updated_data(new_state)
            if "hardware_serial" in updates:
                self._update_device_registry_serial(updates["hardware_serial"])


    async def _poll_slow_properties(self) -> None:
        """One-off pull of slot values the mower rarely pushes.

        Targets:
          - (6, 3): [cloud_connected, rssi_dbm] tuple
          - (1, 5): hardware serial string (only while still unknown — once
            captured it never changes, so we drop it from the param set)

        Failures are swallowed: cloud RPCs against g2408 frequently
        return 80001 ("device unreachable via cloud relay") and that
        is fine; the sensor just stays at whatever value the most
        recent push left it at.
        """
        cloud = getattr(self, "_cloud", None)
        if cloud is None:
            return
        did = getattr(cloud, "device_id", None)
        if not did:
            return
        params: list[dict[str, Any]] = [
            {"did": str(did), "siid": 6, "piid": 3},
        ]
        if getattr(self.data, "hardware_serial", None) is None:
            params.append({"did": str(did), "siid": 1, "piid": 5})
        try:
            response = await self.hass.async_add_executor_job(
                cloud.get_properties, params
            )
        except Exception as ex:
            LOGGER.debug("slow-poll get_properties raised: %s", ex)
            return
        # Log the raw response once at INFO so a future RE pass can see
        # exactly what g2408 returns for siid=6/piid=3 — important for
        # the (likely) 80001 vs (hopeful) success branches. Subsequent
        # ticks fall back to DEBUG to avoid log spam.
        if not getattr(self, "_slow_poll_logged", False):
            LOGGER.info("slow-poll get_properties (siid=6, piid=3) → %r", response)
            self._slow_poll_logged = True
        else:
            LOGGER.debug("slow-poll get_properties (siid=6, piid=3) → %r", response)
        if not isinstance(response, list):
            return
        import time as _time
        now_unix = int(_time.time())
        for entry in response:
            if not isinstance(entry, dict):
                continue
            if entry.get("code") != 0:
                continue
            siid = int(entry.get("siid", 0))
            piid = int(entry.get("piid", 0))
            value = entry.get("value")
            if value is None:
                continue
            # Cold-boot seeding: feed each cloud-fetched property through
            # the state machine so it learns the current task_state /
            # battery / charging even when MQTT never re-pushes them.
            sm = getattr(self, "state_machine", None)
            if sm is not None:
                try:
                    sm.handle_mqtt_property(
                        siid=siid, piid=piid, value=value, now_unix=now_unix,
                    )
                except Exception:
                    LOGGER.exception(
                        "state_machine.handle_mqtt_property failed for s%dp%d",
                        siid, piid,
                    )
            new_state = apply_property_to_state(self.data, siid, piid, value)
            if new_state != self.data:
                # Watch the emergency_stop transition and surface a
                # persistent_notification when it sets / dismiss when it
                # clears. byte[3] bit 7 sets on safety event (lid/lift)
                # and clears ONLY on PIN entry, so this notification
                # mirrors the Dreame app's modal popup exactly.
                self._handle_emergency_stop_transition(
                    self.data.emergency_stop, new_state.emergency_stop,
                )
                self.async_set_updated_data(new_state)
                # Push the hardware serial into the device registry as soon
                # as it lands. DeviceInfo set at entity-init time can't see
                # the value (state is None during construction), so without
                # this nudge the user-facing "Serial Number" field stays
                # empty until the next HA reload.
                if (
                    new_state.hardware_serial is not None
                    and (siid, piid) == (1, 5)
                ):
                    self._update_device_registry_serial(new_state.hardware_serial)






    async def _refresh_cloud_state(self) -> None:
        """Single-shot fetch of the full cloud state.

        Called every 10 min via the periodic timer. Replaces the
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
        from .map_render import render_base_map
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
        from .map_decoder import parse_cloud_maps
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

    async def _refresh_map(self) -> None:
        """Fetch the cloud MAP.* batch, parse all maps, and re-render
        per-map base-map PNGs. Updates `_cached_maps_by_id` and
        `_static_map_pngs_by_id`.

        Per-map md5 dedup: if a map's md5 hasn't changed since the last
        fetch, skip re-rendering that map (unless a live trail is active
        on the active map — trail changes even when the base map hasn't).

        v1.0.0a33: notify listeners when any map's zones/spots change so
        select.zone / select.spot escape "(no map yet)" without waiting
        for the next state push.

        Live-trail re-render path uses _cached_maps_by_id[_active_map_id]
        as the base map.

        All blocking I/O and rendering run in the executor per spec §3.
        """
        if not hasattr(self, "_cloud") or self._cloud is None:
            return

        from .map_decoder import parse_cloud_maps
        from .map_render import render_base_map

        cloud_response = await self.hass.async_add_executor_job(self._cloud.fetch_map)
        if cloud_response is None:
            return

        parsed_by_id = parse_cloud_maps(cloud_response)
        if not parsed_by_id:
            LOGGER.debug("[map] _refresh_map: parse_cloud_maps returned empty")
            return

        # Persist the raw cloud response so the next reload starts with
        # sensors populated. Best-effort; failures are non-fatal.
        if getattr(self, "_maps_cache_store", None) is not None:
            try:
                await self._save_persisted_maps(cloud_response)
            except Exception:
                LOGGER.exception("_save_persisted_maps failed; continuing")

        # v1.0.0a33: detect zones/spots changes across ALL maps before
        # overwriting the cache, so we can fire update_listeners once
        # if any map changed its selectable areas.
        zones_spots_changed = False
        for map_id, map_data in parsed_by_id.items():
            prev_map_data = self._cached_maps_by_id.get(map_id)
            prev_zones = getattr(prev_map_data, "mowing_zones", ()) if prev_map_data else ()
            prev_spots = getattr(prev_map_data, "spot_zones", ()) if prev_map_data else ()
            if (
                prev_map_data is None
                or map_data.mowing_zones != prev_zones
                or map_data.spot_zones != prev_spots
            ):
                zones_spots_changed = True
                break

        # Update the MapData cache with all parsed maps.
        self._cached_maps_by_id = parsed_by_id

        # Render per-map BASE PNGs (no trails) into the per-map cache.
        # The active-map trail overlay is rendered separately into
        # `_main_view_png` by `_render_main_view()`.
        for map_id, map_data in parsed_by_id.items():
            prev_md5 = self._last_map_md5_by_id.get(map_id)
            # `_static_map_pngs_by_id` is the per-map BASE cache (used
            # by Map Selector + Settings & Zones tiles). Always render
            # base-only here; the active-map trail overlay lives in
            # `_main_view_png` via `_render_main_view()`. Mixing the
            # two paints mower trails onto the static map-selector
            # tiles, which is jarring.
            if prev_md5 == map_data.md5:
                LOGGER.debug(
                    "[MAP] map_id=%s md5 unchanged (%s) — skipping re-render",
                    map_id, map_data.md5,
                )
                continue
            png = await self.hass.async_add_executor_job(render_base_map, map_data)
            if png:
                self._static_map_pngs_by_id[map_id] = png
                self._last_map_md5_by_id[map_id] = map_data.md5
            LOGGER.info(
                "[MAP] map_id=%s rendered base map PNG (%d bytes), md5=%s",
                map_id,
                len(png) if png else 0,
                map_data.md5,
            )

        # Notify listeners (camera entity, select entities) if zones/spots
        # changed on any map.
        if zones_spots_changed:
            update_listeners = getattr(self, "async_update_listeners", None)
            if callable(update_listeners):
                update_listeners()

        # Populate _main_view_png so DreameA2MapCamera reads a fresh
        # active-map render after every map fetch.
        await self._render_main_view()

        # Sync HA sub-devices to the updated _cached_maps_by_id.
        self._sync_map_subdevices()














    def _init_cloud(self) -> DreameA2CloudClient:
        """Authenticate with the Dreame cloud and pick up device info."""
        client = DreameA2CloudClient(
            username=self._username,
            password=self._password,
            country=self._country,
        )
        client.login()
        # Discover and pin the g2408 in the cloud device list. Without
        # this _did is None and get_device_info()'s API call returns no
        # data → _host stays None → mqtt_host_port() raises.
        client.select_first_g2408()
        client.get_device_info()  # refreshes _host with OTC info
        host, port = client.mqtt_host_port()
        self._mqtt_host = host
        self._mqtt_port = port
        LOGGER.info(
            "Cloud auth ok; device %s model=%s host=%s",
            client.device_id,
            client.model,
            self._mqtt_host,
        )
        return client

    def _init_mqtt(self) -> None:
        """Open the MQTT connection and subscribe to the mower's status topic."""
        self._mqtt = DreameA2MqttClient()
        self._mqtt.register_callback(self._on_mqtt_message)
        # Raw-MQTT archive intentionally NOT attached here.
        #
        # We empirically confirmed (2026-05-12) that the integration sees
        # exactly the same MQTT stream as the external probe_a2_mqtt.py —
        # same topic, same slots, byte-identical payloads in side-by-side
        # samples. Having both write the same data to disk doubles I/O
        # for no analytic value. The MqttArchive class is kept (see
        # protocol/mqtt_archive.py) and the .attach_archive hook is kept;
        # re-enable here only for short debug windows when probe is off.
        # See docs/research/gps-tracking-todo.md "What we already know
        # NOT to be the path" for the parity check.
        username, password = self._cloud.mqtt_credentials()
        client_id = self._cloud.mqtt_client_id()
        topic = self._cloud.mqtt_topic()
        # MQTT bootstrap diagnostics — v1.0.0a8 originally fired persistent
        # notifications for these to make early-bring-up debugging visible
        # without HA log access. Now that the integration is stable, demoted
        # to DEBUG-level log lines so the notification panel stays clean for
        # actual user-visible events (e.g. emergency_stop). Re-enable as
        # `LOGGER.warning(...)` plus `_pn.create(...)` if you need to
        # diagnose an MQTT-bringup regression on a fresh install.
        LOGGER.debug(
            "MQTT bootstrap: host=%s:%s client_id=%s "
            "username_len=%d password_len=%d topic=%s "
            "did_set=%s uid_set=%s model=%r",
            self._mqtt_host, self._mqtt_port, client_id,
            len(username) if username else 0,
            len(password) if password else 0,
            topic,
            self._cloud._did is not None,
            self._cloud._uid is not None,
            self._cloud._model,
        )

        def _on_first_inbound(topic: str) -> None:
            LOGGER.debug(
                "MQTT first inbound: topic=%r (subscribed=%r)",
                topic, self._cloud.mqtt_topic(),
            )

        def _on_broker_connected() -> None:
            LOGGER.debug("MQTT CONNACK accepted by broker for topic=%s", topic)
        self._mqtt.register_connected_callback(_on_broker_connected)
        self._mqtt._on_first_message = _on_first_inbound
        self._mqtt.connect(
            host=self._mqtt_host,
            port=self._mqtt_port,
            username=username,
            password=password,
            client_id=client_id,
        )
        # subscribe() now caches the topic; the actual paho subscribe
        # fires from _on_connect after CONNACK (v1.0.0a6 fix).
        self._mqtt.subscribe(topic)
        LOGGER.info("Subscribed to %s", topic)




























