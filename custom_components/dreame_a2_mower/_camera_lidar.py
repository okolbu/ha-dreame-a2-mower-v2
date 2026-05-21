"""LiDAR camera entities — top-down and selected-scan cameras."""
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .coordinator import DreameA2MowerCoordinator


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
        from .protocol.pcd import decode_pcd
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
            cloud = await self.hass.async_add_executor_job(decode_pcd, pcd_bytes)
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
        cache = getattr(coordinator.cloud_state, "maps_by_id", None) or {}
        map_obj = cache.get(map_id)
        map_name = getattr(map_obj, "name", None) if map_obj is not None else None
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "LiDAR (top-down)"


class DreameA2LidarTopDownFullCamera(_LidarCameraBase):
    """Full-resolution popout (1024×1024). One per map."""

    _attr_translation_key = "lidar_top_down_full"
    _resolution = (1024, 1024)

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator, map_id=map_id)
        self._attr_unique_id = map_unique_id(coordinator, map_id, "lidar_top_down_full")
        cache = getattr(coordinator.cloud_state, "maps_by_id", None) or {}
        map_obj = cache.get(map_id)
        map_name = getattr(map_obj, "name", None) if map_obj is not None else None
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)
        # has_entity_name=True; device_name is prepended automatically.
        self._attr_name = "LiDAR (full resolution)"


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
        from .protocol.pcd import decode_pcd
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
            cloud = await self.hass.async_add_executor_job(decode_pcd, pcd_bytes)
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
