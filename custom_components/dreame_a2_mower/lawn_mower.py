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
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.actions import MowerAction
from .mower.state import ActionMode, State


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
        client = coordinator._cloud  # may be None during very-early setup
        model = getattr(client, "model", None) if client is not None else None
        mac = getattr(client, "mac_address", None) if client is not None else None
        connections: set[tuple[str, str]] = (
            {(CONNECTION_NETWORK_MAC, mac)} if mac else set()
        )
        # Hardware serial fetched lazily via cloud RPC (s1.5). The
        # coordinator pushes it onto the device record once it lands;
        # at __init__ time it may still be None and that's fine — HA
        # accepts None for serial_number.
        serial = getattr(coordinator.data, "hardware_serial", None)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            connections=connections,
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
            serial_number=serial,
        )

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Map MowerState.state to LawnMowerActivity."""
        s = self.coordinator.data.state
        if s is None:
            return None
        return _STATE_TO_ACTIVITY.get(s)

    async def async_start_mowing(self) -> None:
        """Start mowing in the currently-selected action_mode.

        Reads coordinator.data.action_mode + active_selection_zones/spots
        to pick the right opcode. Dispatches via coordinator.dispatch_action
        which routes to the working cloud path on g2408.
        """
        state = self.coordinator.data
        mode = state.action_mode
        if mode == ActionMode.ALL_AREAS:
            await self.coordinator.dispatch_action(MowerAction.START_MOWING, {})
            return
        if mode == ActionMode.EDGE:
            await self.coordinator.dispatch_action(MowerAction.START_EDGE_MOW, {})
            return
        if mode == ActionMode.ZONE:
            zones = state.active_selection_zones
            if not zones:
                LOGGER.warning("start_mowing: zone mode but no zones selected; no-op")
                return
            await self.coordinator.dispatch_action(
                MowerAction.START_ZONE_MOW, {"zones": list(zones)}
            )
            return
        if mode == ActionMode.SPOT:
            spots = state.active_selection_spots
            if not spots:
                LOGGER.warning("start_mowing: spot mode but no spots selected; no-op")
                return
            await self.coordinator.dispatch_action(
                MowerAction.START_SPOT_MOW, {"spots": list(spots)}
            )
            return
        LOGGER.warning("start_mowing: unknown action_mode %r", mode)

    async def async_pause(self) -> None:
        await self.coordinator.dispatch_action(MowerAction.PAUSE, {})

    async def async_dock(self) -> None:
        await self.coordinator.dispatch_action(MowerAction.DOCK, {})
