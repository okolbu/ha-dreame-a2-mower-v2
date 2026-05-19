"""Tests for the DreameA2ActionModeSelect entity.

Recurring bug pattern: selecting a new action_mode used to take 1-2 minutes
to redraw the live-map preview because async_select_option only broadcast
the new state (action_mode field) without kicking off `_render_main_view`,
so `_main_view_png` stayed stale until the next telemetry-driven render
fired. The camera entity rotates its access_token only when the PNG bytes
change AND a coordinator broadcast fires — the broadcast from the state
change wasn't enough on its own.

These tests pin the contract: the select must kick off the render AND
broadcast again afterwards so the camera entity sees the new PNG and
busts the browser image-URL cache.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.mower.state import ActionMode, MowerState
from custom_components.dreame_a2_mower.select import DreameA2ActionModeSelect


def _make_state(action_mode: ActionMode = ActionMode.ALL_AREAS) -> MowerState:
    return dataclasses.replace(MowerState(), action_mode=action_mode)


def _make_coord(action_mode: ActionMode = ActionMode.ALL_AREAS) -> MagicMock:
    coord = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = _make_state(action_mode)
    coord.data.hardware_serial = None  # mower_unique_id falls back to entry_id
    return coord


class TestDreameA2ActionModeSelect:
    @pytest.mark.asyncio
    async def test_async_select_option_triggers_render_main_view(self):
        """Selecting a new option must await _render_main_view so the
        live-preview PNG reflects the change immediately."""
        coord = _make_coord(action_mode=ActionMode.ALL_AREAS)
        coord._render_main_view = AsyncMock()
        ent = DreameA2ActionModeSelect(coord)
        ent.hass = MagicMock()

        await ent.async_select_option(ActionMode.EDGE.value)

        coord._render_main_view.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_select_option_broadcasts_after_render(self):
        """After the render completes, async_update_listeners must be
        called so the camera entity rotates its access_token and the
        browser refetches the updated image."""
        coord = _make_coord(action_mode=ActionMode.ALL_AREAS)
        call_order: list[str] = []

        async def _fake_render():
            call_order.append("render")

        coord._render_main_view = _fake_render
        coord.async_update_listeners = MagicMock(
            side_effect=lambda: call_order.append("broadcast")
        )
        coord.async_set_updated_data = MagicMock(
            side_effect=lambda _: call_order.append("set_data")
        )

        ent = DreameA2ActionModeSelect(coord)
        ent.hass = MagicMock()

        await ent.async_select_option(ActionMode.SPOT.value)

        # The state-broadcast happens first (so listeners see the new
        # action_mode), then the render runs, then the post-render
        # broadcast fires.
        assert call_order == ["set_data", "render", "broadcast"]

    @pytest.mark.asyncio
    async def test_async_select_option_updates_action_mode_in_state(self):
        """Sanity: the new action_mode lands in the broadcast state."""
        coord = _make_coord(action_mode=ActionMode.ALL_AREAS)
        captured: dict = {}

        def _capture(new_state):
            captured["state"] = new_state

        coord.async_set_updated_data.side_effect = _capture
        coord._render_main_view = AsyncMock()

        ent = DreameA2ActionModeSelect(coord)
        ent.hass = MagicMock()

        await ent.async_select_option(ActionMode.ZONE.value)

        assert captured["state"].action_mode == ActionMode.ZONE
