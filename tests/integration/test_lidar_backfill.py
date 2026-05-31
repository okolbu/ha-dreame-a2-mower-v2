"""Startup LiDAR backfill via the 3dmap OBJ list.

Fresh installs (and HA that was down during a "View LiDAR Map" push)
otherwise wait potentially weeks for the next s99.20 push. The backfill
pulls the cloud's available 3dmap PCD objects once per session and
archives any not already present (dedup by object_name → no re-download).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from custom_components.dreame_a2_mower.archive.lidar import LidarArchive
from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator
from custom_components.dreame_a2_mower.mower.state import MowerState


def _make_coord(tmp_path: Path, *, list_return, active_map_id=0, done=False, seeded=()):
    coord = MagicMock()
    coord._active_map_id = active_map_id
    coord._lidar_backfill_done = done
    coord._cloud = MagicMock()
    coord._cloud.list_3dmap_objects = MagicMock(return_value=list_return)
    coord._cloud.get_interim_file_url = MagicMock(side_effect=lambda name: f"https://oss/{name}")
    coord._cloud.get_file = MagicMock(side_effect=lambda url: b"PCD:" + url.encode())
    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    archive = LidarArchive(tmp_path, map_id=active_map_id if active_map_id is not None else 0)
    for name in seeded:
        archive.archive(name, 1, b"seed:" + name.encode())
    coord.lidar_archive_for = MagicMock(return_value=archive)
    coord.data = MowerState()
    coord.async_set_updated_data = MagicMock()
    coord._backfill_lidar_from_3dmap = (
        DreameA2MowerCoordinator._backfill_lidar_from_3dmap.__get__(coord)
    )
    return coord, archive


def test_fetches_and_archives_new_objects(tmp_path: Path):
    coord, archive = _make_coord(tmp_path, list_return=["objA", "objB"])

    asyncio.run(coord._backfill_lidar_from_3dmap(1000))

    assert archive.count == 2
    assert coord._cloud.get_file.call_count == 2
    assert coord._lidar_backfill_done is True


def test_skips_objects_already_archived_by_name(tmp_path: Path):
    """An object already in the archive (by object_name) is NOT re-downloaded."""
    coord, archive = _make_coord(tmp_path, list_return=["objA", "objB"], seeded=["objA"])

    asyncio.run(coord._backfill_lidar_from_3dmap(1000))

    assert coord._cloud.get_file.call_count == 1            # only objB fetched
    coord._cloud.get_interim_file_url.assert_called_once_with("objB")
    assert archive.count == 2                                # seeded objA + new objB
    assert coord._lidar_backfill_done is True


def test_relay_failure_does_not_mark_done(tmp_path: Path):
    """list_3dmap_objects() == None (relay 80001) → retry next refresh."""
    coord, archive = _make_coord(tmp_path, list_return=None)

    asyncio.run(coord._backfill_lidar_from_3dmap(1000))

    assert archive.count == 0
    coord._cloud.get_file.assert_not_called()
    assert coord._lidar_backfill_done is False


def test_empty_list_marks_done_without_fetching(tmp_path: Path):
    """No 3dmaps in the cloud → mark done (don't retry forever), fetch nothing."""
    coord, archive = _make_coord(tmp_path, list_return=[])

    asyncio.run(coord._backfill_lidar_from_3dmap(1000))

    assert archive.count == 0
    coord._cloud.get_file.assert_not_called()
    assert coord._lidar_backfill_done is True


def test_no_op_when_already_done(tmp_path: Path):
    """Runs at most once per session — does not even list when already done."""
    coord, _ = _make_coord(tmp_path, list_return=["objA"], done=True)

    asyncio.run(coord._backfill_lidar_from_3dmap(1000))

    coord._cloud.list_3dmap_objects.assert_not_called()


def test_no_op_when_active_map_unknown(tmp_path: Path):
    """Active map not yet known → defer (don't list, don't mark done)."""
    coord, _ = _make_coord(tmp_path, list_return=["objA"], active_map_id=None)

    asyncio.run(coord._backfill_lidar_from_3dmap(1000))

    coord._cloud.list_3dmap_objects.assert_not_called()
    assert coord._lidar_backfill_done is False


def test_refresh_cloud_state_runs_the_backfill():
    """_refresh_cloud_state awaits the backfill (after the active map is set)."""
    new_state = MagicMock()
    new_state.mapl = [[0, 1, 0, 0, 0]]
    coord = MagicMock()
    coord._cloud = MagicMock()
    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = AsyncMock(return_value=new_state)
    coord._apply_mapl = MagicMock()
    coord._render_maps_from_cloud_state = AsyncMock()
    coord._sync_map_subdevices = MagicMock()
    coord._apply_cloud_state_to_mower_state = MagicMock()
    coord.async_update_listeners = MagicMock()
    coord._backfill_lidar_from_3dmap = AsyncMock()
    coord._refresh_cloud_state = (
        DreameA2MowerCoordinator._refresh_cloud_state.__get__(coord)
    )

    asyncio.run(coord._refresh_cloud_state())

    coord._backfill_lidar_from_3dmap.assert_awaited_once()
    # called with an integer epoch
    (arg,), _ = coord._backfill_lidar_from_3dmap.await_args
    assert isinstance(arg, int)
