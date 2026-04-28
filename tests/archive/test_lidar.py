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


def test_archive_enforces_size_cap(tmp_path: Path) -> None:
    """When max_bytes is set and the cumulative size exceeds it, oldest
    scans are evicted until under cap."""
    arch = LidarArchive(tmp_path, retention=0, max_bytes=10)
    arch.archive("oldest.pcd", 1700000000, b"AAAAA")  # 5 bytes, total=5
    arch.archive("middle.pcd", 1700000010, b"BBBBB")  # 5 bytes, total=10 (at cap)
    arch.archive("newest.pcd", 1700000020, b"CCCCC")  # 5 bytes — evict oldest

    scans = arch.list_scans()
    assert len(scans) == 2
    # The evicted scan's file must be removed from disk
    on_disk_size = sum(p.stat().st_size for p in tmp_path.glob("*.pcd"))
    assert on_disk_size <= 10
    # The middle and newest scans should be the survivors (oldest pruned)
    survivor_object_names = {s.object_name for s in scans}
    assert "oldest.pcd" not in survivor_object_names
    assert "middle.pcd" in survivor_object_names
    assert "newest.pcd" in survivor_object_names


def test_archive_size_cap_zero_means_unlimited(tmp_path: Path) -> None:
    """max_bytes=0 disables the size cap (matches retention=0 semantics)."""
    arch = LidarArchive(tmp_path, retention=0, max_bytes=0)
    for i in range(5):
        arch.archive(f"scan{i}.pcd", 1700000000 + i, bytes([i]) * 100)
    assert arch.count == 5


def test_archive_count_cap_and_size_cap_both_enforced(tmp_path: Path) -> None:
    """Both caps are independent; whichever bites first prunes."""
    arch = LidarArchive(tmp_path, retention=3, max_bytes=10000)
    for i in range(5):
        arch.archive(f"scan{i}.pcd", 1700000000 + i, bytes([i]) * 100)
    assert arch.count == 3
    # And the OLDEST two are gone
    kept = {s.object_name for s in arch.list_scans()}
    for i in (0, 1):
        assert f"scan{i}.pcd" not in kept


def test_set_max_bytes_runtime_prunes(tmp_path: Path) -> None:
    """Calling set_max_bytes after the fact prunes existing entries down
    to the new cap."""
    arch = LidarArchive(tmp_path, retention=0, max_bytes=0)
    for i in range(5):
        arch.archive(f"scan{i}.pcd", 1700000000 + i, bytes([i]) * 100)
    assert arch.count == 5
    # Tighten cap to fit only ~3 entries (300 bytes)
    arch.set_max_bytes(300)
    assert arch.count == 3
    # On-disk total now under cap
    on_disk = sum(p.stat().st_size for p in tmp_path.glob("*.pcd"))
    assert on_disk <= 300
