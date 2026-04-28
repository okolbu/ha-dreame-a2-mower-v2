"""Tests for LiDAR camera entities."""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import numpy as np
from PIL import Image

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
from custom_components.dreame_a2_mower.camera import (
    DreameA2LidarTopDownCamera,
    DreameA2LidarTopDownFullCamera,
)


def _fake_pcd_bytes(n: int = 50) -> bytes:
    """Build a minimal valid binary PCD blob with n random points."""
    rng = np.random.default_rng(seed=42)
    xyz = rng.uniform(-5.0, 5.0, size=(n, 3)).astype(np.float32)
    body = xyz.tobytes()
    header = (
        b"VERSION 0.7\n"
        b"FIELDS x y z\n"
        b"SIZE 4 4 4\n"
        b"TYPE F F F\n"
        b"COUNT 1 1 1\n"
        + f"WIDTH {n}\n".encode()
        + b"HEIGHT 1\n"
        + b"VIEWPOINT 0 0 0 1 0 0 0\n"
        + f"POINTS {n}\n".encode()
        + b"DATA binary\n"
    )
    return header + body


class _FakeHass:
    """Tiny hass-double for the camera entity to use."""

    async def async_add_executor_job(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


class _Coord:
    """Coordinator-double sufficient for camera entity construction."""

    def __init__(self, lidar_archive):
        self.lidar_archive = lidar_archive
        self.entry = type("E", (), {"entry_id": "abc"})()
        self._cloud = None
        self.hass = _FakeHass()


def test_top_down_camera_returns_png_when_archive_has_scan(tmp_path: Path):
    arch = LidarArchive(tmp_path)
    arch.archive("anywhere", 1700000000, _fake_pcd_bytes())

    cam = DreameA2LidarTopDownCamera(_Coord(arch))
    cam.hass = _FakeHass()
    png = asyncio.run(cam.async_camera_image())
    assert png is not None
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    img = Image.open(io.BytesIO(png))
    assert img.size == (512, 512)


def test_top_down_camera_returns_none_when_archive_empty(tmp_path: Path):
    arch = LidarArchive(tmp_path)

    cam = DreameA2LidarTopDownCamera(_Coord(arch))
    cam.hass = _FakeHass()
    png = asyncio.run(cam.async_camera_image())
    assert png is None


def test_top_down_camera_returns_none_when_archive_is_none(tmp_path: Path):
    """Defensive: if coordinator.lidar_archive is None (very early
    setup), we return None rather than crash."""
    cam = DreameA2LidarTopDownCamera(_Coord(None))
    cam.hass = _FakeHass()
    png = asyncio.run(cam.async_camera_image())
    assert png is None


def test_full_resolution_camera_returns_larger_png(tmp_path: Path):
    arch = LidarArchive(tmp_path)
    arch.archive("anywhere", 1700000000, _fake_pcd_bytes())

    cam = DreameA2LidarTopDownFullCamera(_Coord(arch))
    cam.hass = _FakeHass()
    png = asyncio.run(cam.async_camera_image())
    assert png is not None
    img = Image.open(io.BytesIO(png))
    assert img.size == (1024, 1024)


def test_camera_returns_none_when_pcd_file_missing_from_disk(tmp_path: Path):
    """If index.json says a file exists but it was deleted out-of-band,
    return None rather than crash."""
    arch = LidarArchive(tmp_path)
    arch.archive("anywhere", 1700000000, _fake_pcd_bytes())
    # Manually remove the .pcd file from disk
    for p in tmp_path.glob("*.pcd"):
        p.unlink()

    cam = DreameA2LidarTopDownCamera(_Coord(arch))
    cam.hass = _FakeHass()
    png = asyncio.run(cam.async_camera_image())
    assert png is None
