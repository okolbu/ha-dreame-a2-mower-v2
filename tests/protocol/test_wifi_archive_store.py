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
