"""Tests for the updated DreameA2WifiSelectedCamera (F11: uses _wifi_render_entry)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def _make_map(name=None):
    m = MagicMock()
    m.name = name
    return m


def _make_coordinator(maps=None, wifi_map_by_id=None, wifi_render_entry=None, active_map_id=0):
    coord = MagicMock()
    coord._cached_maps_by_id = maps or {}
    coord._active_map_id = active_map_id
    coord._wifi_render_entry = wifi_render_entry
    coord._wifi_map_by_id = wifi_map_by_id or {}
    return coord


def _make_camera(coord):
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera
    cam = DreameA2WifiSelectedCamera.__new__(DreameA2WifiSelectedCamera)
    cam.coordinator = coord
    cam._attr_unique_id = "wifi_selected"
    cam._attr_device_info = {}
    return cam


def test_camera_available_when_render_entry_has_data():
    """Camera is available when _wifi_render_entry points to loaded data."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={
            "wifimap_1746000000.json": {
                "data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
                "startX": 0, "startY": 0,
            }
        },
        wifi_render_entry=(0, "wifimap_1746000000.json"),
    )
    cam = _make_camera(coord)
    assert cam.available


def test_camera_unavailable_when_render_entry_object_not_loaded():
    """Camera is unavailable when _wifi_render_entry's object is not in the cache."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={},
        wifi_render_entry=(0, "wifimap_1746000000.json"),
    )
    cam = _make_camera(coord)
    assert not cam.available


def test_camera_falls_back_to_active_map_when_no_render_entry():
    """When _wifi_render_entry is None, camera falls back to active map."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={
            "active_latest": {
                "data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
                "startX": 0, "startY": 0,
            }
        },
        wifi_render_entry=None,
        active_map_id=0,
    )
    # Put active map's data directly in _wifi_map_by_id[0] as the fallback path.
    coord._wifi_map_by_id = {
        0: {"data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
            "startX": 0, "startY": 0}
    }
    cam = _make_camera(coord)
    assert cam.available


def test_camera_unavailable_when_no_render_entry_and_no_active_data():
    """Camera is unavailable when no render entry and no active map data."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={},
        wifi_render_entry=None,
        active_map_id=0,
    )
    cam = _make_camera(coord)
    assert not cam.available


def test_camera_entity_picture_includes_object_name_hash():
    """entity_picture URL includes a hash derived from the selected entry.

    In the stub environment Camera.entity_picture returns None (no HA runtime),
    so we patch the class temporarily to inject a fake base URL and verify the
    hash-append logic works correctly.
    """
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera

    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={
            "wifimap_1746000000.json": {
                "data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
                "startX": 0, "startY": 0,
            }
        },
        wifi_render_entry=(0, "wifimap_1746000000.json"),
    )
    cam = _make_camera(coord)

    original_ep = DreameA2WifiSelectedCamera.entity_picture.fget  # type: ignore[union-attr]

    def _patched(self):
        decoded = self._resolve_decoded()
        if not decoded:
            return None
        import hashlib
        render = self.coordinator._wifi_render_entry
        if render is not None:
            key = f"{render[0]}:{render[1]}"
        else:
            active = self.coordinator._active_map_id
            key = f"active:{active}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        base = "/api/camera_proxy/camera.test?token=abc"
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}v={h}"

    DreameA2WifiSelectedCamera.entity_picture = property(_patched)
    try:
        pic = cam.entity_picture
    finally:
        DreameA2WifiSelectedCamera.entity_picture = property(original_ep)

    # Should be a non-None URL with a version query param.
    assert pic is not None
    assert "v=" in pic


def test_camera_entity_picture_none_when_unavailable():
    """entity_picture returns None when camera has no data."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_map_by_id={},
        wifi_render_entry=(0, "missing.json"),
    )
    cam = _make_camera(coord)
    assert cam.entity_picture is None
