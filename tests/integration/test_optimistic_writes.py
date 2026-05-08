"""Tests for the entity-layer optimistic-update + revert pattern."""
from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import DreameA2MowingHeightNumber


def _make_coord(initial_value: int | None = 5):
    coord = object.__new__(DreameA2MowerCoordinator)
    coord.data = MowerState(settings_mowing_height=initial_value)
    coord._active_map_id = 0
    coord.entry = MagicMock()
    coord.entry.entry_id = "test"
    async def _stub_write_settings(*args, **kwargs):
        return True
    coord.write_settings = MagicMock(side_effect=_stub_write_settings)
    coord.hass = MagicMock()
    return coord


def test_number_entity_calls_write_settings_with_active_map_id():
    coord = _make_coord(5)
    ent = DreameA2MowingHeightNumber(coord)
    ent.async_write_ha_state = MagicMock()
    ent.hass = MagicMock()
    asyncio.run(ent.async_set_native_value(7.0))
    coord.write_settings.assert_called_once_with(
        map_id=0, field="mowingHeight", value=7
    )


def test_number_entity_optimistic_update_then_revert_on_failure():
    coord = _make_coord(5)
    async def _stub_write_settings_fail(*args, **kwargs):
        return False
    coord.write_settings = MagicMock(side_effect=_stub_write_settings_fail)
    coord.hass.services = MagicMock()
    async def _stub_async_call(*args, **kwargs):
        return None
    coord.hass.services.async_call = MagicMock(side_effect=_stub_async_call)
    ent = DreameA2MowingHeightNumber(coord)
    ent.async_write_ha_state = MagicMock()
    ent.hass = coord.hass
    ent.entity_id = "number.test"
    asyncio.run(ent.async_set_native_value(7.0))
    # After revert, state.settings_mowing_height should be back to 5
    assert coord.data.settings_mowing_height == 5
    # Notification should have been fired
    args, kwargs = coord.hass.services.async_call.call_args
    assert args[0] == "persistent_notification"
    assert args[1] == "create"
    assert "dreame_a2_write_fail_number.test" in kwargs["service_data"]["notification_id"]
