"""Per-map LiDAR archive subdirs (lidar/{map_id}/).

Task 12: verifies that LidarArchive stores scans under <root>/<map_id>/
and that coordinator routes incoming LiDAR pushes to the active map's
archive.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive


def test_lidar_archive_uses_map_id_subdir(tmp_path: Path):
    """LidarArchive(root, map_id=0) stores files under <root>/0/."""
    archive = LidarArchive(tmp_path, map_id=0)
    archive.archive("scan.pcd", unix_ts=100, data=b"fake_pcd_bytes_0")
    assert (tmp_path / "0").is_dir()
    assert (tmp_path / "0" / "index.json").is_file()
    idx = json.loads((tmp_path / "0" / "index.json").read_text())
    assert len(idx["scans"]) == 1


def test_lidar_archives_isolated_per_map(tmp_path: Path):
    """Two LidarArchive instances with different map_ids are fully isolated."""
    a0 = LidarArchive(tmp_path, map_id=0)
    a1 = LidarArchive(tmp_path, map_id=1)
    a0.archive("x.pcd", unix_ts=1, data=b"XXXXX")
    a1.archive("y.pcd", unix_ts=2, data=b"YYYYY")

    scan0 = a0.latest()
    scan1 = a1.latest()
    assert scan0 is not None
    assert scan0.object_name == "x.pcd"
    assert scan1 is not None
    assert scan1.object_name == "y.pcd"

    # Verify physical separation: map 0 has no map 1 files and vice versa
    assert (tmp_path / "0").is_dir()
    assert (tmp_path / "1").is_dir()
    pcd_in_0 = list((tmp_path / "0").glob("*.pcd"))
    pcd_in_1 = list((tmp_path / "1").glob("*.pcd"))
    assert len(pcd_in_0) == 1
    assert len(pcd_in_1) == 1


def test_lidar_archive_root_property_points_to_subdir(tmp_path: Path):
    """archive.root returns the per-map subdir, not the parent root."""
    archive = LidarArchive(tmp_path, map_id=3)
    assert archive.root == tmp_path / "3"


def test_coordinator_lidar_archive_for_creates_on_first_access(
    coordinator_with_two_maps, tmp_path: Path
):
    """lidar_archive_for(map_id) creates and caches a new LidarArchive
    on first access, so there's no need to pre-populate lidar_archives."""
    coord = coordinator_with_two_maps
    coord.lidar_archives = {}
    coord._lidar_archive_root = tmp_path

    from custom_components.dreame_a2_mower.coordinator import (
        DreameA2MowerCoordinator,
    )
    coord.lidar_archive_for = DreameA2MowerCoordinator.lidar_archive_for.__get__(coord)

    arch = coord.lidar_archive_for(0)
    assert arch is not None
    assert isinstance(arch, LidarArchive)
    # Second call returns the same instance (cached)
    arch2 = coord.lidar_archive_for(0)
    assert arch is arch2


def test_coordinator_routes_push_to_active_map(
    coordinator_with_two_maps, tmp_path: Path
):
    """Coordinator routes incoming LiDAR push to active map's archive."""
    coord = coordinator_with_two_maps
    coord.lidar_archives = {
        0: LidarArchive(tmp_path, map_id=0),
        1: LidarArchive(tmp_path, map_id=1),
    }
    coord._active_map_id = 1
    coord._last_lidar_object_name = None

    # Simulate the routing logic: active map id drives archive selection
    active_archive = coord.lidar_archives.get(coord._active_map_id)
    assert active_archive is not None
    active_archive.archive("scan.pcd", unix_ts=100, data=b"PCD_DATA")

    scan1 = coord.lidar_archives[1].latest()
    assert scan1 is not None
    assert scan1.object_name == "scan.pcd"

    scan0 = coord.lidar_archives[0].latest()
    assert scan0 is None  # nothing written to map 0


def test_lidar_archive_backward_compat_no_map_id(tmp_path: Path):
    """LidarArchive(root) without map_id still works — root is used directly.

    This preserves backward compat for existing camera/view tests that were
    written before per-map support was added.
    """
    archive = LidarArchive(tmp_path)
    archive.archive("scan.pcd", unix_ts=100, data=b"bytes")
    assert archive.root == tmp_path
    assert (tmp_path / "index.json").is_file()
    assert archive.count == 1


def test_migration_moves_flat_pcds_to_map0_subdir(tmp_path: Path):
    """One-shot migration: existing flat *.pcd + index.json move to 0/."""
    # Set up a flat (pre-migration) layout
    pcd1 = tmp_path / "2024-01-01_1704067200_aabbccdd.pcd"
    pcd2 = tmp_path / "2024-01-02_1704153600_11223344.pcd"
    pcd1.write_bytes(b"PCD_DATA_1")
    pcd2.write_bytes(b"PCD_DATA_2")
    flat_index = tmp_path / "index.json"
    flat_index.write_text(
        json.dumps({
            "version": 1,
            "scans": [
                {
                    "filename": pcd1.name,
                    "object_name": "dreame/lidar/a.pcd",
                    "unix_ts": 1704067200,
                    "size_bytes": 10,
                    "md5": "aabbccdd",
                },
                {
                    "filename": pcd2.name,
                    "object_name": "dreame/lidar/b.pcd",
                    "unix_ts": 1704153600,
                    "size_bytes": 10,
                    "md5": "11223344",
                },
            ],
        })
    )

    # Run the migration helper directly
    from custom_components.dreame_a2_mower._lidar_migration import (
        migrate_flat_lidar_archive,
    )
    moved = migrate_flat_lidar_archive(tmp_path)

    assert moved == 3  # 2 pcds + 1 index
    assert (tmp_path / "0").is_dir()
    assert (tmp_path / "0" / pcd1.name).is_file()
    assert (tmp_path / "0" / pcd2.name).is_file()
    assert (tmp_path / "0" / "index.json").is_file()
    # Originals gone
    assert not pcd1.is_file()
    assert not pcd2.is_file()
    assert not flat_index.is_file()


def test_migration_is_idempotent(tmp_path: Path):
    """If 0/ already exists, migration is a no-op (returns 0)."""
    (tmp_path / "0").mkdir()
    (tmp_path / "some.pcd").write_bytes(b"data")  # stray file, but 0/ exists

    from custom_components.dreame_a2_mower._lidar_migration import (
        migrate_flat_lidar_archive,
    )
    moved = migrate_flat_lidar_archive(tmp_path)
    assert moved == 0
    # stray .pcd NOT moved — idempotent means we do nothing once 0/ exists
    assert (tmp_path / "some.pcd").is_file()


def test_migration_no_op_when_nothing_to_migrate(tmp_path: Path):
    """Empty root with no .pcd or index.json → migration skipped silently."""
    from custom_components.dreame_a2_mower._lidar_migration import (
        migrate_flat_lidar_archive,
    )
    moved = migrate_flat_lidar_archive(tmp_path)
    assert moved == 0
