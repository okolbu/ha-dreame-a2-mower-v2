"""Pending-finalize wait task: completes on task-idle, charging, or timeout.

Tests for _wait_for_dock_return in _SessionMixin.  The method is exercised
via a lightweight MagicMock stand-in (no HA imports required).
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_wait_resolves_when_task_idle_event_fires():
    """Resolves with 'task_idle' when the event is set before timeout."""
    coord = MagicMock()
    coord._pending_finalize_done = None
    coord._pending_finalize_done_reason = None

    from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin

    coord._wait_for_dock_return = _SessionMixin._wait_for_dock_return.__get__(coord)

    async def fire_event():
        await asyncio.sleep(0.05)
        coord._pending_finalize_done_reason = "task_idle"
        coord._pending_finalize_done.set()

    asyncio.create_task(fire_event())
    result = await coord._wait_for_dock_return(timeout_s=1)
    assert result == "task_idle"
    # finally block must clear the event slot
    assert coord._pending_finalize_done is None


@pytest.mark.asyncio
async def test_wait_resolves_when_charging_event_fires():
    """Resolves with 'charging' when the charging signal fires before timeout."""
    coord = MagicMock()
    coord._pending_finalize_done = None
    coord._pending_finalize_done_reason = None

    from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin

    coord._wait_for_dock_return = _SessionMixin._wait_for_dock_return.__get__(coord)

    async def fire_event():
        await asyncio.sleep(0.05)
        coord._pending_finalize_done_reason = "charging"
        coord._pending_finalize_done.set()

    asyncio.create_task(fire_event())
    result = await coord._wait_for_dock_return(timeout_s=1)
    assert result == "charging"
    assert coord._pending_finalize_done is None


@pytest.mark.asyncio
async def test_wait_times_out_when_no_signal():
    """Returns 'timeout' when neither task_idle nor charging fires in time."""
    coord = MagicMock()
    coord._pending_finalize_done = None
    coord._pending_finalize_done_reason = None

    from custom_components.dreame_a2_mower.coordinator._session import _SessionMixin

    coord._wait_for_dock_return = _SessionMixin._wait_for_dock_return.__get__(coord)

    result = await coord._wait_for_dock_return(timeout_s=0.1)
    assert result == "timeout"
    # finally block must clear the event slot even on timeout
    assert coord._pending_finalize_done is None
