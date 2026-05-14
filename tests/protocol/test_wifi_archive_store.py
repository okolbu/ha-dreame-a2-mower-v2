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
    """When the filename has no parsable HH:MM:SS prefix, fall back to YYYY/MM/DD midnight UTC."""
    store = WifiArchiveStore(tmp_path)
    # 2026-05-11 UTC midnight = 1778457600. Use a filename that has no
    # 9-digit run looking like HHMMSSxxx — bare object name only.
    ts = store._parse_unix_ts("ali_dreame/2026/05/11/BM169439/some_object.txt")
    from datetime import datetime, timezone
    expected = int(datetime(2026, 5, 11, tzinfo=timezone.utc).timestamp())
    assert ts == expected


def test_parse_unix_ts_date_partition_refined_by_hhmmss(tmp_path: Path):
    """v1.0.10a6+: when the filename component carries an HHMMSSxxx prefix
    (e.g., ``_154215647``), the parser refines the date-partition midnight
    by that HH:MM:SS so two heatmaps generated on the same day get
    distinct ``unix_ts`` values (otherwise they collide on the picker
    dropdown label)."""
    store = WifiArchiveStore(tmp_path)
    ts = store._parse_unix_ts(
        "ali_dreame/2026/05/11/BM169439/-112293549_154215647.0550.txt"
    )
    from datetime import datetime, timezone
    midnight = int(datetime(2026, 5, 11, tzinfo=timezone.utc).timestamp())
    # 15:42:15
    expected = midnight + 15 * 3600 + 42 * 60 + 15
    assert ts == expected


def test_parse_unix_ts_intra_day_disambiguation(tmp_path: Path):
    """Two heatmaps generated the same day must produce distinct unix_ts
    so the picker shows distinct rows. This is the duplicate-row fix."""
    store = WifiArchiveStore(tmp_path)
    morning = store._parse_unix_ts(
        "ali_dreame/2026/05/13/BM169439/-112293549_082656885.0550.txt"
    )
    evening = store._parse_unix_ts(
        "ali_dreame/2026/05/13/BM169439/-112293549_183837060.0550.txt"
    )
    assert morning != evening
    # Morning is earlier than evening on the same date.
    assert morning < evening


def test_parse_unix_ts_date_partition_wins_over_filename_digits(tmp_path: Path):
    """When both signals are present, date-partition wins (refined by HMS).

    Cloud OSS paths put session IDs in the filename underscores.
    The legacy `wifimap_1700000001.json` form is only used when no
    date-partition is present.
    """
    store = WifiArchiveStore(tmp_path)
    # `wifimap_1700000001` is a 10-digit run, not a 9-digit HHMMSSxxx
    # pattern, so no HMS refinement applies — falls back to midnight UTC.
    ts = store._parse_unix_ts("partition/2026/05/11/wifimap_1700000001.json")
    from datetime import datetime, timezone
    expected = int(datetime(2026, 5, 11, tzinfo=timezone.utc).timestamp())
    assert ts == expected


def test_parse_unix_ts_legacy_filename_only(tmp_path: Path):
    """When there's no date partition, fall back to the underscore-ts regex."""
    store = WifiArchiveStore(tmp_path)
    assert store._parse_unix_ts("wifimap_1700000001.json") == 1700000001


# ----------------- v1.0.10a6+ additions -----------------


def test_archive_dedup_same_unix_ts_and_geometry(tmp_path: Path):
    """Two different object_names with identical (unix_ts, geometry)
    must collapse to a single index entry — that's the picker
    duplicate-row fix."""
    store = WifiArchiveStore(tmp_path)
    body = {"data": [-50] * 4, "width": 2, "height": 2, "resolution": 2,
            "startX": 0, "startY": 0}
    # Same date-partition, different filename suffixes that produce
    # IDENTICAL HHMMSS (i.e. mid-second collision is unrealistic but
    # exposes the dedup independently of timestamp parsing).
    e1 = store.archive(
        "ali_dreame/2026/05/13/dev1/-1_120000000.A.txt",
        body, first_seen_unix=100,
    )
    e2 = store.archive(
        "ali_dreame/2026/05/13/dev1/-1_120000999.B.txt",
        body, first_seen_unix=200,
    )
    assert e1.unix_ts == e2.unix_ts
    # Both share geometry, so e2 returns the same row as e1.
    assert e2.object_name == e1.object_name
    idx = store.load_index()
    assert len(idx) == 1


def test_archive_keeps_distinct_when_geometry_differs(tmp_path: Path):
    """Identical timestamps but different geometry → both rows survive."""
    store = WifiArchiveStore(tmp_path)
    body_a = {"data": [-50] * 4, "width": 2, "height": 2, "resolution": 2,
              "startX": 0, "startY": 0}
    body_b = {"data": [-50] * 9, "width": 3, "height": 3, "resolution": 2,
              "startX": 0, "startY": 0}
    store.archive("ali_dreame/2026/05/13/d/a_120000000.txt", body_a, 100)
    store.archive("ali_dreame/2026/05/13/d/b_120000000.txt", body_b, 200)
    idx = store.load_index()
    assert len(idx) == 2


def test_load_index_backward_compat_no_map_id_field(tmp_path: Path):
    """Legacy index.json without `map_id` keys must load with map_id=-1."""
    store = WifiArchiveStore(tmp_path)
    # Write a legacy-format index manually.
    legacy = [
        {
            "object_name": "wifimap_1700000001.json",
            "unix_ts": 1700000001,
            "width": 2, "height": 2, "resolution": 2,
            "startX": 0, "startY": 0,
            "first_seen_unix": 100,
        }
    ]
    store.index_path.write_text(json.dumps(legacy))
    loaded = store.load_index()
    assert len(loaded) == 1
    assert loaded[0].map_id == -1


def test_set_map_id_persists(tmp_path: Path):
    """set_map_id rewrites the index and survives a reload."""
    store = WifiArchiveStore(tmp_path)
    body = {"data": [], "width": 0, "height": 0, "resolution": 2,
            "startX": 0, "startY": 0}
    store.archive("wifimap_1700000001.json", body, 100)
    assert store.set_map_id("wifimap_1700000001.json", 3) is True
    # Idempotent.
    assert store.set_map_id("wifimap_1700000001.json", 3) is False
    reloaded = store.load_index()
    assert reloaded[0].map_id == 3


def test_set_map_id_unknown_object_no_op(tmp_path: Path):
    """set_map_id on a missing object name is a no-op (returns False)."""
    store = WifiArchiveStore(tmp_path)
    assert store.set_map_id("not_in_index.json", 1) is False
