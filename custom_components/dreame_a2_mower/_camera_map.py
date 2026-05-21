"""Map camera entities — live map, per-map static, and work-log."""
from __future__ import annotations

from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .coordinator import DreameA2MowerCoordinator


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
        md = self.coordinator.cloud_state.maps_by_id.get(self.coordinator._active_map_id)
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
            current_md = self.coordinator.cloud_state.maps_by_id.get(active)
            attrs["map_id"] = active
            attrs["map_name"] = getattr(current_md, "name", None)
        attrs["available_map_ids"] = sorted(self.coordinator.cloud_state.maps_by_id.keys())
        # Diagnostic: per-map nav_paths point count (helps debug whether
        # the cloud returned `paths` data for each map). Map 2's missing
        # rendered path is likely either (a) zero data from cloud, or
        # (b) renderer didn't draw despite data — this exposes which.
        nav_paths_by_map: dict[int, int] = {}
        for mid, md in self.coordinator.cloud_state.maps_by_id.items():
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
        map_data = coordinator.cloud_state.maps_by_id.get(map_id)
        map_name = getattr(map_data, "name", None) if map_data is not None else None
        # has_entity_name=True; device_name ("Map N+1" or the map's user-named
        # label) is prepended automatically. Setting _attr_name to a separate
        # value here on top of the device name produced the doubled
        # friendly_name "Map 1 Map 1" (verified 2026-05-14 via /api/states).
        self._attr_name = "Base"
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
