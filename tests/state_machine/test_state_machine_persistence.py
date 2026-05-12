"""Persistence — load_persisted / save_persisted via a mock Store."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_save_persisted_writes_serialised_snapshot():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1000)
    store = MagicMock()
    store.async_save = AsyncMock()

    asyncio.run(sm.save_persisted(store))

    store.async_save.assert_awaited_once()
    saved = store.async_save.await_args.args[0]
    assert isinstance(saved, dict)
    assert saved["battery_percent"] == 87


def test_save_persisted_clears_dirty():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    sm = MowerStateMachine()
    sm.handle_mqtt_property(siid=3, piid=1, value=87, now_unix=1000)
    assert sm.is_dirty() is True

    store = MagicMock()
    store.async_save = AsyncMock()
    asyncio.run(sm.save_persisted(store))
    assert sm.is_dirty() is False


def test_load_persisted_restores_snapshot():
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot, CurrentActivity, Location,
    )
    sm = MowerStateMachine()
    initial = sm.snapshot()
    import dataclasses
    persisted_snap = dataclasses.replace(
        initial,
        current_activity=CurrentActivity.MOWING,
        location=Location.ON_LAWN,
        battery_percent=42,
    )
    store = MagicMock()
    store.async_load = AsyncMock(return_value=persisted_snap.to_dict())

    asyncio.run(sm.load_persisted(store))

    assert sm.snapshot() == persisted_snap
    # After loading authoritative state from disk, not dirty
    assert sm.is_dirty() is False


def test_load_persisted_handles_missing_store_data():
    """No saved data → snapshot stays at initial."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    sm = MowerStateMachine()
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)

    asyncio.run(sm.load_persisted(store))

    assert sm.snapshot() == StateSnapshot.initial()


def test_load_persisted_handles_corrupt_data_logs_warning():
    """Garbage in store → snapshot stays at initial (no exception)."""
    from custom_components.dreame_a2_mower.mower.state_machine import (
        MowerStateMachine,
    )
    from custom_components.dreame_a2_mower.mower.state_snapshot import (
        StateSnapshot,
    )
    sm = MowerStateMachine()
    store = MagicMock()
    # Missing required keys → from_dict raises KeyError
    store.async_load = AsyncMock(return_value={"junk": True})

    asyncio.run(sm.load_persisted(store))
    # Snapshot unchanged from initial
    assert sm.snapshot() == StateSnapshot.initial()
