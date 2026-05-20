"""Tests for DreameA2WorkLogCamera — reads _work_log_png independently."""
from __future__ import annotations

import asyncio

from unittest.mock import MagicMock


def test_work_log_camera_reads_work_log_png():
    from custom_components.dreame_a2_mower.camera import DreameA2WorkLogCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = b"\x89PNGworklog"
    coord._active_map_base_png = None
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    cam = DreameA2WorkLogCamera(coord)
    result = asyncio.run(cam.async_camera_image())
    assert result == b"\x89PNGworklog"


def test_work_log_camera_returns_none_when_slots_empty():
    """Empty work_log_png AND empty active_map_base_png → None (no fallback)."""
    from custom_components.dreame_a2_mower.camera import DreameA2WorkLogCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = None
    coord._active_map_base_png = None
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    cam = DreameA2WorkLogCamera(coord)
    result = asyncio.run(cam.async_camera_image())
    assert result is None


def test_work_log_camera_falls_back_to_active_map_base():
    """When _work_log_png is None but _active_map_base_png is set,
    the camera returns the clean active-map base."""
    from custom_components.dreame_a2_mower.camera import DreameA2WorkLogCamera
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._main_view_png = b"\x89PNGmainview"
    coord._work_log_png = None
    coord._active_map_base_png = b"\x89PNGactivemapbase"
    coord._static_map_pngs_by_id = {}
    coord._last_map_md5_by_id = {}
    coord._active_map_id = 0
    coord._cloud = MagicMock()
    coord._cloud.model = "dreame.mower.g2408"
    coord._cloud.mac_address = None
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"
    coord.data = MagicMock()
    coord.data.hardware_serial = None

    cam = DreameA2WorkLogCamera(coord)
    result = asyncio.run(cam.async_camera_image())
    assert result == b"\x89PNGactivemapbase"
