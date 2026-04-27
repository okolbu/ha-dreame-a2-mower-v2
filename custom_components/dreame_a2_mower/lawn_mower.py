"""LawnMower platform for the Dreame A2 Mower integration.

Per spec §5.1: the primary state + control surface. F1 reads state
from MowerState; F3 wires action calls to cloud RPC.
"""
from __future__ import annotations

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import State


# Map MowerState.State → LawnMowerActivity. None entries map to ERROR
# in HA terms (HA's LawnMowerActivity has no IDLE state distinct from
# DOCKED, so we synthesize).
_STATE_TO_ACTIVITY: dict[State, LawnMowerActivity] = {
    State.WORKING: LawnMowerActivity.MOWING,
    State.STANDBY: LawnMowerActivity.DOCKED,
    State.PAUSED: LawnMowerActivity.PAUSED,
    State.RETURNING: LawnMowerActivity.RETURNING,
    State.CHARGING: LawnMowerActivity.DOCKED,
    State.MAPPING: LawnMowerActivity.MOWING,
    State.CHARGED: LawnMowerActivity.DOCKED,
    State.UPDATING: LawnMowerActivity.DOCKED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the lawn_mower platform from a config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2LawnMower(coordinator)])


class DreameA2LawnMower(
    CoordinatorEntity[DreameA2MowerCoordinator], LawnMowerEntity
):
    """The Dreame A2 mower as an HA lawn_mower entity."""

    _attr_has_entity_name = True
    _attr_name = None  # use device name
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_lawn_mower"

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Map MowerState.state to LawnMowerActivity."""
        s = self.coordinator.data.state
        if s is None:
            return None
        return _STATE_TO_ACTIVITY.get(s)

    async def async_start_mowing(self) -> None:
        """F1: log and no-op. F3 wires this to cloud RPC."""
        LOGGER.info("start_mowing requested — F1 stub (F3 will wire to cloud)")

    async def async_pause(self) -> None:
        LOGGER.info("pause requested — F1 stub")

    async def async_dock(self) -> None:
        LOGGER.info("dock requested — F1 stub")
