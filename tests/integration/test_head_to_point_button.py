"""Per-map Head-to-point button: availability + dispatch to start_go_to_point."""
from unittest.mock import AsyncMock

from custom_components.dreame_a2_mower.const import DOMAIN
from custom_components.dreame_a2_mower.mower.state import MowerState


def test_unique_id_and_device_are_per_map(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.button import DreameA2HeadToPointButton
    coord = coordinator_with_two_maps
    coord.data = MowerState()
    b0 = DreameA2HeadToPointButton(coord, map_id=0)
    assert b0._attr_unique_id == "G2408053AEE0006232_map_0_head_to_point"
    assert b0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_available_only_when_point_selected_for_this_map(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.button import DreameA2HeadToPointButton
    coord = coordinator_with_two_maps
    b0 = DreameA2HeadToPointButton(coord, map_id=0)
    b1 = DreameA2HeadToPointButton(coord, map_id=1)
    coord.data = MowerState(active_selection_point=(0, 1))
    assert b0.available is True
    assert b1.available is False
    coord.data = MowerState(active_selection_point=None)
    assert b0.available is False


async def test_press_dispatches_start_go_to_point(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.button import DreameA2HeadToPointButton
    coord = coordinator_with_two_maps
    coord.start_go_to_point = AsyncMock()
    coord.data = MowerState(active_selection_point=(0, 5))
    b0 = DreameA2HeadToPointButton(coord, map_id=0)
    await b0.async_press()
    coord.start_go_to_point.assert_awaited_once_with(map_id=0, point_id=5)


async def test_press_noop_when_selection_for_other_map(coordinator_with_two_maps):
    from custom_components.dreame_a2_mower.button import DreameA2HeadToPointButton
    coord = coordinator_with_two_maps
    coord.start_go_to_point = AsyncMock()
    coord.data = MowerState(active_selection_point=(0, 5))
    b1 = DreameA2HeadToPointButton(coord, map_id=1)
    await b1.async_press()
    coord.start_go_to_point.assert_not_awaited()
