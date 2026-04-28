"""Service handlers for the Dreame A2 Mower integration.

Per spec §5.2: actions live in service calls; entities should be state.
This module wires the services declared in services.yaml to the
action-dispatch helpers in mower/actions.py (built in F3.5).

The handlers are registered in __init__.py via async_setup_entry, and
unregistered in async_unload_entry.
"""
from __future__ import annotations

import dataclasses
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, LOGGER
from .coordinator import DreameA2MowerCoordinator
from .mower.state import ActionMode

# Service names — keep in sync with services.yaml
SERVICE_SET_ACTIVE_SELECTION = "set_active_selection"
SERVICE_MOW_ZONE = "mow_zone"
SERVICE_MOW_EDGE = "mow_edge"
SERVICE_MOW_SPOT = "mow_spot"
SERVICE_RECHARGE = "recharge"
SERVICE_FIND_BOT = "find_bot"
SERVICE_LOCK_BOT = "lock_bot"
SERVICE_SUPPRESS_FAULT = "suppress_fault"
SERVICE_FINALIZE_SESSION = "finalize_session"
SERVICE_REPLAY_SESSION = "replay_session"


# Schemas
SCHEMA_SET_SELECTION = vol.Schema(
    {
        vol.Optional("zones", default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional("spots", default=[]): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    }
)

SCHEMA_MOW_ZONE = vol.Schema(
    {vol.Required("zone_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)])}
)

SCHEMA_MOW_EDGE = vol.Schema(
    {vol.Optional("zone_id"): vol.Coerce(int)}
)

SCHEMA_MOW_SPOT = vol.Schema(
    {vol.Required("point"): vol.All(cv.ensure_list, [vol.Coerce(float)])}
)

SCHEMA_EMPTY = vol.Schema({})

SCHEMA_REPLAY_SESSION = vol.Schema(
    {vol.Required("session_md5"): str}
)


def _coordinator_from_call(hass: HomeAssistant, call: ServiceCall) -> DreameA2MowerCoordinator | None:
    """Resolve the (only) coordinator instance.

    Single-mower integration: there's at most one coordinator. If
    multi-mower is ever supported, the call would need to specify
    which one (e.g., via entity_id of the lawn_mower entity).
    """
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        LOGGER.warning("No %s coordinator registered; service ignored", DOMAIN)
        return None
    return next(iter(coordinators.values()))


async def _handle_set_active_selection(call: ServiceCall) -> None:
    """Update coordinator.data.active_selection_zones / _spots."""
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    zones = tuple(call.data.get("zones", []))
    spots = tuple(call.data.get("spots", []))
    new_state = dataclasses.replace(
        coordinator.data,
        active_selection_zones=zones,
        active_selection_spots=spots,
    )
    coordinator.async_set_updated_data(new_state)


async def _handle_mow_zone(call: ServiceCall) -> None:
    """Set zone selection then dispatch start_mowing in zone mode."""
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    zone_ids = tuple(call.data["zone_ids"])
    new_state = dataclasses.replace(
        coordinator.data,
        action_mode=ActionMode.ZONE,
        active_selection_zones=zone_ids,
    )
    coordinator.async_set_updated_data(new_state)
    # Dispatch the actual start. Imported here to avoid circular imports.
    from .mower.actions import MowerAction
    await coordinator.dispatch_action(MowerAction.START_ZONE_MOW, {"zones": list(zone_ids)})


async def _handle_mow_edge(call: ServiceCall) -> None:
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    zone_id = call.data.get("zone_id")
    payload: dict[str, Any] = {}
    if zone_id is not None:
        payload["zone_id"] = int(zone_id)
    from .mower.actions import MowerAction
    await coordinator.dispatch_action(MowerAction.START_EDGE_MOW, payload)


async def _handle_mow_spot(call: ServiceCall) -> None:
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    point = call.data["point"]
    if not isinstance(point, list) or len(point) != 2:
        LOGGER.warning("mow_spot: point must be [x_m, y_m]; got %r", point)
        return
    # START_SPOT_MOW is local_only (F5 TODO): the g2408 spot-mow wire format
    # goes via DreameMowerAction.START_CUSTOM, not the TASK routed-action path.
    # Log a user-visible warning so the service call is not silently ignored.
    LOGGER.warning(
        "mow_spot: spot-mow not yet wired for g2408 (TODO F5); call ignored. "
        "point=%r", point
    )
    from .mower.actions import MowerAction
    await coordinator.dispatch_action(
        MowerAction.START_SPOT_MOW,
        {"x_m": float(point[0]), "y_m": float(point[1])},
    )


async def _handle_simple_action(action_name: str):
    """Factory for parameterless action handlers (recharge, find_bot, etc.)."""
    from .mower.actions import MowerAction
    target = MowerAction[action_name]

    async def handler(call: ServiceCall) -> None:
        coordinator = _coordinator_from_call(call.hass, call)
        if coordinator is None:
            return
        await coordinator.dispatch_action(target, {})

    return handler



async def _handle_replay_session(call: ServiceCall) -> None:
    """Look up an archived session by md5 and render it into cached_map_png."""
    coordinator = _coordinator_from_call(call.hass, call)
    if coordinator is None:
        return
    md5 = call.data["session_md5"].strip()
    await coordinator.replay_session(md5)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all the integration's service handlers."""
    hass.services.async_register(DOMAIN, SERVICE_SET_ACTIVE_SELECTION,
                                  _handle_set_active_selection, schema=SCHEMA_SET_SELECTION)
    hass.services.async_register(DOMAIN, SERVICE_MOW_ZONE,
                                  _handle_mow_zone, schema=SCHEMA_MOW_ZONE)
    hass.services.async_register(DOMAIN, SERVICE_MOW_EDGE,
                                  _handle_mow_edge, schema=SCHEMA_MOW_EDGE)
    hass.services.async_register(DOMAIN, SERVICE_MOW_SPOT,
                                  _handle_mow_spot, schema=SCHEMA_MOW_SPOT)
    hass.services.async_register(DOMAIN, SERVICE_RECHARGE,
                                  await _handle_simple_action("RECHARGE"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_FIND_BOT,
                                  await _handle_simple_action("FIND_BOT"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_LOCK_BOT,
                                  await _handle_simple_action("LOCK_BOT_TOGGLE"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_SUPPRESS_FAULT,
                                  await _handle_simple_action("SUPPRESS_FAULT"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_FINALIZE_SESSION,
                                  await _handle_simple_action("FINALIZE_SESSION"), schema=SCHEMA_EMPTY)
    hass.services.async_register(DOMAIN, SERVICE_REPLAY_SESSION,
                                  _handle_replay_session, schema=SCHEMA_REPLAY_SESSION)


def async_unregister_services(hass: HomeAssistant) -> None:
    for svc in (
        SERVICE_SET_ACTIVE_SELECTION, SERVICE_MOW_ZONE, SERVICE_MOW_EDGE, SERVICE_MOW_SPOT,
        SERVICE_RECHARGE, SERVICE_FIND_BOT, SERVICE_LOCK_BOT, SERVICE_SUPPRESS_FAULT,
        SERVICE_FINALIZE_SESSION, SERVICE_REPLAY_SESSION,
    ):
        hass.services.async_remove(DOMAIN, svc)
