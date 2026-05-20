"""Unified per-map mowing-mode picker."""
import asyncio
from unittest.mock import AsyncMock, MagicMock


def _make_coord_with_map():
    coord = MagicMock()
    coord.entry.entry_id = "fake"
    map0 = MagicMock()
    map0.name = "Front lawn"
    z1 = MagicMock(); z1.zone_id = 1; z1.name = "Lawn A"
    z2 = MagicMock(); z2.zone_id = 2; z2.name = "Lawn B"
    map0.mowing_zones = (z1, z2)
    sp1 = MagicMock(); sp1.spot_id = 5; sp1.name = "Spot near tree"
    map0.spot_zones = (sp1,)
    coord._cached_maps_by_id = {0: map0}
    coord.cloud_state.maps_by_id = coord._cached_maps_by_id
    coord.data = MagicMock()
    return coord


def test_mowing_mode_options_listing():
    from custom_components.dreame_a2_mower.select import DreameA2MowingModeSelect
    coord = _make_coord_with_map()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    opts = sel.options
    assert "All areas" in opts
    assert "Edge" in opts
    assert "Zone: Lawn A" in opts
    assert "Zone: Lawn B" in opts
    assert "Spot: Spot near tree" in opts


def test_select_all_areas_dispatches():
    from custom_components.dreame_a2_mower.select import DreameA2MowingModeSelect
    coord = _make_coord_with_map()
    coord.start_mowing_all_areas = AsyncMock()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    sel.async_write_ha_state = MagicMock()
    asyncio.run(sel.async_select_option("All areas"))
    coord.start_mowing_all_areas.assert_awaited_once_with(map_id=0)


def test_select_edge_dispatches():
    from custom_components.dreame_a2_mower.select import DreameA2MowingModeSelect
    coord = _make_coord_with_map()
    coord.start_mowing_edge = AsyncMock()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    sel.async_write_ha_state = MagicMock()
    asyncio.run(sel.async_select_option("Edge"))
    coord.start_mowing_edge.assert_awaited_once_with(map_id=0)


def test_select_zone_dispatches_with_id():
    from custom_components.dreame_a2_mower.select import DreameA2MowingModeSelect
    coord = _make_coord_with_map()
    coord.start_mowing_zone = AsyncMock()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    sel.async_write_ha_state = MagicMock()
    asyncio.run(sel.async_select_option("Zone: Lawn B"))
    coord.start_mowing_zone.assert_awaited_once_with(map_id=0, zone_id=2)


def test_select_spot_dispatches_with_id():
    from custom_components.dreame_a2_mower.select import DreameA2MowingModeSelect
    coord = _make_coord_with_map()
    coord.start_mowing_spot = AsyncMock()
    sel = DreameA2MowingModeSelect(coord, map_id=0)
    sel.async_write_ha_state = MagicMock()
    asyncio.run(sel.async_select_option("Spot: Spot near tree"))
    coord.start_mowing_spot.assert_awaited_once_with(map_id=0, spot_id=5)


def test_start_mowing_switches_active_map_first():
    """All four wrappers route through _ensure_active_map(map_id)."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._ensure_active_map = AsyncMock()
    coord.dispatch_action = AsyncMock()

    async def run():
        await coord.start_mowing_all_areas(map_id=2)
        await coord.start_mowing_edge(map_id=2)
        await coord.start_mowing_zone(map_id=2, zone_id=5)
        await coord.start_mowing_spot(map_id=2, spot_id=7)

    asyncio.run(run())
    # All four await _ensure_active_map(2)
    assert coord._ensure_active_map.await_count == 4
    for call in coord._ensure_active_map.await_args_list:
        # Either positional (2,) or kw (map_id=2)
        assert (call.args == (2,)) or call.kwargs == {"map_id": 2}
