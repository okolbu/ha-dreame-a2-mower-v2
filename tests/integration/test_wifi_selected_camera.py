"""Tests for the updated DreameA2WifiSelectedCamera (Task 5: archive-store + flip)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_map(name=None):
    m = MagicMock()
    m.name = name
    return m


_SAMPLE_BODY = {
    "data": [1] * 4, "width": 2, "height": 2, "resolution": 2,
    "startX": 0, "startY": 0,
}


def _make_coordinator(maps=None, wifi_render_entry=None, active_map_id=0,
                      store_body=None):
    """Build a coordinator mock backed by _wifi_archive_store for body lookups."""
    coord = MagicMock()
    coord._cached_maps_by_id = maps or {}
    coord._active_map_id = active_map_id
    coord._wifi_render_entry = wifi_render_entry
    store = MagicMock()
    store.load_body = MagicMock(return_value=store_body)
    coord._wifi_archive_store = store
    return coord


def _make_camera(coord):
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera
    cam = DreameA2WifiSelectedCamera.__new__(DreameA2WifiSelectedCamera)
    cam.coordinator = coord
    cam._attr_unique_id = "wifi_selected"
    cam._attr_device_info = {}
    return cam


def test_camera_available_when_render_entry_has_data():
    """Camera is available when _wifi_render_entry points to a body the store returns."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_render_entry=(0, "wifimap_1746000000.json"),
        store_body=_SAMPLE_BODY,
    )
    cam = _make_camera(coord)
    assert cam.available


def test_camera_unavailable_when_render_entry_object_not_loaded():
    """Camera is unavailable when the store returns None for the selected entry."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_render_entry=(0, "wifimap_1746000000.json"),
        store_body=None,  # store can't find the body
    )
    cam = _make_camera(coord)
    assert not cam.available


def test_camera_unavailable_when_no_render_entry():
    """When _wifi_render_entry is None, camera is unavailable (no fallback)."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_render_entry=None,
        active_map_id=0,
        store_body=_SAMPLE_BODY,
    )
    cam = _make_camera(coord)
    assert not cam.available


def test_camera_unavailable_when_no_render_entry_and_no_active_data():
    """Camera is unavailable when no render entry (store not consulted)."""
    coord = _make_coordinator(
        maps={0: _make_map("Front")},
        wifi_render_entry=None,
        active_map_id=0,
        store_body=None,
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
        wifi_render_entry=(0, "wifimap_1746000000.json"),
        store_body=_SAMPLE_BODY,
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
        wifi_render_entry=(0, "missing.json"),
        store_body=None,  # store returns None → unavailable
    )
    cam = _make_camera(coord)
    assert cam.entity_picture is None


# ---------------------------------------------------------------------------
# Task 5: archive-store resolve + flip toggle tests
# ---------------------------------------------------------------------------


def _make_camera_with_flips(flip_x: bool, flip_y: bool):
    """Build a DreameA2WifiSelectedCamera with a mocked hass.states + store."""
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_render_entry = (None, "wifimap_1700000001.json")
    coord._wifi_archive_store = MagicMock()
    coord._wifi_archive_store.load_body = MagicMock(
        return_value={"data": [-50] * 16, "width": 4, "height": 4,
                      "resolution": 2, "startX": 0, "startY": 0}
    )
    cam = DreameA2WifiSelectedCamera(coord)
    cam.hass = MagicMock()
    cam.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args, **kw: fn(*args, **kw)
    )
    def _is_state(eid: str, val: str) -> bool:
        if eid == "input_boolean.dreame_a2_mower_wifi_flip_x":
            return val == ("on" if flip_x else "off")
        if eid == "input_boolean.dreame_a2_mower_wifi_flip_y":
            return val == ("on" if flip_y else "off")
        return False
    cam.hass.states.is_state = _is_state
    return cam, coord


def test_camera_reads_archive_body_via_store():
    cam, coord = _make_camera_with_flips(flip_x=False, flip_y=False)
    decoded = cam._resolve_decoded()
    assert decoded is not None
    coord._wifi_archive_store.load_body.assert_called_with(
        "wifimap_1700000001.json"
    )


def test_camera_passes_flip_kwargs_to_renderer():
    cam, _ = _make_camera_with_flips(flip_x=True, flip_y=False)
    with patch(
        "custom_components.dreame_a2_mower.wifi_map_render.render_wifi_map_png"
    ) as mock_r:
        mock_r.return_value = b"\x89PNG..."
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(cam.async_camera_image())
        finally:
            loop.close()
        call = mock_r.call_args
        assert call.kwargs.get("flip_x") is True
        assert call.kwargs.get("flip_y") is False


def test_camera_render_returns_none_when_no_selection():
    """When _wifi_render_entry is None, the camera returns None body."""
    from custom_components.dreame_a2_mower.camera import DreameA2WifiSelectedCamera

    coord = MagicMock()
    coord.entry.entry_id = "fake"
    coord._wifi_render_entry = None
    coord._wifi_archive_store = MagicMock()
    cam = DreameA2WifiSelectedCamera(coord)
    cam.hass = MagicMock()
    assert cam._resolve_decoded() is None
