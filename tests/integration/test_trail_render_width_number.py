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
    async def test_set_native_value_awaits_main_view_render(self):
        """The live-map preview must be re-rendered with the new width
        in-band so it's updated before this call returns."""
        coord = _make_coord(width=24)
        coord._render_main_view = AsyncMock()
        coord._picked_session_summary = None
        ent = DreameA2TrailRenderWidthNumber(coord)
        ent.hass = MagicMock()

        await ent.async_set_native_value(10.0)

        coord._render_main_view.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_native_value_rerenders_picked_work_log(self):
        """When a work-log session is currently picked, changing the
        trail width must re-render that work-log too — otherwise the
        static replay image keeps the old stroke thickness until the
        user re-picks the session."""
        coord = _make_coord(width=24)
        coord._render_main_view = AsyncMock()
        coord.render_work_log_session = AsyncMock()
        coord._picked_session_summary = {
            "filename": "session-2026-05-19.json",
            "md5": "abc",
        }
        ent = DreameA2TrailRenderWidthNumber(coord)
        ent.hass = MagicMock()

        await ent.async_set_native_value(10.0)

        coord.render_work_log_session.assert_awaited_once_with(
            "session-2026-05-19.json"
        )

    @pytest.mark.asyncio
    async def test_set_native_value_skips_work_log_when_no_picked_session(self):
        """No picked session → no work-log re-render attempt."""
        coord = _make_coord(width=24)
        coord._render_main_view = AsyncMock()
        coord.render_work_log_session = AsyncMock()
        coord._picked_session_summary = None
        ent = DreameA2TrailRenderWidthNumber(coord)
        ent.hass = MagicMock()

        await ent.async_set_native_value(10.0)

        coord.render_work_log_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_set_native_value_broadcasts_after_renders(self):
        """After both renders complete, async_update_listeners must
        fire so both DreameA2MapCamera and DreameA2WorkLogCamera see
        the new PNGs and rotate their access_tokens."""
        coord = _make_coord(width=24)
        call_order: list[str] = []

        async def _fake_main():
            call_order.append("render_main")

        async def _fake_work_log(_filename):
            call_order.append("render_work_log")

        coord._render_main_view = _fake_main
        coord.render_work_log_session = _fake_work_log
        coord._picked_session_summary = {"filename": "x.json"}
        coord.async_update_listeners = MagicMock(
            side_effect=lambda: call_order.append("broadcast")
        )
        coord.async_set_updated_data = MagicMock(
            side_effect=lambda _: call_order.append("set_data")
        )

        ent = DreameA2TrailRenderWidthNumber(coord)
        ent.hass = MagicMock()

        await ent.async_set_native_value(10.0)

        assert call_order == [
            "set_data", "render_main", "render_work_log", "broadcast",
        ]


class TestMowerStateTrailRenderWidth:
    def test_default_value(self):
        state = MowerState()
        assert state.trail_render_width == 24

    def test_dataclasses_replace(self):
        state = MowerState()
        new_state = dataclasses.replace(state, trail_render_width=5)
        assert new_state.trail_render_width == 5
        assert state.trail_render_width == 24  # original unchanged
