"""Camera platform entry-point — registers the HTTP views and instantiates
all camera entities. The entity classes live in the `_camera_*` siblings."""
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator

from ._camera_map import (
    DreameA2MapCamera,
    DreameA2PerMapCamera,
    DreameA2WorkLogCamera,
)
from ._camera_lidar import (
    DreameA2LidarTopDownCamera,
    DreameA2LidarTopDownFullCamera,
    DreameA2LidarSelectedCamera,
)
from ._camera_wifi import (
    DreameA2WifiSelectedCamera,
    DreameA2WifiPerMapCamera,
)
from ._camera_views import (
    LidarPcdDownloadView,
    LidarSelectedPcdView,
    MapImageView,
    WorkLogImageView,
)


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
    for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):
        entities.append(DreameA2PerMapCamera(coordinator, map_id))
    # LiDAR cameras — one per known map (top-down thumbnail + full-res).
    for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):
        entities.append(DreameA2LidarTopDownCamera(coordinator, map_id=map_id))
        entities.append(DreameA2LidarTopDownFullCamera(coordinator, map_id=map_id))
    entities.append(DreameA2WorkLogCamera(coordinator))
    entities.append(DreameA2LidarSelectedCamera(coordinator))
    # Single picker-driven WiFi heatmap camera (follows DreameA2WifiViewSelect).
    entities.append(DreameA2WifiSelectedCamera(coordinator))
    # Per-map WiFi heatmap cameras — one per known map (v1.0.10a6+).
    # Renders the newest archive entry whose fingerprint-matcher
    # map_id equals the camera's map_id.
    for map_id in sorted(coordinator.cloud_state.maps_by_id.keys()):
        entities.append(DreameA2WifiPerMapCamera(coordinator, map_id))

    async_add_entities(entities)
