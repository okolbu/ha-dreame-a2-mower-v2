"""Tests for the trail_render_width number entity (P4 render-styling)."""
from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.dreame_a2_mower.mower.state import MowerState
from custom_components.dreame_a2_mower.number import DreameA2TrailRenderWidthNumber


def _make_state(trail_render_width: int = 24) -> MowerState:
    return dataclasses.replace(MowerState(), trail_render_width=trail_render_width)


def _make_coord(width: int = 24) -> MagicMock:
    coord = MagicMock()
    coord.entry.entry_id = "test_entry"
    state = _make_state(width)
    # MowerState is a dataclass with slots; we need to return the real one
    # for native_value to read .trail_render_width correctly.
    coord.data = state
    coord.data.hardware_serial = None  # mower_unique_id falls back to entry_id
    return coord


class TestDreameA2TrailRenderWidthNumber:
    def test_class_attributes(self):
        cls = DreameA2TrailRenderWidthNumber
        assert cls._attr_native_min_value == 1
        assert cls._attr_native_max_value == 50
        assert cls._attr_native_step == 1
        assert cls._attr_native_unit_of_measurement == "px"
        assert cls._attr_has_entity_name is True

    def test_native_value_reads_state(self):
        coord = _make_coord(width=18)
        ent = DreameA2TrailRenderWidthNumber(coord)
        # native_value reads from coord.data.trail_render_width via the property
        assert ent.native_value == 18.0

    def test_native_value_default(self):
        coord = _make_coord()
        ent = DreameA2TrailRenderWidthNumber(coord)
        assert ent.native_value == 24.0

    @pytest.mark.asyncio
    async def test_set_native_value_updates_mower_state(self):
        coord = _make_coord(width=24)
        ent = DreameA2TrailRenderWidthNumber(coord)
        ent.hass = MagicMock()
        ent.hass.async_create_task = MagicMock()

        captured = {}

        def _capture(new_state):
            captured["state"] = new_state

        coord.async_set_updated_data.side_effect = _capture

        async def _fake_render():
            pass
        coord._render_main_view = _fake_render

        await ent.async_set_native_value(7.0)

        assert "state" in captured
        assert captured["state"].trail_render_width == 7

    @pytest.mark.asyncio
    async def test_set_native_value_coerces_float_to_int(self):
        coord = _make_coord(width=24)
        ent = DreameA2TrailRenderWidthNumber(coord)
        ent.hass = MagicMock()
        ent.hass.async_create_task = MagicMock()

        captured = {}

        def _capture(new_state):
            captured["state"] = new_state

        coord.async_set_updated_data.side_effect = _capture

        async def _fake_render():
            pass
        coord._render_main_view = _fake_render

        await ent.async_set_native_value(12.9)
        assert captured["state"].trail_render_width == 12  # int() truncates

    @pytest.mark.asyncio
    async def test_set_native_value_triggers_render(self):
        coord = _make_coord(width=24)
        ent = DreameA2TrailRenderWidthNumber(coord)

        task_created = []

        mock_hass = MagicMock()
        mock_hass.async_create_task.side_effect = lambda coro: task_created.append(coro)
        ent.hass = mock_hass

        async def _fake_render():
            return None
        coord._render_main_view = _fake_render

        await ent.async_set_native_value(10.0)

        # _render_main_view should have been scheduled
        assert len(task_created) == 1


class TestMowerStateTrailRenderWidth:
    def test_default_value(self):
        state = MowerState()
        assert state.trail_render_width == 24

    def test_dataclasses_replace(self):
        state = MowerState()
        new_state = dataclasses.replace(state, trail_render_width=5)
        assert new_state.trail_render_width == 5
        assert state.trail_render_width == 24  # original unchanged
