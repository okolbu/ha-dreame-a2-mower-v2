"""Camera platform — base live map for Dreame A2 Mower."""
from __future__ import annotations

from aiohttp import web
from homeassistant.components.camera import Camera
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
            serial_number=device_id,
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the current rendered base-map PNG."""
        rendered = self.coordinator.cached_map_png
        return rendered  # may be None on first boot before map is fetched


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
            serial_number=device_id,
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
