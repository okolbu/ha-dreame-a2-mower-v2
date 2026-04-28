"""Button platform — manual escape-hatch actions for the Dreame A2 Mower.

F5.10.1: Adds a single button entity:
  button.dreame_a2_mower_finalize_session

When pressed, calls coordinator.dispatch_action(MowerAction.FINALIZE_SESSION)
which runs the finalize-incomplete path:
  - Archives whatever live_map currently holds as an "(incomplete)" session.
  - Clears pending_session_* state.
  - Calls live_map.end_session().
  - Updates MowerState.archived_session_count.

The button is always available (no session-active gate) because pressing it
when no session is live is a no-op: _run_finalize_incomplete archives an empty
session and clears already-None pending fields, which is harmless.  This is the
correct behaviour for the "mower went offline mid-run; HA restarted" escape hatch
— the user should be able to press it at any time without thinking about state.

The button is classified EntityCategory.DIAGNOSTIC so it lives in the "diagnostic"
section of the device page rather than cluttering the primary control surface.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.actions import MowerAction


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up button entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2FinalizeSessionButton(coordinator)])


class DreameA2FinalizeSessionButton(
    CoordinatorEntity[DreameA2MowerCoordinator], ButtonEntity
):
    """Manual escape-hatch: force-finalize the current (or stuck) mowing session.

    Pressing this button triggers the finalize-incomplete path regardless of
    whether a session is in progress.  It is safe to press when idle — the
    underlying _run_finalize_incomplete() call is a no-op when live_map has
    no active session.

    Use-case: mower went offline mid-mow; HA restarted and the session is
    "stuck" in a pending state.  Press this to flush the incomplete session
    to the archive and reset the live-map state so the next mow starts clean.
    """

    _attr_has_entity_name = True
    _attr_name = "Finalize session"
    _attr_icon = "mdi:flag-checkered"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_finalize_session"
        client = coordinator._cloud  # may be None during very-early setup
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
            serial_number=device_id,
        )

    async def async_press(self) -> None:
        """Handle button press — run the finalize-incomplete path."""
        LOGGER.info(
            "button.finalize_session: pressed; dispatching FINALIZE_SESSION action"
        )
        await self.coordinator.dispatch_action(MowerAction.FINALIZE_SESSION, {})
