"""Tests for the /api/dreame_a2_mower/lidar/{map_id}/latest.pcd HTTP view."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
from custom_components.dreame_a2_mower.camera import LidarPcdDownloadView
from custom_components.dreame_a2_mower.const import DOMAIN


def _make_hass(data=None):
    """Return a MagicMock hass whose async_add_executor_job runs callables inline."""
    hass = MagicMock()
    hass.data = data or {}

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor
    return hass


def _make_coord_with_archive(archive: LidarArchive | None, map_id: int = 0):
    """Return a minimal coordinator mock with lidar_archive_for implemented."""
    coord = MagicMock()
    archives = {map_id: archive} if archive is not None else {}
    coord.lidar_archive_for.side_effect = lambda mid: archives.get(mid)
    return coord


def test_view_url_and_auth():
    """Spec §5.9: download URL is auth-required and includes {map_id}."""
    view = LidarPcdDownloadView()
    assert "{map_id}" in view.url
    assert view.requires_auth is True
    assert view.name == "api:dreame_a2_mower:lidar_latest"


def test_view_returns_404_when_no_coordinator(tmp_path: Path):
    """When hass.data has no coordinator entry, return 404."""
    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request, map_id="0"))
    assert resp.status == 404


def test_view_returns_404_when_archive_is_none(tmp_path: Path):
    """When the coordinator has no archive for the requested map, return 404."""
    coord = _make_coord_with_archive(None, map_id=0)

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"abc": coord}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request, map_id="0"))
    assert resp.status == 404


def test_view_returns_404_when_archive_empty(tmp_path: Path):
    arch = LidarArchive(tmp_path, map_id=0)
    coord = _make_coord_with_archive(arch, map_id=0)

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"abc": coord}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request, map_id="0"))
    assert resp.status == 404


def test_view_returns_file_response_when_scan_present(tmp_path: Path):
    arch = LidarArchive(tmp_path, map_id=0)
    arch.archive("anywhere", 1700000000, b"# .PCD v0.7\nDUMMY")
    coord = _make_coord_with_archive(arch, map_id=0)

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"abc": coord}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request, map_id="0"))
    assert resp.status == 200
    assert "attachment" in resp.headers.get("Content-Disposition", "")


def test_view_returns_404_when_archived_file_missing_from_disk(tmp_path: Path):
    """If index.json says a file exists but the .pcd was deleted
    out-of-band, return 404 rather than crash."""
    arch = LidarArchive(tmp_path, map_id=0)
    arch.archive("anywhere", 1700000000, b"# .PCD v0.7\nDUMMY")
    # Remove the .pcd from the per-map subdir
    for p in (tmp_path / "0").glob("*.pcd"):
        p.unlink()

    coord = _make_coord_with_archive(arch, map_id=0)

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"abc": coord}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request, map_id="0"))
    assert resp.status == 404


def test_view_returns_404_for_bad_map_id(tmp_path: Path):
    """Non-integer map_id returns 404."""
    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {}})
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request, map_id="notanint"))
    assert resp.status == 404


def test_view_returns_404_for_wrong_map_id(tmp_path: Path):
    """Valid integer map_id that has no archive returns 404."""
    arch = LidarArchive(tmp_path, map_id=0)
    arch.archive("scan.pcd", 1700000000, b"# .PCD v0.7\nDUMMY")
    coord = _make_coord_with_archive(arch, map_id=0)

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = _make_hass({DOMAIN: {"abc": coord}})
    request.app = {"hass": hass}
    # Map 99 has no archive
    resp = asyncio.run(view.get(request, map_id="99"))
    assert resp.status == 404
