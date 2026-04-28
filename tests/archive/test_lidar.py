"""Tests for archive/lidar.py — lifted from legacy."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.archive.lidar import (
    ArchivedLidarScan,
    LidarArchive,
)


def test_archive_starts_empty(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    assert arch.count == 0
    assert arch.latest() is None
    assert arch.list_scans() == []


def test_archive_persists_scan(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    pcd_bytes = b"# .PCD v0.7 - Point Cloud Data file format\nDUMMY"
    entry = arch.archive("dreame/lidar/abc.pcd", unix_ts=1700000000, data=pcd_bytes)
    assert entry is not None
    assert entry.size_bytes == len(pcd_bytes)
    assert entry.object_name == "dreame/lidar/abc.pcd"
    assert (tmp_path / entry.filename).read_bytes() == pcd_bytes
    assert arch.count == 1


def test_archive_dedupes_by_md5(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    same = b"identical-bytes"
    first = arch.archive("a.pcd", 1700000000, same)
    second = arch.archive("b.pcd", 1700000005, same)
    assert first is not None
    assert second is None  # md5 collision skips the write
    assert arch.count == 1


def test_archive_index_round_trip(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    arch.archive("a.pcd", 1700000000, b"AAA")
    arch.archive("b.pcd", 1700000010, b"BBB")
    # New instance — should rehydrate from index.json
    arch2 = LidarArchive(tmp_path)
    assert arch2.count == 2
    latest = arch2.latest()
    assert latest is not None
    assert latest.unix_ts == 1700000010


def test_archive_empty_payload_returns_none(tmp_path: Path) -> None:
    arch = LidarArchive(tmp_path)
    assert arch.archive("anywhere", 1700000000, b"") is None
    assert arch.count == 0


def test_archive_corrupt_index_starts_fresh(tmp_path: Path) -> None:
    """Mirrors SessionArchive: a malformed index.json doesn't crash setup."""
    (tmp_path / "index.json").write_text("not json {{{")
    arch = LidarArchive(tmp_path)
    assert arch.count == 0
