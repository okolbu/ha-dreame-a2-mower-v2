"""Tests for wifi_archive_store: disk-backed wifimap archive."""
from __future__ import annotations

import json
from pathlib import Path

from custom_components.dreame_a2_mower.wifi_archive_store import (
    WifiArchiveStore,
    WifiArchiveEntry,
)


def test_load_empty_returns_empty_list(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    assert store.load_index() == []


def test_write_then_load_round_trip(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    body = {"data": [-50] * 16, "width": 4, "height": 4, "resolution": 2,
            "startX": 100, "startY": 200}
    entry = store.archive(
        object_name="wifimap_1700000001.json",
        body=body,
        first_seen_unix=1747000000,
    )
    assert entry.object_name == "wifimap_1700000001.json"
    assert entry.unix_ts == 1700000001
    assert entry.width == 4 and entry.height == 4 and entry.resolution == 2
    assert entry.startX == 100 and entry.startY == 200
    assert entry.first_seen_unix == 1747000000

    loaded = store.load_index()
    assert len(loaded) == 1
    assert loaded[0].object_name == "wifimap_1700000001.json"

    body_loaded = store.load_body("wifimap_1700000001.json")
    assert body_loaded == body


def test_archive_is_idempotent(tmp_path: Path):
    """Calling archive() twice with the same object_name does NOT duplicate
    the index entry, and does NOT update first_seen_unix."""
    store = WifiArchiveStore(tmp_path)
    body = {"data": [-50], "width": 1, "height": 1, "resolution": 2,
            "startX": 0, "startY": 0}
    store.archive("wifimap_1700000001.json", body, first_seen_unix=100)
    store.archive("wifimap_1700000001.json", body, first_seen_unix=999)
    loaded = store.load_index()
    assert len(loaded) == 1
    assert loaded[0].first_seen_unix == 100  # original wins


def test_has_object(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    assert not store.has_object("wifimap_1.json")
    store.archive("wifimap_1.json",
                  {"data": [], "width": 0, "height": 0, "resolution": 2,
                   "startX": 0, "startY": 0},
                  first_seen_unix=0)
    assert store.has_object("wifimap_1.json")


def test_load_body_unknown_returns_none(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    assert store.load_body("never_archived.json") is None


def test_parse_unix_ts_from_filename(tmp_path: Path):
    store = WifiArchiveStore(tmp_path)
    # Standard pattern.
    assert store._parse_unix_ts("wifimap_1700000001.json") == 1700000001
    # Trailing extra suffix.
    assert store._parse_unix_ts("wifimap_1700000001_v2.json") == 1700000001
    # Garbage name.
    assert store._parse_unix_ts("not_a_wifimap.json") == 0


def test_load_index_handles_corrupt_json(tmp_path: Path):
    """A corrupt index.json file is treated as 'no entries' — does not raise."""
    store = WifiArchiveStore(tmp_path)
    store.index_path.write_text("{not valid json")
    assert store.load_index() == []


def test_archive_rejects_traversal_in_object_name(tmp_path: Path):
    import pytest
    store = WifiArchiveStore(tmp_path)
    body = {"data": [], "width": 0, "height": 0, "resolution": 2,
            "startX": 0, "startY": 0}
    with pytest.raises(ValueError):
        store.archive("../etc/passwd", body, first_seen_unix=0)
    with pytest.raises(ValueError):
        store.archive("/etc/passwd", body, first_seen_unix=0)
    with pytest.raises(ValueError):
        store.archive("~/.ssh/id_rsa", body, first_seen_unix=0)
    with pytest.raises(ValueError):
        store.archive("foo/../bar.json", body, first_seen_unix=0)


def test_archive_accepts_nested_oss_path(tmp_path: Path):
    """Cloud OSS object names with date-partition directories are valid."""
    store = WifiArchiveStore(tmp_path)
    body = {"data": [-50] * 4, "width": 2, "height": 2, "resolution": 2,
            "startX": 0, "startY": 0}
    oss_name = "ali_dreame/2026/05/11/BM169439/-112293549_154215647.0550.txt"
    entry = store.archive(oss_name, body, first_seen_unix=1747000000)

    # object_name in the index is the full OSS path (cloud identity).
    assert entry.object_name == oss_name
    # The disk file is flattened (no nested dirs in archive root).
    disk_name = "ali_dreame__2026__05__11__BM169439__-112293549_154215647.0550.txt"
    assert (tmp_path / disk_name).is_file()
    assert not (tmp_path / "ali_dreame").exists()

    # Round-trip lookups work via the OSS name.
    assert store.has_object(oss_name)
    assert store.load_body(oss_name) == body


def test_parse_unix_ts_from_date_partition(tmp_path: Path):
    """When the filename has no unix-ts, fall back to YYYY/MM/DD from path."""
    store = WifiArchiveStore(tmp_path)
    # 2026-05-11 UTC midnight = 1778457600.
    ts = store._parse_unix_ts(
        "ali_dreame/2026/05/11/BM169439/-112293549_154215647.0550.txt"
    )
    from datetime import datetime, timezone
    expected = int(datetime(2026, 5, 11, tzinfo=timezone.utc).timestamp())
    assert ts == expected


def test_parse_unix_ts_date_partition_wins_over_filename_digits(tmp_path: Path):
    """When both signals are present, date-partition wins.

    Cloud OSS paths put session IDs in the filename underscores
    (`_154215647` is NOT a 2026 timestamp); the date-partition in
    the path is the authoritative signal.
    """
    store = WifiArchiveStore(tmp_path)
    ts = store._parse_unix_ts("partition/2026/05/11/wifimap_1700000001.json")
    from datetime import datetime, timezone
    expected = int(datetime(2026, 5, 11, tzinfo=timezone.utc).timestamp())
    assert ts == expected


def test_parse_unix_ts_legacy_filename_only(tmp_path: Path):
    """When there's no date partition, fall back to the underscore-ts regex."""
    store = WifiArchiveStore(tmp_path)
    assert store._parse_unix_ts("wifimap_1700000001.json") == 1700000001
