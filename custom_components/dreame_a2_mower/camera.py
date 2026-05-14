"""Camera platform — base live map for Dreame A2 Mower."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.camera import Camera
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Register the auth-gated PCD download endpoint exactly once per HA
    # process. Subsequent config-entry reloads hit the same view (the
    # coordinator is looked up per-request).
    if not hass.data.setdefault(f"{DOMAIN}_views_registered", False):
        hass.http.register_view(LidarPcdDownloadView())
        hass.http.register_view(LidarSelectedPcdView())
        hass.http.register_view(MapImageView())
        hass.http.register_view(WorkLogImageView())
        hass.data[f"{DOMAIN}_views_registered"] = True

    # The "active map" follower camera (existing behaviour).
    entities: list[Camera] = [DreameA2MapCamera(coordinator)]
    # One per-map static camera per known map.
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.append(DreameA2PerMapCamera(coordinator, map_id))
    # LiDAR cameras — one per known map (top-down thumbnail + full-res).
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.append(DreameA2LidarTopDownCamera(coordinator, map_id=map_id))
        entities.append(DreameA2LidarTopDownFullCamera(coordinator, map_id=map_id))
    entities.append(DreameA2WorkLogCamera(coordinator))
    entities.append(DreameA2LidarSelectedCamera(coordinator))
    # Single picker-driven WiFi heatmap camera (follows DreameA2WifiViewSelect).
    entities.append(DreameA2WifiSelectedCamera(coordinator))
    # Per-map WiFi heatmap cameras — one per known map (v1.0.10a6+).
    # Renders the newest archive entry whose fingerprint-matcher
    # map_id equals the camera's map_id.
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.append(DreameA2WifiPerMapCamera(coordinator, map_id))

    async_add_entities(entities)


class DreameA2MapCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Live map camera for the Dreame A2 Mower."""

    _attr_has_entity_name = True
    _attr_name = "Map"
    _attr_content_type = "image/png"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "map")
        self._attr_device_info = mower_device_info(coordinator)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the current rendered base-map PNG."""
        rendered = self.coordinator._main_view_png
        return rendered  # may be None on first boot before map is fetched

    @property
    def entity_picture(self) -> str | None:
        """Return our custom MapImageView URL with a content-hash query param.

        HA's default `/api/camera_proxy/` response has **no `Cache-Control`
        header**, leaving caching policy to browsers. Chrome / Firefox are
        conservative; Safari is aggressive — it serves cached responses on
        re-fetch even when the URL's token query param has changed. Verified
        2026-05-05 with a 7-pick A/B test: Chrome refreshed every pick,
        Safari lagged 1 behind plus skipped the first.

        We work around this by routing the map image through a custom
        ``HomeAssistantView`` (``MapImageView``) that explicitly emits
        ``Cache-Control: no-store, max-age=0`` headers. The URL also carries
        a ``?v=<sha1[:12]>`` derived from the cached PNG bytes so each
        render produces a structurally unique URL — defence in depth in case
        a misbehaving cache ignores headers.

        Returns ``None`` when no ``_main_view_png`` is present (the entity
        has nothing to serve yet, e.g. immediately after boot before the
        first map fetch).
        """
        png = self.coordinator._main_view_png
        if not png:
            return None
        import hashlib
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/map.png?v={v}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Surface the cached PNG's hash and the mower-frame ↔ PNG-pixel
        calibration the bundled WebGL LiDAR card uses to texture the
        rendered map onto a quad in 3D space.
        """
        attrs: dict[str, Any] = {}
        png = self.coordinator._main_view_png
        if png:
            import hashlib
            attrs["image_version"] = hashlib.sha1(png).hexdigest()[:12]
        md = self.coordinator._cached_maps_by_id.get(self.coordinator._active_map_id)
        if md is not None:
            try:
                bx2 = float(md.bx2)
                by2 = float(md.by2)
                grid = float(md.pixel_size_mm)
                h = int(md.height_px)
            except (TypeError, ValueError, AttributeError):
                return attrs
            # Renderer formula (`map_render._cloud_to_px`):
            #   px = (bx2 - x_mm) / grid
            #   py = (by2 - y_mm) / grid
            # The renderer then flips the canvas vertically before saving,
            # so the served PNG's y is `(h - 1) - py_pre_flip`.
            #
            # Pick three non-collinear mower-frame mm points; the LiDAR
            # card affine-fits these to recover the transform.
            samples = ((0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0))
            attrs["calibration_points"] = [
                {
                    "mower": {"x": x_mm, "y": y_mm},
                    "map": {
                        "x": (bx2 - x_mm) / grid,
                        "y": (h - 1) - (by2 - y_mm) / grid,
                    },
                }
                for x_mm, y_mm in samples
            ]
        # Multi-map awareness — expose active map id and name.
        active = self.coordinator._active_map_id
        if active is not None:
            current_md = self.coordinator._cached_maps_by_id.get(active)
            attrs["map_id"] = active
            attrs["map_name"] = getattr(current_md, "name", None)
        attrs["available_map_ids"] = sorted(self.coordinator._cached_maps_by_id.keys())
        # Diagnostic: per-map nav_paths point count (helps debug whether
        # the cloud returned `paths` data for each map). Map 2's missing
        # rendered path is likely either (a) zero data from cloud, or
        # (b) renderer didn't draw despite data — this exposes which.
        nav_paths_by_map: dict[int, int] = {}
        for mid, md in self.coordinator._cached_maps_by_id.items():
            paths = getattr(md, "nav_paths", ())
            nav_paths_by_map[mid] = sum(len(p.path) for p in paths) if paths else 0
        attrs["nav_paths_pt_count_by_map"] = nav_paths_by_map
        # CloudState diagnostics — populated when cloud_state is available.
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is not None:
            active = self.coordinator._active_map_id
            if active is not None:
                fnt = cs.forbidden_node_types_by_map.get(active)
                if fnt is not None:
                    attrs["forbidden_node_types"] = fnt
            # Full SETTINGS raw list — for inspection of the dual-level structure.
            attrs["settings_dual_level_diagnostic"] = cs.settings.raw
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        """Rotate the camera's access_token whenever the coordinator
        broadcasts new data, then push the entity state.

        HA's frontend caches the ``/api/camera_proxy/`` URL by access
        token; replay-session re-renders ``_main_view_png`` but the
        token only changes via ``async_update_token`` which is normally
        only invoked on a 5-minute timer. Rotating it here forces an
        immediate cache-bust whenever the underlying image is replaced
        — picker click → new render → new token → frontend re-fetches.

        Note: despite the ``async_`` prefix, ``Camera.async_update_token``
        is a ``@callback`` synchronous method (HA naming convention for
        event-loop-safe, not coroutine). v1.0.0a56 wrapped it in
        ``async_create_task`` and crashed with "a coroutine was expected,
        got None" on every coordinator update. v1.0.0a57 calls it
        directly.
        """
        cur = self.coordinator._main_view_png
        # Rotate access_token whenever the rendered PNG bytes change so
        # the frontend immediately re-fetches the updated image.
        png_changed = cur is not None and cur != getattr(self, "_last_seen_png", None)
        if png_changed:
            self._last_seen_png = cur
            self.async_update_token()
        super()._handle_coordinator_update()


class DreameA2PerMapCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Static base-map snapshot for a single map_id.

    Read-only — no live trail overlay (those follow the active map via
    DreameA2MapCamera). Used by the bundled "Maps" dashboard view to
    show all maps side-by-side.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "map_static"

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, map_id: int
    ) -> None:
        super().__init__(coordinator)
        Camera.__init__(self)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "map")
        map_data = coordinator._cached_maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        self._attr_name = map_name or f"Map {map_id + 1}"
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self.coordinator._static_map_pngs_by_id.get(self._map_id)

    @property
    def entity_picture(self) -> str | None:
        png = self.coordinator._static_map_pngs_by_id.get(self._map_id)
        if not png:
            return None
        import hashlib
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/map.png?map_id={self._map_id}&v={v}"


class DreameA2WorkLogCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """The Work Log camera. Independent of live state — its PNG is
    written ONLY by the work-log picker (select.dreame_a2_mower_work_log).
    Periodic refreshes never touch it.

    Returns None when no log has been picked yet (or the picker is on
    the placeholder), surfacing as "Image not available" in the UI.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "work_log"
    _attr_name = "Work Log"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        Camera.__init__(self)
        self._attr_unique_id = mower_unique_id(coordinator, "work_log")
        self._attr_device_info = mower_device_info(coordinator)

    def _resolve_png(self) -> bytes | None:
        """Pick a PNG for the camera: picked log if any, else active-map clean base.

        When no session is picked (or the user picks the placeholder to
        clear), fall back to the active map's CLEAN base render (no
        trail, no mower icon, no M_PATH) so the empty state shows
        "this is the map your work logs would render on" without
        confusing the user with cumulative mow history.
        """
        png = self.coordinator._work_log_png
        if png:
            return png
        return self.coordinator._active_map_base_png

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return self._resolve_png()

    @property
    def entity_picture(self) -> str | None:
        png = self._resolve_png()
        if not png:
            return None
        import hashlib
        v = hashlib.sha1(png).hexdigest()[:12]
        return f"/api/dreame_a2_mower/work_log.png?v={v}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Rotate the camera's access_token whenever the resolved PNG changes.

        picture-entity cards use `/api/camera_proxy/<entity>?token=<at>` for
        camera entities, ignoring our custom entity_picture URL. The browser
        caches that response by token, so a fresh picker pick (which
        replaces _work_log_png) wouldn't visibly update the card until the
        next ~5-8s poll cycle. Rotating the token here changes the URL
        query param on every PNG-change, busting the cache deterministically.

        Same pattern as DreameA2MapCamera. async_update_token is a
        @callback (synchronous despite the `async_` prefix) - call it
        directly, never via async_create_task.
        """
        cur = self._resolve_png()
        if cur is not None and cur != getattr(self, "_last_seen_png", None):
            self._last_seen_png = cur
            self.async_update_token()
        super()._handle_coordinator_update()


class _LidarCameraBase(CoordinatorEntity[DreameA2MowerCoordinator], Camera):
    """Shared rendering for the top-down LiDAR camera entities.

    Subclasses set ``_resolution`` to the desired (width, height) tuple.
    Each instance is bound to a specific ``map_id`` and reads the latest
    PCD bytes from ``coordinator.lidar_archive_for(map_id)``, parses, and
    renders to PNG. Returns ``None`` when no scan is archived, the archive
    is unavailable, or the on-disk file is missing.
    """

    _attr_has_entity_name = True
    _attr_content_type = "image/png"
    _resolution: tuple[int, int] = (512, 512)

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._map_id = map_id

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        from .protocol.pcd import parse_pcd
        from .protocol.pcd_render import render_top_down

        archive = self.coordinator.lidar_archive_for(self._map_id)
        if archive is None:
            return None
        latest = await self.hass.async_add_executor_job(archive.latest)
        if latest is None:
            return None
        pcd_path = archive.root / latest.filename
        try:
            pcd_bytes = await self.hass.async_add_executor_job(
                pcd_path.read_bytes
            )
        except (FileNotFoundError, OSError):
            return None
        try:
            cloud = await self.hass.async_add_executor_job(parse_pcd, pcd_bytes)
        except Exception:
            return None
        w, h = self._resolution
        # 45° tilt — bird's-eye view is far more readable than pure
        # top-down for this scene; matches legacy default.
        return await self.hass.async_add_executor_job(
            render_top_down, cloud, w, h, 8, (0, 0, 0), 45.0,
        )


class DreameA2LidarTopDownCamera(_LidarCameraBase):
    """Dashboard thumbnail (512×512) — fast, low-memory. One per map."""

    _attr_translation_key = "lidar_top_down"
    _resolution = (512, 512)

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "lidar_top_down")
        self._attr_device_info = map_device_info(coordinator, map_id, None)
        maps_by_id = getattr(coordinator, "_cached_maps_by_id", {})
        map_obj = maps_by_id.get(map_id)
        map_name = getattr(map_obj, "name", None) or f"Map {map_id + 1}"
        self._attr_name = f"{map_name} LiDAR (top-down)"


class DreameA2LidarTopDownFullCamera(_LidarCameraBase):
    """Full-resolution popout (1024×1024). One per map."""

    _attr_translation_key = "lidar_top_down_full"
    _resolution = (1024, 1024)

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "lidar_top_down_full")
        self._attr_device_info = map_device_info(coordinator, map_id, None)
        maps_by_id = getattr(coordinator, "_cached_maps_by_id", {})
        map_obj = maps_by_id.get(map_id)
        map_name = getattr(map_obj, "name", None) or f"Map {map_id + 1}"
        self._attr_name = f"{map_name} LiDAR (full resolution)"


class DreameA2LidarSelectedCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Cross-map LiDAR camera — renders whichever scan the
    DreameA2LidarArchiveSelect entity has selected.

    Falls back to the active map's latest scan when nothing is selected
    (``_lidar_render_entry`` is None).
    """

    _attr_has_entity_name = True
    _attr_name = "LiDAR selected scan"
    _attr_content_type = "image/png"
    _attr_translation_key = "lidar_selected"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "lidar_selected")
        self._attr_device_info = mower_device_info(coordinator)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        from .protocol.pcd import parse_pcd
        from .protocol.pcd_render import render_top_down

        render = self.coordinator._lidar_render_entry
        if render is None:
            # Fall back to active-map latest.
            active = self.coordinator._active_map_id
            if active is None:
                return None
            archive = self.coordinator.lidar_archive_for(active)
            if archive is None:
                return None
            latest = await self.hass.async_add_executor_job(archive.latest)
            if latest is None:
                return None
            pcd_path = archive.root / latest.filename
        else:
            map_id, filename = render
            archive = self.coordinator.lidar_archive_for(map_id)
            if archive is None:
                return None
            pcd_path = archive.root / filename

        try:
            pcd_bytes = await self.hass.async_add_executor_job(
                pcd_path.read_bytes
            )
        except (FileNotFoundError, OSError):
            return None
        try:
            cloud = await self.hass.async_add_executor_job(parse_pcd, pcd_bytes)
        except Exception:
            return None
        return await self.hass.async_add_executor_job(
            render_top_down, cloud, 512, 512, 8, (0, 0, 0), 45.0,
        )

    @property
    def entity_picture(self) -> str | None:
        """Return a cache-busting URL for the selected LiDAR scan.

        Uses a hash of the render-entry state to produce a unique URL
        on each selection change, preventing browser cache stale renders.
        """
        import hashlib
        render = self.coordinator._lidar_render_entry
        if render is not None:
            v = hashlib.sha1(f"{render[0]}:{render[1]}".encode()).hexdigest()[:12]
        else:
            active = self.coordinator._active_map_id
            if active is None:
                return None
            v = hashlib.sha1(f"active:{active}".encode()).hexdigest()[:12]
        return f"/api/dreame_a2_mower/lidar_selected.png?v={v}"

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        """Rotate the camera's access_token whenever the selected scan changes."""
        render = self.coordinator._lidar_render_entry
        if render != getattr(self, "_last_seen_render", object()):
            self._last_seen_render = render
            self.async_update_token()
        super()._handle_coordinator_update()


class DreameA2WifiSelectedCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Renders whichever WiFi heatmap the archive picker selects.

    Driven by ``select.dreame_a2_mower_wifi_archive`` (DreameA2WifiArchiveSelect)
    via ``coordinator._wifi_render_entry``.  Body is loaded on demand from
    ``coordinator._wifi_archive_store``.

    The camera key ``wifi_heatmap_selected`` in translations corresponds to
    entity_id ``camera.dreame_a2_mower_wifi_heatmap_selected``.

    Flip toggles are read at render time from:
        ``input_boolean.dreame_a2_mower_wifi_flip_x``
        ``input_boolean.dreame_a2_mower_wifi_flip_y``
    State changes on those entities bust the entity-picture cache automatically.
    """

    _FLIP_X_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_x"
    _FLIP_Y_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_y"

    _attr_has_entity_name = True
    _attr_name = "WiFi heatmap (selected)"
    _attr_content_type = "image/png"
    _attr_translation_key = "wifi_heatmap_selected"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "wifi_selected")
        self._attr_device_info = mower_device_info(coordinator)

    def _resolve_decoded(self) -> dict | None:
        """Return decoded wifi map body for the selected entry.

        Reads from coordinator._wifi_archive_store. Returns None when no
        entry is selected (placeholder shown in picker).
        """
        render = self.coordinator._wifi_render_entry
        if render is None:
            return None
        _map_id, obj_name = render
        if not obj_name:
            return None
        store = getattr(self.coordinator, "_wifi_archive_store", None)
        if store is None:
            return None
        return store.load_body(obj_name)

    @property
    def available(self) -> bool:
        return self._resolve_decoded() is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        flip_x = (
            self.hass is not None
            and self.hass.states.is_state(self._FLIP_X_ENTITY, "on")
        )
        flip_y = (
            self.hass is not None
            and self.hass.states.is_state(self._FLIP_Y_ENTITY, "on")
        )
        from .wifi_map_render import render_wifi_map_png
        return await self.hass.async_add_executor_job(
            lambda: render_wifi_map_png(decoded, flip_x=flip_x, flip_y=flip_y)
        )

    @property
    def entity_picture(self) -> str | None:
        """Cache-bust URL based on selected entry + data hash."""
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        import hashlib
        render = self.coordinator._wifi_render_entry
        if render is not None:
            key = f"{render[0]}:{render[1]}"
        else:
            active = self.coordinator._active_map_id
            key = f"active:{active}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        base = super().entity_picture
        if base is None:
            return None
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}v={h}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to flip toggle state changes to bust the image cache."""
        await super().async_added_to_hass()
        from homeassistant.helpers.event import async_track_state_change_event

        @callback
        def _flip_changed(_event) -> None:
            self.async_update_token()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._FLIP_X_ENTITY, self._FLIP_Y_ENTITY],
                _flip_changed,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        """Rotate the camera's access_token only when the selection changes.

        The decoded body is freshly loaded from disk on every call, so its
        object id() is meaningless — keying on it would rotate the token
        on every coordinator update.
        """
        render = self.coordinator._wifi_render_entry
        if render != getattr(self, "_last_seen_key", object()):
            self._last_seen_key = render
            self.async_update_token()
        super()._handle_coordinator_update()


class DreameA2WifiPerMapCamera(
    CoordinatorEntity[DreameA2MowerCoordinator], Camera
):
    """Per-map WiFi heatmap camera (v1.0.10a6+).

    Renders the *newest* archive entry whose tagged ``map_id`` matches
    this camera's ``_map_id`` — i.e. one camera per logical map. The
    matching is driven by the fingerprint correlator
    (``wifi_match.match_heatmap_to_session``), with the
    geometry-inference path still serving as fallback for entries the
    fingerprint matcher cannot score.

    Unavailable while no tagged entry exists for this map (e.g. a
    brand-new map the cloud hasn't generated a heatmap for yet).
    """

    _attr_has_entity_name = True
    _attr_content_type = "image/png"
    _attr_translation_key = "wifi_heatmap_per_map"

    _FLIP_X_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_x"
    _FLIP_Y_ENTITY = "input_boolean.dreame_a2_mower_wifi_flip_y"

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, map_id: int
    ) -> None:
        super().__init__(coordinator)
        Camera.__init__(self)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(
            coordinator, map_id, "wifi_heatmap"
        )
        map_data = coordinator._cached_maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        self._attr_name = "WiFi heatmap"
        self._attr_device_info = map_device_info(
            coordinator, map_id, name=map_name
        )

    def _resolve_entry(self):
        """Newest archive entry tagged with this camera's map_id, or None."""
        index = getattr(self.coordinator, "_wifi_archive_index", None) or []
        matches = [e for e in index if int(getattr(e, "map_id", -1)) == self._map_id]
        if not matches:
            return None
        matches.sort(key=lambda e: int(e.unix_ts), reverse=True)
        return matches[0]

    def _resolve_decoded(self) -> dict | None:
        entry = self._resolve_entry()
        if entry is None:
            return None
        store = getattr(self.coordinator, "_wifi_archive_store", None)
        if store is None:
            return None
        return store.load_body(entry.object_name)

    @property
    def available(self) -> bool:
        return self._resolve_entry() is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        flip_x = (
            self.hass is not None
            and self.hass.states.is_state(self._FLIP_X_ENTITY, "on")
        )
        flip_y = (
            self.hass is not None
            and self.hass.states.is_state(self._FLIP_Y_ENTITY, "on")
        )
        from .wifi_map_render import render_wifi_map_png
        return await self.hass.async_add_executor_job(
            lambda: render_wifi_map_png(decoded, flip_x=flip_x, flip_y=flip_y)
        )

    @property
    def entity_picture(self) -> str | None:
        entry = self._resolve_entry()
        if entry is None:
            return None
        import hashlib
        key = f"{self._map_id}:{entry.object_name}:{entry.unix_ts}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        base = super().entity_picture
        if base is None:
            return None
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}v={h}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to flip toggle state changes to bust the image cache."""
        await super().async_added_to_hass()
        from homeassistant.helpers.event import async_track_state_change_event

        @callback
        def _flip_changed(_event) -> None:
            self.async_update_token()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._FLIP_X_ENTITY, self._FLIP_Y_ENTITY],
                _flip_changed,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        entry = self._resolve_entry()
        key = entry.object_name if entry is not None else None
        if key != getattr(self, "_last_seen_key", object()):
            self._last_seen_key = key
            self.async_update_token()
        super()._handle_coordinator_update()


class MapImageView(HomeAssistantView):
    """HTTP endpoint that serves the live / replay map PNG with explicit
    no-cache headers.

    GET ``/api/dreame_a2_mower/map.png`` (public — see Auth note below).

    This exists to work around Safari's aggressive image caching. HA's
    default ``/api/camera_proxy/`` view emits **no** ``Cache-Control``
    header, leaving caching policy to the browser. Chrome and Firefox are
    conservative and refetch when the URL's query string changes; Safari
    is sticky and serves the cached response anyway. By routing the map
    image through our own view we can emit ``Cache-Control: no-store,
    max-age=0`` and force every fetch to be a fresh round-trip.

    The coordinator is looked up from ``hass.data`` per-request, so
    config-entry reloads are picked up without re-registering the view.

    Auth: ``requires_auth = False``. The bundled dashboard's replay-map
    card uses a markdown ``<img>`` whose src points here; HA's frontend
    only auto-signs URLs surfaced via ``entity_picture`` on cards that
    consume it (picture-glance, etc.), and the markdown card does not.
    A plain ``<img>`` request carries no Authorization header so an
    auth-required view returns 401. The map PNG is a top-down render of
    the lawn — there's no PII. If your HA is internet-exposed and you
    don't want strangers fetching this, gate access at the reverse
    proxy / frontend level. (LiDAR PCD downloads remain auth-required.)
    """

    url = "/api/dreame_a2_mower/map.png"
    name = "api:dreame_a2_mower:map"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        coordinator = None
        for cand in entries.values():
            coordinator = cand
            break
        if coordinator is None:
            return web.Response(status=404, text="No mower coordinator")

        map_id_raw = request.query.get("map_id")
        if map_id_raw is not None:
            try:
                map_id = int(map_id_raw)
            except (TypeError, ValueError):
                return web.Response(status=400, text="Bad map_id")
            png = coordinator._static_map_pngs_by_id.get(map_id)
        else:
            # Active-map (Main view) PNG.
            png = coordinator._main_view_png

        if not png:
            return web.Response(status=404, text="No map rendered yet")

        return web.Response(
            body=png,
            content_type="image/png",
            headers={
                # `no-store` is the strongest cache-bypass directive — tells
                # browsers (and intermediaries) that no version of the
                # response is stored anywhere. `max-age=0` is belt-and-braces
                # for User-Agents that ignore `no-store`.
                "Cache-Control": "no-store, max-age=0",
                # Some Safari builds also respect Pragma:no-cache for
                # legacy HTTP/1.0 cache stacks.
                "Pragma": "no-cache",
            },
        )


class WorkLogImageView(HomeAssistantView):
    """HTTP endpoint serving the Work Log camera's PNG with no-cache headers."""

    url = "/api/dreame_a2_mower/work_log.png"
    name = "api:dreame_a2_mower:work_log"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        coordinator = None
        for cand in entries.values():
            coordinator = cand
            break
        if coordinator is None:
            return web.Response(status=404, text="No mower coordinator")
        # Fallback to active-map CLEAN base when no log is picked
        # (mirrors DreameA2WorkLogCamera._resolve_png) so the dashboard
        # card never shows a broken image just because the picker is on
        # placeholder. Uses _active_map_base_png (no trail, no M_PATH)
        # rather than _static_map_pngs_by_id (which has M_PATH).
        png = coordinator._work_log_png or coordinator._active_map_base_png
        if not png:
            return web.Response(status=404, text="No work log rendered yet")
        return web.Response(
            body=png,
            content_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )


class LidarSelectedPcdView(HomeAssistantView):
    """Serve the PCD bytes of the currently picker-selected LiDAR scan.

    Routed at /api/dreame_a2_mower/lidar/selected.pcd. The
    ``select.dreame_a2_mower_lidar_archive`` entity drives which scan is
    served via the coordinator's ``_lidar_render_entry`` field.

    Falls back to the active map's latest scan when nothing is explicitly
    selected.
    """

    url = "/api/dreame_a2_mower/lidar/selected.pcd"
    name = "api:dreame_a2_mower:lidar_selected_pcd"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        domain_data = hass.data.get(DOMAIN, {})
        if not domain_data:
            return web.Response(status=503, text="Integration not loaded")
        coord = next(iter(domain_data.values()))
        render = coord._lidar_render_entry
        if render is None:
            # No selection — fall back to active map's latest.
            active = coord._active_map_id
            if active is None:
                return web.Response(status=404, text="No selection")
            archive = coord.lidar_archive_for(active)
            if archive is None:
                return web.Response(status=404, text="No archive")
            latest = await hass.async_add_executor_job(archive.latest)
            if latest is None:
                return web.Response(status=404, text="Archive empty")
            pcd_path = archive.root / latest.filename
        else:
            map_id, filename = render
            archive = coord.lidar_archive_for(map_id)
            if archive is None:
                return web.Response(status=404, text="No archive")
            pcd_path = archive.root / filename
        try:
            pcd_bytes = await hass.async_add_executor_job(pcd_path.read_bytes)
        except (FileNotFoundError, OSError):
            return web.Response(status=404, text="File missing")
        return web.Response(
            body=pcd_bytes,
            content_type="application/octet-stream",
            headers={"Cache-Control": "no-cache"},
        )


class LidarPcdDownloadView(HomeAssistantView):
    """HTTP endpoint that serves the most recent archived ``.pcd`` blob for a map.

    GET ``/api/dreame_a2_mower/lidar/{map_id}/latest.pcd`` (auth required).

    The coordinator is looked up from ``hass.data`` on each request so
    a config-entry reload is picked up without re-registering the view.
    Spec §5.9: auth required (creds discipline).

    Returns 404 with a brief explanation when:
      - ``map_id`` is not a valid integer,
      - no coordinator is registered yet,
      - the coordinator has no archive for that map_id,
      - the archive has no entries,
      - the on-disk .pcd file referenced by index.json is missing.
    """

    url = "/api/dreame_a2_mower/lidar/{map_id}/latest.pcd"
    name = "api:dreame_a2_mower:lidar_latest"
    requires_auth = True

    async def get(self, request: web.Request, map_id: str) -> web.StreamResponse:
        try:
            mid = int(map_id)
        except (ValueError, TypeError):
            return web.Response(status=404, text="Invalid map_id")
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        archive = None
        for coordinator in entries.values():
            cand = coordinator.lidar_archive_for(mid)
            if cand is not None:
                archive = cand
                break
        if archive is None:
            return web.Response(status=404, text="LiDAR archive not available")
        latest = await hass.async_add_executor_job(archive.latest)
        if latest is None:
            return web.Response(status=404, text="No LiDAR scans archived yet")
        path = archive.root / latest.filename
        if not path.is_file():
            return web.Response(status=404, text="Archived scan file missing")
        resp = web.FileResponse(path=path)
        resp.headers["Content-Type"] = "application/octet-stream"
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="{latest.filename}"'
        )
        return resp
