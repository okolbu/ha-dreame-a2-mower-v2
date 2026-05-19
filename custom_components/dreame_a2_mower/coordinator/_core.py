"""core mixin — extracted from coordinator.py 2026-05-15.

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


class _CoreMixin:
    """Methods extracted from coordinator.py — see spec for groupings."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        wifi_index: "list[WifiArchiveEntry] | None" = None,
    ) -> None:
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
        # True once we've seen a real task_state_code value from MQTT
        # since boot. Used by the finalize gate to distinguish a
        # genuine "task_state observed as idle/complete" from
        # "MowerState's default None because no MQTT push has landed
        # yet" — without this, a restart inside an MQTT-quiet window
        # combined with `_restore_in_progress`'s prev=0 seed would
        # falsely fire FINALIZE_INCOMPLETE on a still-active session
        # (see 2026-05-15 rain-stop incident).
        self._real_task_state_observed: bool = False
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
        # Store is created here; index is loaded via executor in async_setup_entry
        # (pattern a) and passed as `wifi_index` to avoid a blocking disk read
        # inside __init__.  Falls back to [] when not supplied (should not happen
        # in normal HA startup, but guards test / programmatic construction).
        wifi_archive_dir = Path(hass.config.path(DOMAIN, "wifi_archive"))
        self._wifi_archive_store: WifiArchiveStore = WifiArchiveStore(wifi_archive_dir)
        self._wifi_archive_index: list[WifiArchiveEntry] = (
            wifi_index if wifi_index is not None else []
        )

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
        # No-trail variant of _work_log_png — same map, no trail painted.
        # Used by the replay card as its animation base so the SVG-animated
        # trail doesn't double up on a pre-painted static trail.
        self._work_log_base_png: bytes | None = None
        self._picked_session_summary: dict[str, Any] | None = None
        """Flat attribute dict for sensor.dreame_a2_mower_picked_session.
        Set by render_work_log_session; cleared by the work_log select
        when the placeholder is picked."""
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
        # Decoded wifi-body cache — keyed by object_name.
        # Populated asynchronously by _async_load_wifi_body() which is
        # scheduled via async_create_task in set_wifi_render_entry.
        # The camera's available/async_camera_image reads from here so the
        # disk read never happens on the event loop.
        self._wifi_body_cache: dict[str, Any | None] = {}
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

        # Pending-finalize wait (dock-return capture).
        # Set to an asyncio.Event by _wait_for_dock_return; cleared in its
        # finally block so stale signals from subsequent MQTT pushes are
        # harmless. Task slot reserved for future cancellation support.
        self._pending_finalize_task: "asyncio.Task | None" = None
        self._pending_finalize_done: "asyncio.Event | None" = None
        self._pending_finalize_done_reason: str | None = None

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

            # Ensure the debounce handle from _device_sync (set by tripwire
            # callbacks via loop.call_later) doesn't fire into a torn-down
            # coordinator after entry unload.
            def _cancel_debounce_handle() -> None:
                handle = self._cloud_refresh_debounce_handle
                if handle is not None:
                    handle.cancel()
                    self._cloud_refresh_debounce_handle = None

            self.entry.async_on_unload(_cancel_debounce_handle)

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
                    from ..mower.state import ChargingStatus
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

