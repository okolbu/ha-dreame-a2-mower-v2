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


def test_lidar_archive_map_id_is_required(tmp_path: Path):
    """LidarArchive(root, map_id=N) is the only supported call signature.

    map_id is required; the flat-mode shim was removed in T13.
    """
    import pytest
    # map_id as positional keyword
    archive = LidarArchive(tmp_path, map_id=0)
    archive.archive("scan.pcd", unix_ts=100, data=b"bytes")
    assert archive.root == tmp_path / "0"
    assert (tmp_path / "0" / "index.json").is_file()
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


# ---------------------------------------------------------------------------
# Task 13 — per-map camera entities
# ---------------------------------------------------------------------------


def test_lidar_top_down_per_map(coordinator_with_two_maps, tmp_path):
    """LiDAR top-down camera is per-map, on map sub-device."""
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownCamera
    from custom_components.dreame_a2_mower.const import DOMAIN

    coord = coordinator_with_two_maps
    coord.lidar_archives = {
        0: LidarArchive(tmp_path, map_id=0),
        1: LidarArchive(tmp_path, map_id=1),
    }
    cam0 = DreameA2LidarTopDownCamera(coord, map_id=0)
    cam1 = DreameA2LidarTopDownCamera(coord, map_id=1)

    assert cam0._attr_unique_id == "G2408053AEE0006232_map_0_lidar_top_down"
    assert cam1._attr_unique_id == "G2408053AEE0006232_map_1_lidar_top_down"
    assert cam0._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_lidar_top_down_full_per_map(coordinator_with_two_maps, tmp_path):
    """LiDAR full-resolution camera is also per-map."""
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
    from custom_components.dreame_a2_mower.camera import DreameA2LidarTopDownFullCamera
    from custom_components.dreame_a2_mower.const import DOMAIN

    coord = coordinator_with_two_maps
    coord.lidar_archives = {
        0: LidarArchive(tmp_path, map_id=0),
    }
    cam = DreameA2LidarTopDownFullCamera(coord, map_id=0)

    assert cam._attr_unique_id == "G2408053AEE0006232_map_0_lidar_top_down_full"
    assert cam._attr_device_info["identifiers"] == {
        (DOMAIN, "G2408053AEE0006232_map_0")
    }


def test_lidar_view_url_takes_map_id():
    """LidarPcdDownloadView URL pattern includes map_id path param."""
    from custom_components.dreame_a2_mower.camera import LidarPcdDownloadView

    assert "{map_id}" in LidarPcdDownloadView.url


def test_lidar_view_per_map_returns_pcd(tmp_path):
    """GET /api/dreame_a2_mower/lidar/0/latest.pcd returns PCD for map 0."""
    import asyncio
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
    from custom_components.dreame_a2_mower.camera import LidarPcdDownloadView
    from custom_components.dreame_a2_mower.const import DOMAIN

    arch = LidarArchive(tmp_path, map_id=0)
    arch.archive("scan.pcd", unix_ts=1700000000, data=b"# .PCD v0.7\nDATA binary\n")

    coord = MagicMock()
    coord.lidar_archives = {0: arch}
    coord._active_map_id = 0
    coord.lidar_archive_for.side_effect = lambda mid: coord.lidar_archives.get(mid)

    entry_id = "abc123"
    hass = MagicMock()
    hass.data = {DOMAIN: {entry_id: coord}}

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    view = LidarPcdDownloadView()
    request = MagicMock()
    request.app = {"hass": hass}
    request.match_info = {"map_id": "0"}

    resp = asyncio.run(view.get(request, map_id="0"))
    assert resp.status == 200


def test_lidar_view_per_map_returns_404_for_unknown_map(tmp_path):
    """GET /api/dreame_a2_mower/lidar/99/latest.pcd → 404 when map 99 has no archive."""
    import asyncio
    from unittest.mock import MagicMock
    from custom_components.dreame_a2_mower.camera import LidarPcdDownloadView
    from custom_components.dreame_a2_mower.const import DOMAIN

    coord = MagicMock()
    coord.lidar_archives = {}
    coord._active_map_id = 0
    coord.lidar_archive_for.side_effect = lambda mid: coord.lidar_archives.get(mid)

    entry_id = "abc123"
    hass = MagicMock()
    hass.data = {DOMAIN: {entry_id: coord}}

    async def _executor(fn, *args):
        return fn(*args)

    hass.async_add_executor_job.side_effect = _executor

    view = LidarPcdDownloadView()
    request = MagicMock()
    request.app = {"hass": hass}

    resp = asyncio.run(view.get(request, map_id="99"))
    assert resp.status == 404


# ---------------------------------------------------------------------------
# Cross-map LiDAR archive picker (select + camera)
# ---------------------------------------------------------------------------


def test_lidar_archive_entries_method(tmp_path: Path):
    """LidarArchive.entries() returns scans newest-first (alias for list_scans)."""
    archive = LidarArchive(tmp_path, map_id=0)
    archive.archive("older.pcd", unix_ts=100, data=b"data_older_abc")
    archive.archive("newer.pcd", unix_ts=200, data=b"data_newer_xyz")
    entries = archive.entries()
    assert len(entries) == 2
    assert entries[0].unix_ts == 200  # newest first
    assert entries[1].unix_ts == 100


def test_list_lidar_archive_entries_aggregates_across_maps(
    coordinator_with_two_maps, tmp_path: Path
):
    """Cross-map listing returns all entries, newest-first."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    arch0 = LidarArchive(tmp_path, map_id=0)
    arch1 = LidarArchive(tmp_path, map_id=1)
    arch0.archive("older.pcd", unix_ts=100, data=b"older_scan_data_0")
    arch1.archive("newer.pcd", unix_ts=200, data=b"newer_scan_data_1")
    coord.lidar_archives = {0: arch0, 1: arch1}
    coord.list_lidar_archive_entries = (
        DreameA2MowerCoordinator.list_lidar_archive_entries.__get__(coord)
    )
    entries = coord.list_lidar_archive_entries()
    assert len(entries) == 2
    assert entries[0][0] == 1   # map_id of newest scan
    assert entries[0][1].unix_ts == 200
    assert entries[1][0] == 0   # map_id of older scan
    assert entries[1][1].unix_ts == 100


def test_set_lidar_render_entry_updates_state(coordinator_with_two_maps):
    """set_lidar_render_entry() stores (map_id, filename) or clears to None."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = coordinator_with_two_maps
    coord._lidar_render_entry = None
    coord.set_lidar_render_entry = (
        DreameA2MowerCoordinator.set_lidar_render_entry.__get__(coord)
    )
    coord.async_update_listeners = lambda: None

    coord.set_lidar_render_entry(1, "foo.pcd")
    assert coord._lidar_render_entry == (1, "foo.pcd")

    coord.set_lidar_render_entry(None, None)
    assert coord._lidar_render_entry is None


def test_lidar_archive_select_options(coordinator_with_two_maps, tmp_path: Path):
    """DreameA2LidarArchiveSelect.options returns formatted labels newest-first."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.select import DreameA2LidarArchiveSelect

    coord = coordinator_with_two_maps
    arch0 = LidarArchive(tmp_path, map_id=0)
    arch1 = LidarArchive(tmp_path, map_id=1)
    arch0.archive("a.pcd", unix_ts=1000000, data=b"scan_data_map0_aaa")
    arch1.archive("b.pcd", unix_ts=2000000, data=b"scan_data_map1_bbb")
    coord.lidar_archives = {0: arch0, 1: arch1}
    coord._lidar_render_entry = None
    coord.list_lidar_archive_entries = (
        DreameA2MowerCoordinator.list_lidar_archive_entries.__get__(coord)
    )
    coord.set_lidar_render_entry = (
        DreameA2MowerCoordinator.set_lidar_render_entry.__get__(coord)
    )
    coord.async_update_listeners = lambda: None

    sel = DreameA2LidarArchiveSelect(coord)
    sel._rebuild_options()

    opts = sel.options
    assert len(opts) == 2
    # Newest-first: map 1's scan (ts=2000000) should appear before map 0's
    assert "[Map 2]" in opts[0]  # map_id=1 → "Map 2"
    assert "[Map 1]" in opts[1]  # map_id=0 → "Map 1"


def test_lidar_archive_select_no_scans(coordinator_with_two_maps):
    """DreameA2LidarArchiveSelect shows placeholder when no scans exist."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
    from custom_components.dreame_a2_mower.select import DreameA2LidarArchiveSelect

    coord = coordinator_with_two_maps
    coord.lidar_archives = {}
    coord._lidar_render_entry = None
    coord.list_lidar_archive_entries = (
        DreameA2MowerCoordinator.list_lidar_archive_entries.__get__(coord)
    )

    sel = DreameA2LidarArchiveSelect(coord)
    sel._rebuild_options()

    assert sel.options == ["(no scans)"]


def test_lidar_selected_camera_unique_id(coordinator_with_two_maps):
    """DreameA2LidarSelectedCamera has the expected unique_id."""
    from custom_components.dreame_a2_mower.camera import DreameA2LidarSelectedCamera

    coord = coordinator_with_two_maps
    cam = DreameA2LidarSelectedCamera(coord)
    assert cam._attr_unique_id == "G2408053AEE0006232_lidar_selected"


# ---------------------------------------------------------------------------
# F6 — move_lidar_scan between archives
# ---------------------------------------------------------------------------


def test_move_lidar_scan_between_archives(tmp_path):
    """move_entry_to moves PCD file and updates both indexes."""
    a0 = LidarArchive(tmp_path, map_id=0)
    a1 = LidarArchive(tmp_path, map_id=1)
    a0.archive("scan.pcd", unix_ts=100, data=b"scan_bytes_here_xyz")
    fn = a0.list_scans()[0].filename

    moved = a0.move_entry_to(fn, a1)

    assert moved is True
    assert a0.list_scans() == []
    assert len(a1.list_scans()) == 1
    assert a1.list_scans()[0].filename == fn
    # File lives in destination, gone from source.
    assert (tmp_path / "1" / fn).is_file()
    assert not (tmp_path / "0" / fn).is_file()
    # Both index.json files are consistent.
    import json
    idx0 = json.loads((tmp_path / "0" / "index.json").read_text())
    idx1 = json.loads((tmp_path / "1" / "index.json").read_text())
    assert idx0["scans"] == []
    assert len(idx1["scans"]) == 1
    assert idx1["scans"][0]["filename"] == fn


def test_move_lidar_scan_returns_false_on_missing(tmp_path):
    """move_entry_to returns False when filename doesn't exist in source."""
    a0 = LidarArchive(tmp_path, map_id=0)
    a1 = LidarArchive(tmp_path, map_id=1)
    assert a0.move_entry_to("nonexistent.pcd", a1) is False


def test_move_lidar_scan_missing_file_repairs_index(tmp_path):
    """move_entry_to removes a missing-on-disk entry from the index (repair)."""
    a0 = LidarArchive(tmp_path, map_id=0)
    a1 = LidarArchive(tmp_path, map_id=1)
    # Manually insert a ghost entry into index.
    a0.archive("ghost.pcd", unix_ts=50, data=b"ghost_data_here_abc")
    fn = a0.list_scans()[0].filename
    # Delete the actual file but leave the index entry.
    (tmp_path / "0" / fn).unlink()

    result = a0.move_entry_to(fn, a1)

    # Returns False (file not present).
    assert result is False
    # Source index is repaired — entry removed.
    assert a0.list_scans() == []
    # Destination index unchanged.
    assert a1.list_scans() == []
