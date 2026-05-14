"""Device tracker (GPS) for the Dreame A2 Mower."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, mower_unique_id
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
    CoordinatorEntity[DreameA2MowerCoordinator], TrackerEntity, RestoreEntity
):
    """Maps MowerState.position_lat/lon to HA's device_tracker.

    Source: LOCN routed action (`{pos: [lon, lat]}`), polled every 60s
    on a separate timer from the main coordinator (so the GPS entity
    stays alive when the bulk cloud state refresh fails). Sentinel
    `[-1, -1]` means the dock origin isn't configured.

    Robustness:
    - ``RestoreEntity``: last-known lat/lon survive HA restarts.
      When LOCN fails (mower offline → cloud 80001), we keep showing
      the most recent fix instead of going `unavailable` (which
      removes the marker from the HA map card).
    - ``available`` only gates on having coords; it does NOT gate on
      the main coordinator's ``last_update_success``. The map should
      stay populated even when other entities are dragging the
      coordinator into a failing state.
    """

    _attr_has_entity_name = True
    _attr_name = "Location"
    _attr_icon = "mdi:robot-mower"
    _attr_source_type = SourceType.GPS
    # GPS dock-origin configuration isn't implemented yet, so this entity
    # is permanently `unavailable` until that lands. Disable-by-default
    # so it doesn't clutter the entity list on fresh installs. Existing
    # installs are unaffected — users can re-enable via the entity
    # registry once dock-origin support arrives.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "gps")
        self._attr_device_info = mower_device_info(coordinator)
        self._restored_lat: float | None = None
        self._restored_lon: float | None = None

    async def async_added_to_hass(self) -> None:
        """Pull last-known lat/lon out of the recorder so the marker
        survives HA restarts and LOCN-polling failures."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or not last.attributes:
            return
        try:
            lat = last.attributes.get("latitude")
            lon = last.attributes.get("longitude")
            if lat is not None and lon is not None:
                self._restored_lat = float(lat)
                self._restored_lon = float(lon)
        except (TypeError, ValueError):
            pass

    @property
    def latitude(self) -> float | None:
        live = self.coordinator.data.position_lat
        return live if live is not None else self._restored_lat

    @property
    def longitude(self) -> float | None:
        live = self.coordinator.data.position_lon
        return live if live is not None else self._restored_lon

    @property
    def available(self) -> bool:
        # Available iff we have coords (live or restored). NOT gated
        # on coordinator.last_update_success — LOCN has its own
        # success path independent of the bulk refresh.
        return self.latitude is not None and self.longitude is not None
