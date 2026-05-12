"""LawnMower platform for the Dreame A2 Mower integration.

Per spec §5.1: the primary state + control surface. F1 reads state
from MowerState; F3 wires action calls to cloud RPC.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import mower_device_info, mower_unique_id
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

# Reverse of _STATE_TO_ACTIVITY for restoration. Since DOCKED maps from
# multiple states (STANDBY, CHARGING, CHARGED, UPDATING), prefer STANDBY
# on restore — if the mower is actually CHARGING the next MQTT push will
# correct it within seconds.
_ACTIVITY_TO_STATE: dict[LawnMowerActivity, State] = {
    LawnMowerActivity.MOWING: State.WORKING,
    LawnMowerActivity.DOCKED: State.STANDBY,
    LawnMowerActivity.PAUSED: State.PAUSED,
    LawnMowerActivity.RETURNING: State.RETURNING,
}


def project_activity(snapshot) -> LawnMowerActivity:
    """Project StateSnapshot to HA's impoverished LawnMowerActivity enum.

    HA's enum has only MOWING / DOCKED / PAUSED / RETURNING / ERROR
    — no "idle on lawn" or "cruising" states. This function applies
    the projection rules from the spec (§ Entities consuming the
    snapshot, lawn_mower projection rules).
    """
    from .mower.state_snapshot import (
        CurrentActivity as CA, Location as L,
    )
    if snapshot.errors:
        return LawnMowerActivity.ERROR
    ca = snapshot.current_activity
    if ca == CA.MOWING:
        return LawnMowerActivity.MOWING
    if ca == CA.PAUSED:
        return LawnMowerActivity.PAUSED
    if ca == CA.RETURNING:
        return LawnMowerActivity.RETURNING
    if ca == CA.CHARGE_RESUME:
        return LawnMowerActivity.DOCKED
    if ca == CA.IDLE:
        return (
            LawnMowerActivity.DOCKED
            if snapshot.location == L.AT_DOCK
            else LawnMowerActivity.PAUSED
        )
    if ca in (CA.CRUISING_TO_POINT, CA.FAST_MAPPING,
              CA.DRIVING_BLADES_UP, CA.REPOSITIONING):
        return LawnMowerActivity.MOWING
    if ca == CA.AT_POINT:
        return LawnMowerActivity.PAUSED
    return LawnMowerActivity.ERROR


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the lawn_mower platform from a config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameA2LawnMower(coordinator)])


class DreameA2LawnMower(
    CoordinatorEntity[DreameA2MowerCoordinator], LawnMowerEntity, RestoreEntity
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
        self._attr_unique_id = mower_unique_id(coordinator, "lawn_mower")
        self._attr_device_info = mower_device_info(coordinator)

    async def async_added_to_hass(self) -> None:
        """Restore last-known state so the entity isn't 'unknown' on cold boot."""
        await super().async_added_to_hass()
        if self.coordinator.data.state is not None:
            # Live state already populated (e.g., MQTT pushed during setup)
            return
        last = await self.async_get_last_state()
        if last is None or last.state in (None, "unknown", "unavailable"):
            return
        # Reverse-map LawnMowerActivity back to State (best-effort)
        try:
            activity = LawnMowerActivity(last.state)
        except ValueError:
            LOGGER.debug(
                "lawn_mower: unrecognized restored state %r — ignoring",
                last.state,
            )
            return
        restored_state = _ACTIVITY_TO_STATE.get(activity)
        if restored_state is None:
            return
        # Push the restored value into coordinator.data so the buttons see it too.
        new_data = dataclasses.replace(self.coordinator.data, state=restored_state)
        self.coordinator.async_set_updated_data(new_data)
        LOGGER.info(
            "lawn_mower: restored state from last-known activity %r → %s",
            last.state,
            restored_state.name,
        )

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Project StateSnapshot to LawnMowerActivity via snapshot-based rules."""
        return project_activity(self.coordinator.state_machine.snapshot())

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Surface cloud-state diagnostics: task_id (cloud-side action target)."""
        cs = getattr(self.coordinator, "cloud_state", None)
        if cs is None:
            return {}
        return {"task_id": cs.task_id}
