"""Button platform — primary mow controls + finalize escape hatch.

Mirrors the Dreame app's main button row: Start / Pause / Stop /
Recharge. Plus a Finalize-Session escape hatch that runs the
finalize-incomplete path when a session is stuck without a cloud
summary.

All buttons live in the device page's main controls section
(no entity_category) so the Dreame app's "tap to start" UX is
preserved at-a-glance on the HA device card.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.actions import MowerAction
from .mower.state import State


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up button entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DreameA2StartMowingButton(coordinator),
            DreameA2PauseMowingButton(coordinator),
            DreameA2StopMowingButton(coordinator),
            DreameA2RechargeButton(coordinator),
            DreameA2FindBotButton(coordinator),
            DreameA2FinalizeSessionButton(coordinator),
        ]
    )


class _DreameA2ActionButton(
    CoordinatorEntity[DreameA2MowerCoordinator], ButtonEntity
):
    """Base for primary mow-control buttons mirroring the Dreame app's
    Start / Pause / Stop / Recharge tiles."""

    _attr_has_entity_name = True
    _action: MowerAction
    _params: dict | None = None

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        unique_suffix: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_suffix}"
        self._attr_name = name
        self._attr_icon = icon
        client = coordinator._cloud
        device_id = getattr(client, "device_id", None) if client is not None else None
        model = getattr(client, "model", None) if client is not None else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Dreame A2 Mower",
            manufacturer="Dreame",
            model=model or "dreame.mower.g2408",
        )

    async def async_press(self) -> None:
        LOGGER.info("button.%s: pressed; dispatching %s", self._attr_unique_id, self._action.name)
        await self.coordinator.dispatch_action(self._action, self._params or {})


class DreameA2StartMowingButton(_DreameA2ActionButton):
    """Start mowing in the currently-selected action_mode."""

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "start_mowing", "Start mowing", "mdi:play-circle")
        self._action = MowerAction.START_MOWING

    async def async_press(self) -> None:
        # Route through the lawn_mower entity's start handler so action_mode
        # + active_selection get respected (zone/spot/edge → right opcode).
        from .mower.state import ActionMode

        state = self.coordinator.data
        mode = state.action_mode
        if mode == ActionMode.ALL_AREAS:
            action, params = MowerAction.START_MOWING, {}
        elif mode == ActionMode.EDGE:
            action, params = MowerAction.START_EDGE_MOW, {"contour_ids": []}
        elif mode == ActionMode.ZONE:
            zones = state.active_selection_zones
            if not zones:
                LOGGER.warning("button.start_mowing: zone mode but no zones selected; no-op")
                return
            action, params = MowerAction.START_ZONE_MOW, {"zones": list(zones)}
        elif mode == ActionMode.SPOT:
            spots = state.active_selection_spots
            if not spots:
                LOGGER.warning("button.start_mowing: spot mode but no spots selected; no-op")
                return
            action, params = MowerAction.START_SPOT_MOW, {"spots": list(spots)}
        else:
            LOGGER.warning("button.start_mowing: unknown action_mode %r", mode)
            return
        LOGGER.info("button.start_mowing: dispatching %s with %s", action.name, params)
        await self.coordinator.dispatch_action(action, params)


class DreameA2PauseMowingButton(_DreameA2ActionButton):
    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "pause_mowing", "Pause", "mdi:pause-circle")
        self._action = MowerAction.PAUSE

    @property
    def available(self) -> bool:
        # Pause only makes sense while actively mowing.
        return self.coordinator.data.state in (State.WORKING, State.MAPPING)


class DreameA2StopMowingButton(_DreameA2ActionButton):
    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "stop_mowing", "Stop", "mdi:stop-circle")
        self._action = MowerAction.STOP

    @property
    def available(self) -> bool:
        # WORKING/MAPPING/PAUSED → Stop, RETURNING → End Return to Station.
        # Both go through the same MowerAction.STOP wire call.
        return self.coordinator.data.state in (
            State.WORKING,
            State.MAPPING,
            State.PAUSED,
            State.RETURNING,
        )


class DreameA2RechargeButton(_DreameA2ActionButton):
    """Send the mower back to the dock.

    Greyed out when the mower is already at the dock (CHARGING /
    CHARGED) or already on its way (RETURNING) — matches the app
    which disables the Recharge tile in those states.
    """

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "recharge", "Recharge", "mdi:home-import-outline")
        self._action = MowerAction.RECHARGE

    @property
    def available(self) -> bool:
        return self.coordinator.data.state not in (
            State.CHARGING,
            State.CHARGED,
            State.RETURNING,
        )


class DreameA2FindBotButton(_DreameA2ActionButton):
    """Play the locator beep so the user can find the mower out in the lawn.

    The action is fire-and-forget on the mower side — wire format
    (s2.50 routed-action with siid=7 aiid=1, routed_o=9) is sent on the
    inbound /cmd/ MQTT topic; the mower performs the locate and does NOT
    echo any state change on /status/. Always available; pressing it
    while the mower is docked just makes the dock area beep.
    """

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "find_bot", "Find my robot", "mdi:map-marker-radius")
        self._action = MowerAction.FIND_BOT


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
        )

    async def async_press(self) -> None:
        """Handle button press — run the finalize-incomplete path."""
        LOGGER.info(
            "button.finalize_session: pressed; dispatching FINALIZE_SESSION action"
        )
        await self.coordinator.dispatch_action(MowerAction.FINALIZE_SESSION, {})
