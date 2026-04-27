"""Device tracker (GPS) for the Dreame A2 Mower."""
from __future__ import annotations

from homeassistant.components.device_tracker.config_entry import TrackerEntity
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
    async_add_entities([DreameA2MowerGpsTracker(coordinator)])


class DreameA2MowerGpsTracker(
    CoordinatorEntity[DreameA2MowerCoordinator], TrackerEntity
):
    """Maps MowerState.position_lat/lon to HA's device_tracker.

    Source: LOCN routed action (`{pos: [lon, lat]}`). Sentinel
    `[-1, -1]` means the dock origin isn't configured — the entity
    is unavailable until the user runs the app's "Set dock GPS"
    flow. Per spec §8 unknowns policy, this is a persistent field;
    last-known coords survive HA restarts via RestoreEntity (F5
    when RestoreEntity is wired more broadly; F2 leaves it without).
    """

    _attr_has_entity_name = True
    _attr_name = "Location"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_gps"
        client = coordinator._cloud
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
            serial_number=device_id,
        )

    @property
    def latitude(self) -> float | None:
        return self.coordinator.data.position_lat

    @property
    def longitude(self) -> float | None:
        return self.coordinator.data.position_lon

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.position_lat is not None
            and self.coordinator.data.position_lon is not None
        )
