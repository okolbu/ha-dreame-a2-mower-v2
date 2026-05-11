"""Tests for DreameA2WifiViewSelect (WiFi viewer picker)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def _make_map(name: str | None = None):
    m = MagicMock()
    m.name = name
    return m


def _make_coordinator(maps: dict):
    coord = MagicMock()
    coord._cached_maps_by_id = maps
    coord._active_map_id = min(maps.keys()) if maps else None
    coord._wifi_view_map_id = None
    coord.async_update_listeners = MagicMock()
    # Wire up the real set_wifi_view_map_id logic.
    def _set_wifi_view(map_id):
        coord._wifi_view_map_id = map_id
        coord.async_update_listeners()
    coord.set_wifi_view_map_id = _set_wifi_view
    return coord


def _make_entity(coord):
    from custom_components.dreame_a2_mower.select import DreameA2WifiViewSelect
    from custom_components.dreame_a2_mower._devices import mower_unique_id, mower_device_info
    e = DreameA2WifiViewSelect.__new__(DreameA2WifiViewSelect)
    e.coordinator = coord
    e._attr_unique_id = "wifi_view"
    e._attr_device_info = {}
    return e


def test_wifi_view_select_options_match_cached_maps():
    coord = _make_coordinator({0: _make_map("Front"), 1: _make_map("Back")})
    e = _make_entity(coord)
    opts = e.options
    assert "Front" in opts
    assert "Back" in opts
    assert len(opts) == 2


def test_wifi_view_select_options_fallback_names():
    """When map has no name, option is 'Map N'."""
    coord = _make_coordinator({0: _make_map(None), 1: _make_map(None)})
    e = _make_entity(coord)
    opts = e.options
    assert "Map 1" in opts
    assert "Map 2" in opts


def test_wifi_view_select_options_empty_maps():
    """No cached maps → single sentinel option."""
    coord = _make_coordinator({})
    e = _make_entity(coord)
    assert e.options == ["(no maps)"]


def test_wifi_view_select_current_option_reflects_active_map():
    """Before any pick, current_option follows active_map_id."""
    coord = _make_coordinator({0: _make_map("Front"), 1: _make_map("Back")})
    coord._active_map_id = 1
    coord._wifi_view_map_id = None
    e = _make_entity(coord)
    assert e.current_option == "Back"


def test_wifi_view_select_current_option_reflects_explicit_pick():
    coord = _make_coordinator({0: _make_map("Front"), 1: _make_map("Back")})
    coord._wifi_view_map_id = 0
    e = _make_entity(coord)
    assert e.current_option == "Front"


def test_wifi_view_select_change_updates_coordinator_state():
    coord = _make_coordinator({0: _make_map("Front"), 1: _make_map("Back")})
    e = _make_entity(coord)
    asyncio.run(e.async_select_option("Back"))
    assert coord._wifi_view_map_id == 1
    assert coord.async_update_listeners.called


def test_wifi_view_select_ignores_no_maps_sentinel():
    coord = _make_coordinator({})
    e = _make_entity(coord)
    # Should not raise, should not call set_wifi_view_map_id
    asyncio.run(e.async_select_option("(no maps)"))
    assert coord._wifi_view_map_id is None


def test_wifi_selected_camera_follows_view_select():
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera
    coord = _make_coordinator({0: _make_map("Front"), 1: _make_map("Back")})
    coord._wifi_map_by_id = {
        0: {"_object_name": "a", "width": 10, "height": 10, "data": [1, 1, 1, 1]},
    }
    coord._wifi_view_map_id = 0

    cam = DreameA2WifiSelectedCamera.__new__(DreameA2WifiSelectedCamera)
    cam.coordinator = coord
    cam._attr_unique_id = "wifi_selected"
    cam._attr_device_info = {}

    assert cam.available
    coord._wifi_view_map_id = 1   # Map 2 has no data
    assert not cam.available


def test_wifi_selected_camera_falls_back_to_active_map():
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera
    coord = _make_coordinator({0: _make_map("Front"), 1: _make_map("Back")})
    coord._active_map_id = 0
    coord._wifi_view_map_id = None
    coord._wifi_map_by_id = {
        0: {"_object_name": "a", "width": 5, "height": 5, "data": [0] * 25},
    }

    cam = DreameA2WifiSelectedCamera.__new__(DreameA2WifiSelectedCamera)
    cam.coordinator = coord
    cam._attr_unique_id = "wifi_selected"
    cam._attr_device_info = {}

    assert cam._selected_map_id() == 0
    assert cam.available
