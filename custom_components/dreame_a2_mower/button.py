"""Button platform — primary mow controls + finalize escape hatch.

Mirrors the Dreame app's main button row: Start / Pause / Stop /
Recharge. Plus a Finalize-Session escape hatch that runs the
finalize-incomplete path when a session is stuck without a cloud
summary, and a Refresh-Cloud-State button that forces a full
on-demand pull of CFG / SETTINGS / SCHEDULE / MAP / etc.

All buttons live in the device page's main controls section
(no entity_category) so the Dreame app's "tap to start" UX is
preserved at-a-glance on the HA device card.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._devices import map_device_info, map_unique_id, mower_device_info, mower_unique_id
from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.actions import MowerAction
from .mower.state import State


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities from the config entry."""
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = [
        DreameA2StartMowingButton(coordinator),
        DreameA2PauseMowingButton(coordinator),
        DreameA2StopMowingButton(coordinator),
        DreameA2RechargeButton(coordinator),
        DreameA2FindBotButton(coordinator),
        DreameA2LockBotButton(coordinator),
        DreameA2Generate3DMapButton(coordinator),
        DreameA2FinalizeSessionButton(coordinator),
        DreameA2RefreshCloudStateButton(coordinator),
    ]
    # One "Refresh WiFi map" button per known map.
    for map_id in sorted(coordinator._cached_maps_by_id.keys()):
        entities.append(DreameA2RequestWifiMapButton(coordinator, map_id=map_id))
    async_add_entities(entities)


class _DreameA2ActionButton(
    CoordinatorEntity[DreameA2MowerCoordinator], ButtonEntity
):
    """Base for primary mow-control buttons mirroring the Dreame app's
    Start / Pause / Stop / Recharge tiles."""

    _attr_has_entity_name = True
    _action: MowerAction
    _params: dict[str, object] | None = None

    def __init__(
        self,
        coordinator: DreameA2MowerCoordinator,
        unique_suffix: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, unique_suffix)
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = mower_device_info(coordinator)

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
            # Honour the dedicated `select.edge` picker. Empty tuple
            # means "no specific selection" → coordinator.dispatch_action
            # resolves to every outer-perimeter contour from the cached
            # map (the multi-zone-correct default). Non-empty tuple is
            # the user's explicit single-perimeter pick.
            edge_contours = state.active_selection_edge_contours
            params = {"contour_ids": [list(c) for c in edge_contours]}
            action = MowerAction.START_EDGE_MOW
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


class DreameA2LockBotButton(_DreameA2ActionButton):
    """Lock the mower (apk opcode 12 "lockBot") — distinct from CHILD_LOCK.

    Where CHILD_LOCK (the toggle in switch.child_lock) flips the CFG.CLS
    flag, this is the discrete "lockBot" action documented in apk
    §"Actions" (op=12) and used by ioBroker.dreame v0.3.7 as a separate
    button. The exact runtime semantics on g2408 are unverified — added
    for live testing once the mower is docked.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "lock_bot", "Lock robot", "mdi:lock")
        self._action = MowerAction.LOCK_BOT


class DreameA2Generate3DMapButton(_DreameA2ActionButton):
    """Trigger the on-device LIDAR 3D map render (apk opcode 10).

    Long-running on the mower side; progress is published on s2p54
    ("3dmap-progress") and a final URL on the LIDAR file slot.
    Wire format ``{m:'a', p:0, o:10, d:{idx:0}}`` from ioBroker.dreame
    v0.3.7 main.js:3474. Untested on g2408.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator, "generate_3dmap", "Generate 3D map", "mdi:cube-outline")
        self._action = MowerAction.GENERATE_3D_MAP


class DreameA2RequestWifiMapButton(
    CoordinatorEntity[DreameA2MowerCoordinator], ButtonEntity
):
    """Refresh the WiFi signal heatmap view from the cloud — per-map.

    On g2408 the direct MIoT `s6.aiid=4` "request fresh wifi map"
    path is closed (verified live 2026-05-09 — returns 80001). The
    mower auto-generates wifi maps on its own schedule; we cannot
    trigger a fresh render. Pressing this button instead refreshes
    the integration's cache from the latest OSS-cached wifimap
    object for this map and updates the corresponding per-map
    `camera.dreame_a2_mower_wifi_heatmap_<N>`. See matrix
    `button.request_wifi_map` row + the TODO entry for the trigger
    discovery.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: DreameA2MowerCoordinator, *, map_id: int
    ) -> None:
        super().__init__(coordinator)
        self._map_id = map_id
        self._attr_unique_id = map_unique_id(coordinator, map_id, "request_wifi_map")
        self._attr_icon = "mdi:wifi"
        map_obj = coordinator._cached_maps_by_id.get(map_id)
        map_name = getattr(map_obj, "name", None) or f"Map {map_id + 1}"
        self._attr_name = f"{map_name} Refresh WiFi map view"
        self._attr_device_info = map_device_info(coordinator, map_id, name=map_name)

    async def async_press(self) -> None:
        LOGGER.info(
            "button.request_wifi_map: refreshing WiFi heatmap for map %d",
            self._map_id,
        )
        await self.coordinator._refresh_wifi_map(map_id=self._map_id)


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
        self._attr_unique_id = mower_unique_id(coordinator, "finalize_session")
        self._attr_device_info = mower_device_info(coordinator)

    async def async_press(self) -> None:
        """Handle button press — run the finalize-incomplete path."""
        LOGGER.info(
            "button.finalize_session: pressed; dispatching FINALIZE_SESSION action"
        )
        await self.coordinator.dispatch_action(MowerAction.FINALIZE_SESSION, {})


class DreameA2RefreshCloudStateButton(
    CoordinatorEntity[DreameA2MowerCoordinator], ButtonEntity
):
    """Force an on-demand re-fetch of all cloud-derived state.

    Triggers `_refresh_cloud_state` immediately instead of waiting for
    the next 10-min poll or an MQTT tripwire. Useful when:

    - Settings were changed in the Dreame app and HA hasn't caught up
      via the s6p2 tripwire (e.g. the device didn't push, or the user
      wants to confirm "everything is current right now").
    - Debugging a settings sync issue and you want the latest cloud
      view in HA without waiting.

    Diagnostic category — lives in the device's diagnostics section
    rather than the main controls row.
    """

    _attr_has_entity_name = True
    _attr_name = "Refresh from cloud"
    _attr_icon = "mdi:cloud-refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "refresh_cloud_state")
        self._attr_device_info = mower_device_info(coordinator)

    async def async_press(self) -> None:
        LOGGER.info("button.refresh_cloud_state: pressed; refreshing all cloud state")
        await self.coordinator._refresh_cloud_state()
