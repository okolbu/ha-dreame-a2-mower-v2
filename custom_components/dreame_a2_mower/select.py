"""Select platform — action_mode picker for the Dreame A2 Mower."""
from __future__ import annotations

import dataclasses

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ActionMode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2ActionModeSelect(coordinator)])


class DreameA2ActionModeSelect(
    CoordinatorEntity[DreameA2MowerCoordinator], SelectEntity
):
    """User-facing action_mode picker.

    Per spec §5.1: HA realization of the Dreame app's mode dropdown
    (All-areas / Edge / Zone / Spot — Manual is BT-only and omitted).

    Selection is integration state stored on coordinator.data.action_mode
    and persisted across HA restarts via RestoreEntity (TBD: HA's
    SelectEntity doesn't auto-restore; we set the initial state from
    coordinator.data on entity construction, and write through to
    coordinator on every change).
    """

    _attr_has_entity_name = True
    _attr_name = "Action mode"
    _attr_options = [m.value for m in ActionMode]

    entity_description = SelectEntityDescription(
        key="action_mode",
        translation_key="action_mode",
    )

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_mode"
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

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.action_mode.value

    async def async_select_option(self, option: str) -> None:
        """Update coordinator.data.action_mode and broadcast."""
        new_mode = ActionMode(option)
        new_state = dataclasses.replace(self.coordinator.data, action_mode=new_mode)
        self.coordinator.async_set_updated_data(new_state)
