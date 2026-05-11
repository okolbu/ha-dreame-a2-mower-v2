"""Tests for lawn_mower.py state restoration across HA restarts.

Covers:
- DreameA2LawnMower.async_added_to_hass restores state from RestoreEntity
- DreameA2MowerCoordinator._persist_state_on_change writes on updates
- DreameA2MowerCoordinator._restore_persisted_state restores on first refresh
"""
from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.dreame_a2_mower.mower.state import MowerState, State


# ---------------------------------------------------------------------------
# Helper: build a minimal DreameA2LawnMower without real HA setup
# ---------------------------------------------------------------------------

def _make_lawn_mower(coordinator, *, mower_state: MowerState | None = None):
    """Construct a DreameA2LawnMower bypassing HA entity registration."""
    from custom_components.dreame_a2_mower.lawn_mower import DreameA2LawnMower

    entity = DreameA2LawnMower.__new__(DreameA2LawnMower)
    entity.coordinator = coordinator
    if mower_state is not None:
        coordinator.data = mower_state
    else:
        coordinator.data = MowerState()
    return entity


# ---------------------------------------------------------------------------
# Test 1: lawn_mower restores state on async_added_to_hass
# ---------------------------------------------------------------------------

def _run_added_to_hass(entity, last_ha_state):
    """Run async_added_to_hass on the entity with a mocked last state.

    Injects async_get_last_state directly on the entity instance to avoid
    relying on the stub RestoreEntity base class's method resolution.
    Patches the RestoreEntity.async_added_to_hass super() call to a no-op.
    """
    entity.async_get_last_state = AsyncMock(return_value=last_ha_state)

    async def run():
        # Patch the MRO super() call to RestoreEntity.async_added_to_hass
        import homeassistant.helpers.restore_state as rs_mod
        original = getattr(rs_mod.RestoreEntity, "async_added_to_hass", None)
        rs_mod.RestoreEntity.async_added_to_hass = AsyncMock()
        try:
            await entity.async_added_to_hass()
        finally:
            if original is None:
                try:
                    delattr(rs_mod.RestoreEntity, "async_added_to_hass")
                except AttributeError:
                    pass
            else:
                rs_mod.RestoreEntity.async_added_to_hass = original

    asyncio.run(run())


def test_lawn_mower_restores_mowing_state_on_added_to_hass(coordinator_with_two_maps):
    """After HA restart, lawn_mower restores WORKING from last activity=mowing."""
    coord = coordinator_with_two_maps
    coord.data = MowerState()  # state is None (cold boot)
    coord.async_set_updated_data = MagicMock(side_effect=lambda d: setattr(coord, "data", d))

    last_state = MagicMock()
    last_state.state = "mowing"

    entity = _make_lawn_mower(coord)
    _run_added_to_hass(entity, last_state)

    coord.async_set_updated_data.assert_called_once()
    updated = coord.async_set_updated_data.call_args[0][0]
    assert updated.state == State.WORKING


def test_lawn_mower_restores_docked_state_on_added_to_hass(coordinator_with_two_maps):
    """lawn_mower restores STANDBY from last activity=docked."""
    coord = coordinator_with_two_maps
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock(side_effect=lambda d: setattr(coord, "data", d))

    last_state = MagicMock()
    last_state.state = "docked"

    entity = _make_lawn_mower(coord)
    _run_added_to_hass(entity, last_state)

    updated = coord.async_set_updated_data.call_args[0][0]
    assert updated.state == State.STANDBY


def test_lawn_mower_restores_paused_state(coordinator_with_two_maps):
    """lawn_mower restores PAUSED from last activity=paused."""
    coord = coordinator_with_two_maps
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock(side_effect=lambda d: setattr(coord, "data", d))

    last_state = MagicMock()
    last_state.state = "paused"

    entity = _make_lawn_mower(coord)
    _run_added_to_hass(entity, last_state)

    updated = coord.async_set_updated_data.call_args[0][0]
    assert updated.state == State.PAUSED


def test_lawn_mower_restores_returning_state(coordinator_with_two_maps):
    """lawn_mower restores RETURNING from last activity=returning."""
    coord = coordinator_with_two_maps
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock(side_effect=lambda d: setattr(coord, "data", d))

    last_state = MagicMock()
    last_state.state = "returning"

    entity = _make_lawn_mower(coord)
    _run_added_to_hass(entity, last_state)

    updated = coord.async_set_updated_data.call_args[0][0]
    assert updated.state == State.RETURNING


def test_lawn_mower_skips_restore_when_state_already_populated(coordinator_with_two_maps):
    """If coordinator already has live state, RestoreEntity result is ignored."""
    coord = coordinator_with_two_maps
    coord.async_set_updated_data = MagicMock()

    last_state = MagicMock()
    last_state.state = "mowing"

    # Provide live state via mower_state param so _make_lawn_mower doesn't reset it
    entity = _make_lawn_mower(coord, mower_state=MowerState(state=State.CHARGING))
    _run_added_to_hass(entity, last_state)

    coord.async_set_updated_data.assert_not_called()


def test_lawn_mower_skips_restore_when_last_state_is_unknown(coordinator_with_two_maps):
    """If last HA state was 'unknown', no restore is performed."""
    coord = coordinator_with_two_maps
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock()

    last_state = MagicMock()
    last_state.state = "unknown"

    entity = _make_lawn_mower(coord)
    _run_added_to_hass(entity, last_state)

    coord.async_set_updated_data.assert_not_called()


def test_lawn_mower_skips_restore_when_last_state_is_none(coordinator_with_two_maps):
    """If async_get_last_state returns None, no restore is performed."""
    coord = coordinator_with_two_maps
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock()

    entity = _make_lawn_mower(coord)
    _run_added_to_hass(entity, None)

    coord.async_set_updated_data.assert_not_called()


def test_lawn_mower_handles_unrecognized_state_gracefully(coordinator_with_two_maps):
    """Unrecognized state strings are logged and silently ignored."""
    coord = coordinator_with_two_maps
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock()

    last_state = MagicMock()
    last_state.state = "charging_turbo_boost"  # not a valid LawnMowerActivity

    entity = _make_lawn_mower(coord)
    _run_added_to_hass(entity, last_state)  # must not raise

    coord.async_set_updated_data.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: coordinator persists state on every update
# ---------------------------------------------------------------------------

def test_coordinator_persists_state_when_state_is_non_none(coordinator_with_two_maps):
    """_persist_state_on_change writes state name to the Store."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    coord.data = MowerState(state=State.WORKING)
    coord.hass = MagicMock()
    coord.hass.async_create_task = MagicMock()

    # Wire real method
    coord._state_persistence = MagicMock()
    coord._state_persistence.async_save = AsyncMock()
    coord._persist_state_on_change = (
        DreameA2MowerCoordinator._persist_state_on_change.__get__(coord)
    )

    coord._persist_state_on_change()

    # Must have scheduled a task (not blocked event loop)
    coord.hass.async_create_task.assert_called_once()
    # The coroutine that was scheduled should be an async_save call
    coro = coord.hass.async_create_task.call_args[0][0]
    # Run the coroutine to verify it calls async_save with the right payload
    asyncio.run(coro)
    coord._state_persistence.async_save.assert_called_once_with({"state": "WORKING"})


def test_coordinator_skips_persist_when_state_is_none(coordinator_with_two_maps):
    """_persist_state_on_change is a no-op when state is None."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    coord.data = MowerState()  # state=None
    coord.hass = MagicMock()
    coord.hass.async_create_task = MagicMock()
    coord._state_persistence = MagicMock()
    coord._persist_state_on_change = (
        DreameA2MowerCoordinator._persist_state_on_change.__get__(coord)
    )

    coord._persist_state_on_change()

    coord.hass.async_create_task.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: coordinator restores state on first refresh
# ---------------------------------------------------------------------------

def test_coordinator_restores_state_from_persistence(coordinator_with_two_maps):
    """_restore_persisted_state populates state from disk when state is None."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    coord.data = MowerState()  # state=None

    persisted_data = {"state": "WORKING"}
    coord._state_persistence = MagicMock()
    coord._state_persistence.async_load = AsyncMock(return_value=persisted_data)

    coord._restore_persisted_state = (
        DreameA2MowerCoordinator._restore_persisted_state.__get__(coord)
    )

    asyncio.run(coord._restore_persisted_state())

    assert coord.data.state == State.WORKING


def test_coordinator_skips_restore_when_state_already_set(coordinator_with_two_maps):
    """_restore_persisted_state is a no-op when coordinator already has live state."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    coord.data = MowerState(state=State.CHARGING)  # already set

    coord._state_persistence = MagicMock()
    coord._state_persistence.async_load = AsyncMock(return_value={"state": "WORKING"})

    coord._restore_persisted_state = (
        DreameA2MowerCoordinator._restore_persisted_state.__get__(coord)
    )

    asyncio.run(coord._restore_persisted_state())

    # State must remain CHARGING — the persisted value must not override it
    assert coord.data.state == State.CHARGING
    coord._state_persistence.async_load.assert_not_called()


def test_coordinator_skips_restore_when_no_persistence(coordinator_with_two_maps):
    """_restore_persisted_state is a no-op when the store has never been written."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    coord.data = MowerState()

    coord._state_persistence = MagicMock()
    coord._state_persistence.async_load = AsyncMock(return_value=None)

    coord._restore_persisted_state = (
        DreameA2MowerCoordinator._restore_persisted_state.__get__(coord)
    )

    asyncio.run(coord._restore_persisted_state())

    assert coord.data.state is None


def test_coordinator_handles_unknown_state_name_in_persistence(coordinator_with_two_maps):
    """Unrecognised state name in the store is silently dropped."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    coord.data = MowerState()

    coord._state_persistence = MagicMock()
    coord._state_persistence.async_load = AsyncMock(return_value={"state": "HYPERMODE"})

    coord._restore_persisted_state = (
        DreameA2MowerCoordinator._restore_persisted_state.__get__(coord)
    )

    asyncio.run(coord._restore_persisted_state())

    assert coord.data.state is None


def test_coordinator_handles_corrupt_persistence_dict(coordinator_with_two_maps):
    """Corrupt store content (non-dict) is silently ignored."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    coord.data = MowerState()

    coord._state_persistence = MagicMock()
    coord._state_persistence.async_load = AsyncMock(return_value="corrupted_string")

    coord._restore_persisted_state = (
        DreameA2MowerCoordinator._restore_persisted_state.__get__(coord)
    )

    asyncio.run(coord._restore_persisted_state())

    assert coord.data.state is None
