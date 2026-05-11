"""Tests for WiFi archive select + coordinator archive methods."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_map(name: str | None = None, bx1=0.0, by1=0.0, bx2=1000.0, by2=1000.0):
    m = MagicMock()
    m.name = name
    # bx1/by1/bx2/by2 represent cloud-frame extent in cm.
    m.bx1 = bx1; m.by1 = by1; m.bx2 = bx2; m.by2 = by2
    m.pixel_size_mm = 25.0
    return m


def _make_coordinator(maps: dict, wifi_candidates=None):
    coord = MagicMock()
    coord._cached_maps_by_id = maps
    coord._active_map_id = min(maps.keys()) if maps else None
    coord._wifi_render_entry = None
    coord.async_update_listeners = MagicMock()
    if wifi_candidates is not None:
        coord.list_wifi_archive_entries = MagicMock(return_value=wifi_candidates)

    def _set_wifi_render_entry(map_id, object_name):
        coord._wifi_render_entry = None if map_id is None else (map_id, object_name)
        coord.async_update_listeners()

    coord.set_wifi_render_entry = _set_wifi_render_entry
    return coord


# ---------------------------------------------------------------------------
# cloud_client.list_wifi_candidates
# ---------------------------------------------------------------------------

def test_list_wifi_candidates_returns_all_with_no_extents():
    """Without map_extents all candidates are returned with map_id=None."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._wifi_map_cache = {}

    # OBJ probe returns two object names.
    obj_resp = {"out": [{"d": {"name": ["wifimap_1746000000.json", "wifimap_1745000000.json"]}}]}
    client.action = MagicMock(return_value=obj_resp)

    # _decode_or_none path: provide signed URL + downloadable JSON for each.
    def _fake_url(obj_name):
        return f"https://oss/{obj_name}"

    def _fake_get_file(url):
        import json
        ts = int(url.split("_")[-1].replace(".json", ""))
        return json.dumps({
            "data": [1] * 4,
            "width": 2, "height": 2, "resolution": 2,
            "startX": 100, "startY": 100,
        }).encode()

    client.get_interim_file_url = _fake_url
    client.get_file = _fake_get_file

    results = client.list_wifi_candidates(map_extents={})
    assert len(results) == 2
    # Newest first (1746000000 > 1745000000).
    assert results[0]["unix_ts"] == 1746000000
    assert results[1]["unix_ts"] == 1745000000
    # No geometry match possible — map_id is None.
    assert all(r["map_id"] is None for r in results)


def test_list_wifi_candidates_assigns_map_id_by_geometry():
    """Geometry matching assigns the correct map_id to each candidate."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._wifi_map_cache = {}

    # Two wifimap objects with different extents.
    obj_resp = {"out": [{"d": {"name": [
        "wifimap_1746000000.json",   # center ~ (250, 250) → inside map 0 (0-500)
        "wifimap_1745000000.json",   # center ~ (1250, 1250) → inside map 1 (1000-1500)
    ]}}]}
    client.action = MagicMock(return_value=obj_resp)

    import json

    def _fake_url(obj_name):
        return f"https://oss/{obj_name}"

    def _fake_get_file(url):
        if "1746000000" in url:
            # startX=100, startY=100, width=4, height=4, res=2 →
            # w_cm=4*2*10=80, cx=100+40=140; cy=100+40=140 → inside map0(0-500)
            return json.dumps({
                "data": [1] * 16, "width": 4, "height": 4,
                "resolution": 2, "startX": 100, "startY": 100,
            }).encode()
        else:
            # startX=1100, startY=1100, width=4, height=4, res=2 →
            # cx=1100+40=1140, cy=1100+40=1140 → inside map1(1000-1500)
            return json.dumps({
                "data": [1] * 16, "width": 4, "height": 4,
                "resolution": 2, "startX": 1100, "startY": 1100,
            }).encode()

    client.get_interim_file_url = _fake_url
    client.get_file = _fake_get_file

    map_extents = {
        0: (0.0, 0.0, 500.0, 500.0),
        1: (1000.0, 1000.0, 1500.0, 1500.0),
    }
    results = client.list_wifi_candidates(map_extents=map_extents)
    assert len(results) == 2
    by_ts = {r["unix_ts"]: r for r in results}
    assert by_ts[1746000000]["map_id"] == 0
    assert by_ts[1745000000]["map_id"] == 1


def test_list_wifi_candidates_empty_when_no_objects():
    """Returns [] when OBJ probe has no names."""
    from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient

    client = DreameA2CloudClient.__new__(DreameA2CloudClient)
    client._wifi_map_cache = {}
    client.action = MagicMock(return_value={"out": [{"d": {"name": []}}]})
    client.get_interim_file_url = MagicMock()
    client.get_file = MagicMock()

    results = client.list_wifi_candidates(map_extents={})
    assert results == []


# ---------------------------------------------------------------------------
# coordinator.list_wifi_archive_entries + set_wifi_render_entry
# ---------------------------------------------------------------------------

def test_coordinator_list_wifi_archive_entries_sorted_newest_first():
    """list_wifi_archive_entries returns entries from _wifi_archive_cache, newest-first.

    Since v1.0.5a8 (F11 fix) the method reads ONLY from _wifi_archive_cache —
    no cloud I/O. The cloud is never called from the event loop.
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._cached_maps_by_id = {0: _make_map("Front"), 1: _make_map("Back")}
    coord._cloud = MagicMock()

    entries = [
        {"object_name": "a", "unix_ts": 1000, "map_id": 0,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
        {"object_name": "b", "unix_ts": 2000, "map_id": 1,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
        {"object_name": "c", "unix_ts": 1500, "map_id": None,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
    ]
    # Populate the cache directly (as _refresh_wifi_map would do in production).
    coord._wifi_archive_cache = entries

    result = coord.list_wifi_archive_entries()
    assert result[0]["unix_ts"] == 2000
    assert result[1]["unix_ts"] == 1500
    assert result[2]["unix_ts"] == 1000
    # CRITICAL: cloud must NOT be called — event-loop safety.
    coord._cloud.list_wifi_candidates.assert_not_called()


def test_wifi_archive_cache_returns_from_cache_not_cloud():
    """list_wifi_archive_entries reads _wifi_archive_cache, never calls cloud.

    This is the F11 regression guard: a blocked cloud call on the event
    loop (80001 timeout) must not make the picker show '(no WiFi maps)'.
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._cached_maps_by_id = {}
    coord._cloud = MagicMock()

    # Simulate what _refresh_wifi_map stores after a successful cache fill.
    coord._wifi_archive_cache = [
        {"object_name": "wifimap_1746000000.json", "unix_ts": 1746000000, "map_id": 0,
         "startX": 100.0, "startY": 100.0, "width": 8, "height": 8, "resolution": 2},
    ]

    result = coord.list_wifi_archive_entries()

    # Returns the cached entry.
    assert len(result) == 1
    assert result[0]["object_name"] == "wifimap_1746000000.json"
    # Cloud is never touched — regardless of how many times called.
    coord._cloud.list_wifi_candidates.assert_not_called()

    # Second call (simulating _handle_coordinator_update → _rebuild_options)
    result2 = coord.list_wifi_archive_entries()
    assert len(result2) == 1
    coord._cloud.list_wifi_candidates.assert_not_called()


def test_wifi_archive_cache_empty_returns_empty_list():
    """Before any _refresh_wifi_map runs, list_wifi_archive_entries returns []."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._wifi_archive_cache = []
    coord._cloud = MagicMock()

    result = coord.list_wifi_archive_entries()
    assert result == []
    coord._cloud.list_wifi_candidates.assert_not_called()


def test_set_wifi_render_entry_updates_state_and_fires_listeners():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._wifi_render_entry = None
    coord.async_update_listeners = MagicMock()

    coord.set_wifi_render_entry(0, "wifimap_1746000000.json")
    assert coord._wifi_render_entry == (0, "wifimap_1746000000.json")
    coord.async_update_listeners.assert_called_once()


def test_set_wifi_render_entry_none_resets():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._wifi_render_entry = (0, "old.json")
    coord.async_update_listeners = MagicMock()

    coord.set_wifi_render_entry(None, None)
    assert coord._wifi_render_entry is None


# ---------------------------------------------------------------------------
# DreameA2WifiArchiveSelect
# ---------------------------------------------------------------------------

def test_wifi_archive_select_options_labeled():
    """Options are formatted as '[Map N] YYYY-MM-DD HH:MM'."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect

    entries = [
        {"object_name": "a", "unix_ts": 1746000000, "map_id": 0,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
    ]
    coord = _make_coordinator({0: _make_map("Front")}, wifi_candidates=entries)

    sel = DreameA2WifiArchiveSelect.__new__(DreameA2WifiArchiveSelect)
    sel.coordinator = coord
    sel._attr_unique_id = "wifi_archive"
    sel._attr_device_info = {}
    sel._attr_options = []
    sel._attr_current_option = sel._placeholder = "(no WiFi maps)"

    sel._rebuild_options()

    assert len(sel._attr_options) == 1
    opt = sel._attr_options[0]
    assert opt.startswith("[Map 1]")
    # Should contain a date string.
    assert "202" in opt


def test_wifi_archive_select_unknown_map_labeled():
    """Candidates with map_id=None are labeled '[Unknown map]'."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect

    entries = [
        {"object_name": "a", "unix_ts": 1746000000, "map_id": None,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
    ]
    coord = _make_coordinator({}, wifi_candidates=entries)

    sel = DreameA2WifiArchiveSelect.__new__(DreameA2WifiArchiveSelect)
    sel.coordinator = coord
    sel._attr_unique_id = "wifi_archive"
    sel._attr_device_info = {}
    sel._attr_options = []
    sel._attr_current_option = sel._placeholder = "(no WiFi maps)"

    sel._rebuild_options()
    assert sel._attr_options[0].startswith("[Unknown map]")


def test_wifi_archive_select_on_select_calls_set_wifi_render_entry():
    """Selecting an option updates coordinator._wifi_render_entry."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect

    entries = [
        {"object_name": "wifimap_1746000000.json", "unix_ts": 1746000000, "map_id": 0,
         "startX": 0.0, "startY": 0.0, "width": 4, "height": 4, "resolution": 2},
    ]
    coord = _make_coordinator({0: _make_map("Front")}, wifi_candidates=entries)

    sel = DreameA2WifiArchiveSelect.__new__(DreameA2WifiArchiveSelect)
    sel.coordinator = coord
    sel._attr_unique_id = "wifi_archive"
    sel._attr_device_info = {}
    sel._attr_options = []
    sel._attr_current_option = sel._placeholder = "(no WiFi maps)"
    sel.async_write_ha_state = MagicMock()

    sel._rebuild_options()
    opt = sel._attr_options[0]
    asyncio.run(sel.async_select_option(opt))

    assert coord._wifi_render_entry == (0, "wifimap_1746000000.json")
    coord.async_update_listeners.assert_called()
