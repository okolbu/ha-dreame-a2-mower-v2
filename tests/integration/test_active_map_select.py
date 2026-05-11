"""Active-map select uses SN-based unique_id on the mower device."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.dreame_a2_mower.const import DOMAIN


def test_active_map_select_unique_id_uses_sn(coordinator_with_two_maps):
    coord = coordinator_with_two_maps
    from custom_components.dreame_a2_mower.select import DreameA2ActiveMapSelect

    e = DreameA2ActiveMapSelect(coord)
    assert e._attr_unique_id == "G2408053AEE0006232_active_map"
    assert e._attr_device_info["identifiers"] == {(DOMAIN, "G2408053AEE0006232")}


def test_active_map_select_exposes_current_map_id_attribute(
    coordinator_with_two_maps,
):
    """Dashboard `conditional` cards key off attributes.current_map_id.

    The select's state is the user-renameable friendly name; the
    attribute is a stable integer that survives renames.
    """
    coord = coordinator_with_two_maps
    coord._active_map_id = 1

    from custom_components.dreame_a2_mower.select import (
        DreameA2ActiveMapSelect,
    )
    e = DreameA2ActiveMapSelect(coord)
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] == 1

    coord._active_map_id = 0
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] == 0

    coord._active_map_id = None
    attrs = e.extra_state_attributes
    assert attrs["current_map_id"] is None


# ---------------------------------------------------------------------------
# Guard: refuse map switch while mowing / paused
# ---------------------------------------------------------------------------

def _make_select_with_state(coordinator_with_two_maps, state_value):
    """Return a DreameA2ActiveMapSelect with coordinator.data.state set."""
    from custom_components.dreame_a2_mower.select import DreameA2ActiveMapSelect

    coord = coordinator_with_two_maps
    coord._active_map_id = 0  # currently on Map 1 (id=0)

    data = MagicMock()
    data.state = state_value
    coord.data = data

    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.dispatch_action = AsyncMock()

    sel = DreameA2ActiveMapSelect.__new__(DreameA2ActiveMapSelect)
    sel.coordinator = coord
    sel._optimistic_target_map_id = None
    sel.hass = coord.hass
    return sel, coord


def test_active_map_select_refuses_change_while_mowing(coordinator_with_two_maps):
    """Cloud rejects map switch during active mow; refuse client-side."""
    from custom_components.dreame_a2_mower.mower.state import State

    sel, coord = _make_select_with_state(coordinator_with_two_maps, State.WORKING)

    asyncio.run(sel.async_select_option("Back"))

    # Must NOT have dispatched the action
    coord.dispatch_action.assert_not_called()
    # Must have surfaced a persistent_notification
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args.args[0] == "persistent_notification"
    assert call_args.args[1] == "create"
    payload = call_args.args[2]
    assert DOMAIN in payload["notification_id"]


def test_active_map_select_refuses_change_while_paused(coordinator_with_two_maps):
    """Map switch is also blocked in paused state (mow session still active)."""
    from custom_components.dreame_a2_mower.mower.state import State

    sel, coord = _make_select_with_state(coordinator_with_two_maps, State.PAUSED)

    asyncio.run(sel.async_select_option("Back"))

    coord.dispatch_action.assert_not_called()
    coord.hass.services.async_call.assert_called_once()
    call_args = coord.hass.services.async_call.call_args
    assert call_args.args[0] == "persistent_notification"


def test_active_map_select_allows_change_when_idle(coordinator_with_two_maps):
    """Map switch dispatches normally when mower is idle/docked (STANDBY)."""
    from custom_components.dreame_a2_mower.mower.state import State

    sel, coord = _make_select_with_state(coordinator_with_two_maps, State.STANDBY)
    # async_write_ha_state is called before dispatch; provide a no-op stub
    sel.async_write_ha_state = MagicMock()

    # Patch async_call_later to avoid real HA event-loop dependency
    import custom_components.dreame_a2_mower.select as _select_mod
    original = getattr(_select_mod, "async_call_later", None)
    _select_mod.async_call_later = MagicMock()  # prevent import-time failure

    try:
        asyncio.run(sel.async_select_option("Back"))
    finally:
        if original is None:
            del _select_mod.async_call_later
        else:
            _select_mod.async_call_later = original

    # Should have dispatched SET_ACTIVE_MAP
    coord.dispatch_action.assert_called_once()
    # Should NOT have created a persistent notification
    coord.hass.services.async_call.assert_not_called()


def test_active_map_select_allows_change_when_charging(coordinator_with_two_maps):
    """Map switch dispatches normally when mower is charging."""
    from custom_components.dreame_a2_mower.mower.state import State

    sel, coord = _make_select_with_state(coordinator_with_two_maps, State.CHARGING)
    sel.async_write_ha_state = MagicMock()

    import custom_components.dreame_a2_mower.select as _select_mod
    _select_mod.async_call_later = MagicMock()

    asyncio.run(sel.async_select_option("Back"))

    coord.dispatch_action.assert_called_once()
    coord.hass.services.async_call.assert_not_called()
