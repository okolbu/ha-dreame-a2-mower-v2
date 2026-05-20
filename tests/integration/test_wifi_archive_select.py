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
    coord.cloud_state.maps_by_id = maps
    coord._active_map_id = min(maps.keys()) if maps else None
    coord._wifi_render_entry = None
    coord.async_update_listeners = MagicMock()
    if wifi_candidates is not None:
        coord._wifi_archive_index = wifi_candidates

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


def test_set_wifi_render_entry_updates_state_and_fires_listeners():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._wifi_render_entry = None
    coord._wifi_body_cache = {}
    coord.hass = MagicMock()
    coord.async_update_listeners = MagicMock()

    coord.set_wifi_render_entry(0, "wifimap_1746000000.json")
    assert coord._wifi_render_entry == (0, "wifimap_1746000000.json")
    coord.async_update_listeners.assert_called_once()
    # Body not cached yet: a background load task must have been scheduled.
    coord.hass.async_create_task.assert_called_once()


def test_set_wifi_render_entry_none_resets():
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._wifi_render_entry = (0, "old.json")
    coord.async_update_listeners = MagicMock()

    coord.set_wifi_render_entry(None, None)
    assert coord._wifi_render_entry is None


def test_set_wifi_render_entry_map_id_none_still_sets_selection():
    """Picker passes map_id=None (correlation unsolved) — must NOT clear
    the render entry; only object_name=None clears it.

    Regression: prior logic ``if map_id is None or object_name is None: clear``
    treated map_id=None as "no selection" and wiped the picker's choice,
    making the camera unavailable.
    """
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = DreameA2MowerCoordinator.__new__(DreameA2MowerCoordinator)
    coord._wifi_render_entry = None
    coord._wifi_body_cache = {}
    coord.hass = MagicMock()
    coord.async_update_listeners = MagicMock()

    coord.set_wifi_render_entry(None, "ali_dreame/2026/05/11/x.txt")
    assert coord._wifi_render_entry == (None, "ali_dreame/2026/05/11/x.txt")
    coord.async_update_listeners.assert_called_once()
    # Body not cached yet: a background load task must have been scheduled.
    coord.hass.async_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# DreameA2WifiArchiveSelect
# ---------------------------------------------------------------------------

def test_wifi_archive_select_options_labeled():
    """Options are formatted as '[Map ?] YYYY-MM-DD HH:MM'."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveEntry

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_archive_index = [
        WifiArchiveEntry(
            object_name="a",
            unix_ts=1746000000,
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=0,
        ),
    ]
    coord._wifi_render_entry = None

    sel = DreameA2WifiArchiveSelect(coord)
    sel._rebuild_options()

    assert len(sel._attr_options) == 1
    opt = sel._attr_options[0]
    assert opt.startswith("[Map ?]")
    # Should contain a date string.
    assert "202" in opt


def test_wifi_archive_select_unknown_map_labeled():
    """All labels use '[Map ?]' — map_id correlation is unsolved."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveEntry

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_archive_index = [
        WifiArchiveEntry(
            object_name="a",
            unix_ts=1746000000,
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=0,
        ),
    ]
    coord._wifi_render_entry = None

    sel = DreameA2WifiArchiveSelect(coord)
    sel._rebuild_options()
    assert sel._attr_options[0].startswith("[Map ?]")


def test_wifi_archive_select_on_select_calls_set_wifi_render_entry():
    """Selecting an option calls set_wifi_render_entry(None, object_name)."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveEntry

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_archive_index = [
        WifiArchiveEntry(
            object_name="wifimap_1746000000.json",
            unix_ts=1746000000,
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=0,
        ),
    ]
    coord._wifi_render_entry = None
    coord.set_wifi_render_entry = MagicMock()

    sel = DreameA2WifiArchiveSelect(coord)
    sel._rebuild_options()
    sel.async_write_ha_state = MagicMock()
    opt = sel._attr_options[0]
    asyncio.run(sel.async_select_option(opt))

    coord.set_wifi_render_entry.assert_called_once_with(None, "wifimap_1746000000.json")


def test_wifi_archive_select_labels_always_map_unknown():
    """Every label is [Map ?] regardless of inferred map_id from the entry."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveEntry

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_archive_index = [
        WifiArchiveEntry(
            object_name="wifimap_1700000001.json",
            unix_ts=1700000001,
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=1747000000,
        ),
        WifiArchiveEntry(
            object_name="wifimap_1700000002.json",
            unix_ts=1700000002,
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=1747000000,
        ),
    ]
    coord._wifi_render_entry = None
    ent = DreameA2WifiArchiveSelect(coord)
    ent._rebuild_options()
    # Should have 2 entries (not the placeholder), and BOTH start with "[Map ?] ".
    assert len(ent._attr_options) == 2
    for opt in ent._attr_options:
        assert opt.startswith("[Map ?] "), f"label {opt!r} missing [Map ?] prefix"


def test_wifi_archive_select_sorts_newest_first():
    """Picker labels sort by unix_ts newest-first."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveEntry

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_archive_index = [
        WifiArchiveEntry(
            object_name="wifimap_1700000001.json",
            unix_ts=1700000001,  # older
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=0,
        ),
        WifiArchiveEntry(
            object_name="wifimap_1700000099.json",
            unix_ts=1700000099,  # newer
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=0,
        ),
    ]
    coord._wifi_render_entry = None
    ent = DreameA2WifiArchiveSelect(coord)
    ent._rebuild_options()
    # First option's underlying entry has the newer unix_ts.
    first_entry = ent._label_to_entry[ent._attr_options[0]]
    second_entry = ent._label_to_entry[ent._attr_options[1]]
    assert first_entry.unix_ts > second_entry.unix_ts


def test_wifi_archive_select_select_option_sets_render_entry_with_map_none():
    """Selecting a label calls coordinator.set_wifi_render_entry(None, object_name)."""
    from custom_components.dreame_a2_mower.select import DreameA2WifiArchiveSelect
    from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveEntry

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_archive_index = [
        WifiArchiveEntry(
            object_name="wifimap_1700000001.json",
            unix_ts=1700000001,
            width=4, height=4, resolution=2,
            startX=0, startY=0,
            first_seen_unix=0,
        ),
    ]
    coord._wifi_render_entry = None
    coord.set_wifi_render_entry = MagicMock()
    ent = DreameA2WifiArchiveSelect(coord)
    ent._rebuild_options()
    ent.async_write_ha_state = MagicMock()
    label = ent._attr_options[0]
    asyncio.run(ent.async_select_option(label))
    coord.set_wifi_render_entry.assert_called_once_with(None, "wifimap_1700000001.json")
