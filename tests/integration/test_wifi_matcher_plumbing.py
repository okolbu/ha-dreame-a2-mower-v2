"""Coordinator-side tests for the WiFi heatmap → map_id matcher
(`_tag_wifi_archive_map_ids` + the matcher run on refresh)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.dreame_a2_mower.archive.session import (
    ArchivedSession,
    SessionArchive,
)
from custom_components.dreame_a2_mower.wifi_archive_store import WifiArchiveStore


def _build_coordinator_skeleton(tmp_path: Path):
    """Construct a hollow coordinator with just enough state for the
    matcher helpers to run."""
    from custom_components.dreame_a2_mower.coordinator import DreameA2MowerCoordinator

    coord = object.__new__(DreameA2MowerCoordinator)
    coord._wifi_archive_store = WifiArchiveStore(tmp_path / "wifi_archive")
    coord._wifi_archive_index = []
    coord.session_archive = SessionArchive(tmp_path / "sessions")
    coord._WIFI_MATCH_RECENT_SESSIONS = 30
    return coord


def _write_session_blob(
    coord, *, filename: str, map_id: int, start_ts: int, end_ts: int,
    wifi_samples: list[list],
):
    """Add a session to disk + index with the given wifi_samples."""
    archive = coord.session_archive
    archive._index_loaded = True  # skip load_index()
    archive._index.append(
        ArchivedSession(
            filename=filename,
            start_ts=start_ts,
            end_ts=end_ts,
            duration_min=60,
            area_mowed_m2=10.0,
            map_area_m2=100,
            md5=filename[:8],
            map_id=map_id,
        )
    )
    archive._save_index()
    body = {"md5": filename[:8], "start": start_ts, "end": end_ts}
    if wifi_samples is not None:
        body["wifi_samples"] = wifi_samples
    (archive.root / filename).write_text(json.dumps(body))


def _write_heatmap(coord, *, object_name: str, width: int, height: int,
                   res_m: int, start_x_m: float, start_y_m: float,
                   fill_dbm: int = -55):
    """Drop a heatmap blob into the wifi archive store (no matcher tag)."""
    body = {
        "data": [fill_dbm] * (width * height),
        "width": width,
        "height": height,
        "resolution": res_m,
        "startX": int(start_x_m * 100),  # cm
        "startY": int(start_y_m * 100),
    }
    coord._wifi_archive_store.archive(object_name, body, first_seen_unix=1000)
    coord._wifi_archive_index = coord._wifi_archive_store.load_index()


def test_tag_with_single_matching_session(tmp_path: Path):
    """One session, one heatmap — straightforward match."""
    coord = _build_coordinator_skeleton(tmp_path)
    # Session ran on map_id=2 with samples near origin.
    _write_session_blob(
        coord,
        filename="session_a.json",
        map_id=2,
        start_ts=1000,
        end_ts=2000,
        wifi_samples=[
            [1.0, 1.0, -55, 1100],
            [3.0, 1.0, -55, 1200],
            [5.0, 1.0, -55, 1300],
        ],
    )
    # Heatmap with bbox 0..8 m × 0..8 m, all cells -55 dBm.
    _write_heatmap(
        coord,
        object_name="wifimap_1700.json",
        width=4, height=4, res_m=2,
        start_x_m=0.0, start_y_m=0.0,
        fill_dbm=-55,
    )
    n = coord._tag_wifi_archive_map_ids()
    assert n == 1
    reloaded = coord._wifi_archive_store.load_index()
    assert reloaded[0].map_id == 2


def test_tag_picks_best_of_two_competing_sessions(tmp_path: Path):
    """Two sessions on different maps — matcher picks the one with
    samples inside the heatmap bbox."""
    coord = _build_coordinator_skeleton(tmp_path)
    # Session 0 — samples FAR from the heatmap (outside its bbox).
    _write_session_blob(
        coord,
        filename="session_far.json",
        map_id=0,
        start_ts=1000,
        end_ts=2000,
        wifi_samples=[
            [100.0, 100.0, -55, 1100],
            [101.0, 100.0, -55, 1200],
        ],
    )
    # Session 1 — samples inside the heatmap bbox.
    _write_session_blob(
        coord,
        filename="session_near.json",
        map_id=1,
        start_ts=1500,
        end_ts=2500,
        wifi_samples=[
            [1.0, 1.0, -55, 1600],
            [3.0, 1.0, -55, 1700],
            [5.0, 1.0, -55, 1800],
        ],
    )
    _write_heatmap(
        coord,
        object_name="wifimap_match.json",
        width=4, height=4, res_m=2,
        start_x_m=0.0, start_y_m=0.0,
        fill_dbm=-55,
    )
    assert coord._tag_wifi_archive_map_ids() == 1
    reloaded = coord._wifi_archive_store.load_index()
    assert reloaded[0].map_id == 1


def test_tag_skips_already_tagged(tmp_path: Path):
    """An entry with map_id >= 0 is left alone on subsequent runs."""
    coord = _build_coordinator_skeleton(tmp_path)
    _write_session_blob(
        coord,
        filename="session_a.json",
        map_id=2,
        start_ts=1000,
        end_ts=2000,
        wifi_samples=[[1.0, 1.0, -55, 1100]],
    )
    _write_heatmap(
        coord,
        object_name="wifimap_x.json",
        width=4, height=4, res_m=2,
        start_x_m=0.0, start_y_m=0.0,
    )
    # First run tags.
    assert coord._tag_wifi_archive_map_ids() == 1
    # Second run is a no-op.
    assert coord._tag_wifi_archive_map_ids() == 0


def test_tag_returns_zero_when_no_session_samples(tmp_path: Path):
    """When no session has wifi_samples, nothing to score against."""
    coord = _build_coordinator_skeleton(tmp_path)
    _write_session_blob(
        coord,
        filename="session_a.json",
        map_id=2,
        start_ts=1000,
        end_ts=2000,
        wifi_samples=[],  # empty
    )
    _write_heatmap(
        coord,
        object_name="wifimap_x.json",
        width=4, height=4, res_m=2,
        start_x_m=0.0, start_y_m=0.0,
    )
    assert coord._tag_wifi_archive_map_ids() == 0
    # Entry stays at -1.
    reloaded = coord._wifi_archive_store.load_index()
    assert reloaded[0].map_id == -1


def test_read_session_wifi_samples_round_trip(tmp_path: Path):
    """The disk reader normalises rows to (float, float, int, int) tuples."""
    coord = _build_coordinator_skeleton(tmp_path)
    _write_session_blob(
        coord,
        filename="session_a.json",
        map_id=3,
        start_ts=1000,
        end_ts=2000,
        wifi_samples=[
            [1.5, 2.5, -55, 1100],
            ["garbage", 0.0, 0, 0],  # filtered
            [3.0, 4.0, -60, 1200],
        ],
    )
    out = coord._read_session_wifi_samples("session_a.json")
    assert out == [
        (1.5, 2.5, -55, 1100),
        (3.0, 4.0, -60, 1200),
    ]


def test_read_session_wifi_samples_missing_key(tmp_path: Path):
    """A blob without wifi_samples returns []."""
    coord = _build_coordinator_skeleton(tmp_path)
    _write_session_blob(
        coord,
        filename="session_a.json",
        map_id=0,
        start_ts=1000,
        end_ts=2000,
        wifi_samples=None,  # type: ignore[arg-type]
    )
    assert coord._read_session_wifi_samples("session_a.json") == []
