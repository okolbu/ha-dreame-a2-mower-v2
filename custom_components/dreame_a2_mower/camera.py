"""Camera platform — base live map for Dreame A2 Mower."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.camera import Camera

_LOGGER = logging.getLogger(__name__)
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        DreameA2MapCamera(coordinator),
        DreameA2LidarTopDownCamera(coordinator),
        DreameA2LidarTopDownFullCamera(coordinator),
    ])
    # Register the auth-gated PCD download endpoint exactly once per HA
    # process. Subsequent config-entry reloads hit the same view (the
    # coordinator is looked up per-request).
    if not getattr(hass, "_dreame_a2_lidar_view_registered", False):
        hass.http.register_view(LidarPcdDownloadView())
        hass.http.register_view(MapImageView())
        hass._dreame_a2_lidar_view_registered = True


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
        self._attr_unique_id = f"{coordinator.entry.entry_id}_map"
        client = coordinator._cloud if hasattr(coordinator, "_cloud") else None
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the current rendered base-map PNG."""
        rendered = self.coordinator.cached_map_png
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

        Returns ``None`` when no ``cached_map_png`` is present (the entity
        has nothing to serve yet, e.g. immediately after boot before the
        first map fetch).
        """
        png = self.coordinator.cached_map_png
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
        png = self.coordinator.cached_map_png
        if png:
            import hashlib
            attrs["image_version"] = hashlib.sha1(png).hexdigest()[:12]
        md = getattr(self.coordinator, "_cached_map_data", None)
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
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:  # type: ignore[override]
        """Rotate the camera's access_token whenever the coordinator
        broadcasts new data, then push the entity state.

        HA's frontend caches the ``/api/camera_proxy/`` URL by access
        token; replay-session re-renders ``cached_map_png`` but the
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
        cur = self.coordinator.cached_map_png
        # 2026-05-05: rotate the access_token whenever EITHER the rendered
        # PNG bytes change OR the coordinator's replay counter ticks. The
        # byte-equality check alone misses two sequential replays of the
        # same archive (or visually-identical archives) — the frontend
        # then serves the cached prior image. Replay counter ensures
        # every picker tap produces a fresh URL.
        replay_n = getattr(self.coordinator, "_replay_counter", 0)
        last_replay_n = getattr(self, "_last_replay_n", 0)
        png_changed = cur is not None and cur != getattr(self, "_last_seen_png", None)
        replay_changed = replay_n != last_replay_n
        if png_changed or replay_changed:
            self._last_seen_png = cur
            self._last_replay_n = replay_n
            self.async_update_token()
        super()._handle_coordinator_update()


class _LidarCameraBase(CoordinatorEntity[DreameA2MowerCoordinator], Camera):
    """Shared rendering for the top-down LiDAR camera entities.

    Subclasses set ``_resolution`` to the desired (width, height) tuple.
    Reads the latest PCD bytes from ``coordinator.lidar_archive``,
    parses, and renders to PNG. Returns ``None`` when no scan is
    archived, the archive is unavailable, or the on-disk file is
    missing.
    """

    _attr_has_entity_name = True
    _attr_content_type = "image/png"
    _resolution: tuple[int, int] = (512, 512)

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        CoordinatorEntity.__init__(self, coordinator)
        client = getattr(coordinator, "_cloud", None)
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        from .protocol.pcd import parse_pcd
        from .protocol.pcd_render import render_top_down

        archive = getattr(self.coordinator, "lidar_archive", None)
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
        except Exception:  # noqa: BLE001
            return None
        w, h = self._resolution
        # 45° tilt — bird's-eye view is far more readable than pure
        # top-down for this scene; matches legacy default.
        return await self.hass.async_add_executor_job(
            render_top_down, cloud, w, h, 8, (0, 0, 0), 45.0,
        )


class DreameA2LidarTopDownCamera(_LidarCameraBase):
    """Dashboard thumbnail (512×512) — fast, low-memory."""

    _attr_translation_key = "lidar_top_down"
    _resolution = (512, 512)

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_lidar_top_down"
        )


class DreameA2LidarTopDownFullCamera(_LidarCameraBase):
    """Full-resolution popout (1024×1024)."""

    _attr_translation_key = "lidar_top_down_full"
    _resolution = (1024, 1024)

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_lidar_top_down_full"
        )


class MapImageView(HomeAssistantView):
    """HTTP endpoint that serves the live / replay map PNG with explicit
    no-cache headers.

    GET ``/api/dreame_a2_mower/map.png`` (auth required).

    This exists to work around Safari's aggressive image caching. HA's
    default ``/api/camera_proxy/`` view emits **no** ``Cache-Control``
    header, leaving caching policy to the browser. Chrome and Firefox are
    conservative and refetch when the URL's query string changes; Safari
    is sticky and serves the cached response anyway. By routing the map
    image through our own view we can emit ``Cache-Control: no-store,
    max-age=0`` and force every fetch to be a fresh round-trip.

    The coordinator is looked up from ``hass.data`` per-request, so
    config-entry reloads are picked up without re-registering the view.

    Auth: HA's standard authenticated-request flow (LLAT or
    signed-path token), inherited from ``HomeAssistantView`` defaults.
    """

    url = "/api/dreame_a2_mower/map.png"
    name = "api:dreame_a2_mower:map"
    requires_auth = True

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        coordinator = None
        for cand in entries.values():
            if getattr(cand, "cached_map_png", None):
                coordinator = cand
                break
        if coordinator is None or coordinator.cached_map_png is None:
            return web.Response(status=404, text="No map rendered yet")

        # Side-effect: if the browser fetched the URL containing the
        # version hash we last wrote into `_replay_expected_v` (set by
        # `coordinator.replay_session()` on every pick), the loading
        # banner can clear immediately — a real browser has now SEEN
        # the new image. Avoids the 10 s fallback timer leaving the
        # banner up after the image is already on screen.
        v = request.query.get("v", "")
        if v and getattr(coordinator, "_replay_expected_v", None) == v:
            coordinator._replay_expected_v = None
            cancel = getattr(coordinator, "_replay_clear_cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:  # noqa: BLE001
                    pass
                coordinator._replay_clear_cancel = None
            if coordinator.data.replay_loading:
                import dataclasses as _dc
                coordinator.async_set_updated_data(
                    _dc.replace(coordinator.data, replay_loading=False)
                )

        return web.Response(
            body=coordinator.cached_map_png,
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


class LidarPcdDownloadView(HomeAssistantView):
    """HTTP endpoint that serves the most recent archived ``.pcd`` blob.

    GET ``/api/dreame_a2_mower/lidar/latest.pcd`` (auth required).

    The coordinator is looked up from ``hass.data`` on each request so
    a config-entry reload is picked up without re-registering the view.
    Spec §5.9: auth required (creds discipline).

    Returns 404 with a brief explanation when:
      - no coordinator is registered yet,
      - the coordinator's lidar_archive is None,
      - the archive has no entries,
      - the on-disk .pcd file referenced by index.json is missing.
    """

    url = "/api/dreame_a2_mower/lidar/latest.pcd"
    name = "api:dreame_a2_mower:lidar_latest"
    requires_auth = True

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app["hass"]
        entries = hass.data.get(DOMAIN) or {}
        archive = None
        for coordinator in entries.values():
            cand = getattr(coordinator, "lidar_archive", None)
            if cand is not None:
                archive = cand
                break
        if archive is None:
            return web.Response(status=404, text="LiDAR archive disabled")
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
