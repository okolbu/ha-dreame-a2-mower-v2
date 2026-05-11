"""Tests for the /api/dreame_a2_mower/lidar/selected.pcd HTTP view."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
from custom_components.dreame_a2_mower.camera import LidarSelectedPcdView
from custom_components.dreame_a2_mower.const import DOMAIN


def _make_hass(data=None):
    hass = MagicMock()
    hass.data = data or {}

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    return hass


def _make_coord(archive_by_map_id: dict, lidar_render_entry=None, active_map_id=0):
    coord = MagicMock()
    coord._lidar_render_entry = lidar_render_entry
    coord._active_map_id = active_map_id
    coord.lidar_archive_for.side_effect = lambda mid: archive_by_map_id.get(mid)
    return coord


def test_view_url_and_auth():
    view = LidarSelectedPcdView()
    assert view.url == "/api/dreame_a2_mower/lidar/selected.pcd"
    assert view.requires_auth is True
    assert view.name == "api:dreame_a2_mower:lidar_selected_pcd"


def test_view_503_when_no_integration(tmp_path: Path):
    view = LidarSelectedPcdView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 503


def test_view_404_no_active_map_and_no_selection(tmp_path: Path):
    coord = _make_coord({}, lidar_render_entry=None, active_map_id=None)
    view = LidarSelectedPcdView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"x": coord}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 404


def test_view_serves_latest_when_no_explicit_selection(tmp_path: Path):
    arch = LidarArchive(tmp_path, map_id=0)
    arch.archive("scan.pcd", 1700000000, b"PCD DATA")
    coord = _make_coord({0: arch}, lidar_render_entry=None, active_map_id=0)
    view = LidarSelectedPcdView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"x": coord}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 200
    assert resp.body == b"PCD DATA"


def test_view_serves_explicitly_selected_scan(tmp_path: Path):
    arch = LidarArchive(tmp_path, map_id=0)
    arch.archive("first.pcd", 1700000000, b"FIRST PCD")
    arch.archive("second.pcd", 1700000001, b"SECOND PCD")
    # Get the filename of the earliest scan (it's in the archive by now)
    entries = arch.entries()
    target_entry = min(entries, key=lambda e: e.unix_ts)

    coord = _make_coord(
        {0: arch},
        lidar_render_entry=(0, target_entry.filename),
        active_map_id=0,
    )
    view = LidarSelectedPcdView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"x": coord}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 200


def test_view_404_when_selected_file_missing(tmp_path: Path):
    arch = LidarArchive(tmp_path, map_id=0)
    arch.archive("ghost.pcd", 1700000000, b"GHOST")
    # Delete the actual file so the path exists in index but not on disk.
    for p in (tmp_path / "0").glob("*.pcd"):
        p.unlink()

    entries = arch.entries()
    target_entry = entries[0]
    coord = _make_coord(
        {0: arch},
        lidar_render_entry=(0, target_entry.filename),
        active_map_id=0,
    )
    view = LidarSelectedPcdView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"x": coord}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 404
