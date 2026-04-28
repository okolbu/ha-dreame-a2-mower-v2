"""Tests for the /api/dreame_a2_mower/lidar/latest.pcd HTTP view."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
from custom_components.dreame_a2_mower.camera import LidarPcdDownloadView


def test_view_url_and_auth():
    """Spec §5.9: download URL is auth-required."""
    view = LidarPcdDownloadView()
    assert view.url == "/api/dreame_a2_mower/lidar/latest.pcd"
    assert view.requires_auth is True
    assert view.name == "api:dreame_a2_mower:lidar_latest"


def test_view_returns_404_when_no_coordinator(tmp_path: Path):
    """When hass.data has no coordinator entry, return 404."""
    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {}}
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 404


def test_view_returns_404_when_archive_is_none(tmp_path: Path):
    """When the coordinator's lidar_archive attribute is None (very
    early setup), return 404."""
    coord = MagicMock()
    coord.lidar_archive = None

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {"abc": coord}}
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 404


def test_view_returns_404_when_archive_empty(tmp_path: Path):
    arch = LidarArchive(tmp_path)
    coord = MagicMock()
    coord.lidar_archive = arch

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {"abc": coord}}
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 404


def test_view_returns_file_response_when_scan_present(tmp_path: Path):
    arch = LidarArchive(tmp_path)
    arch.archive("anywhere", 1700000000, b"# .PCD v0.7\nDUMMY")
    coord = MagicMock()
    coord.lidar_archive = arch

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {"abc": coord}}
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 200
    assert "attachment" in resp.headers.get("Content-Disposition", "")


def test_view_returns_404_when_archived_file_missing_from_disk(tmp_path: Path):
    """If index.json says a file exists but the .pcd was deleted
    out-of-band, return 404 rather than crash."""
    arch = LidarArchive(tmp_path)
    arch.archive("anywhere", 1700000000, b"# .PCD v0.7\nDUMMY")
    for p in tmp_path.glob("*.pcd"):
        p.unlink()

    coord = MagicMock()
    coord.lidar_archive = arch

    view = LidarPcdDownloadView()
    request = MagicMock()
    hass = MagicMock()
    hass.data = {"dreame_a2_mower": {"abc": coord}}
    request.app = {"hass": hass}
    resp = asyncio.run(view.get(request))
    assert resp.status == 404
