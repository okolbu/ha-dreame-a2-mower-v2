"""Tests for custom_components.dreame_a2_mower.archive.session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.archive.session import (
    ArchivedSession,
    INDEX_NAME,
    IN_PROGRESS_NAME,
    IN_PROGRESS_MAX_AGE_S,
    SessionArchive,
)
from custom_components.dreame_a2_mower.protocol.session_summary import parse_session_summary


FIXTURE_PATH = (
    Path(__file__).parent.parent / "protocol" / "fixtures" / "session_summary_2026-04-18.json"
)


@pytest.fixture
def raw_json() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture
def summary(raw_json):
    return parse_session_summary(raw_json)


def test_fresh_archive_is_empty(tmp_path):
    a = SessionArchive(tmp_path)
    assert a.count == 0
    assert a.latest() is None
    assert a.list_sessions() == []


def test_archive_writes_file_and_index(tmp_path, summary, raw_json):
    a = SessionArchive(tmp_path)
    entry = a.archive(summary, raw_json=raw_json)

    assert entry is not None
    assert a.count == 1
    file_path = tmp_path / entry.filename
    assert file_path.exists()
    # Wire payload preserved verbatim.
    assert json.loads(file_path.read_text()) == raw_json
    # Index lists the entry.
    idx = json.loads((tmp_path / INDEX_NAME).read_text())
    assert idx["version"] == 1
    assert len(idx["sessions"]) == 1
    assert idx["sessions"][0]["md5"] == summary.md5


def test_filename_shape(tmp_path, summary, raw_json):
    a = SessionArchive(tmp_path)
    entry = a.archive(summary, raw_json=raw_json)
    # Expected: YYYY-MM-DD_<end_ts>_<md5_prefix>.json
    parts = entry.filename.removesuffix(".json").split("_")
    assert len(parts) == 3
    assert parts[0].count("-") == 2           # date
    assert parts[1].isdigit()                  # end_ts
    assert parts[2] == summary.md5[:8]


def test_archive_is_idempotent_by_md5_and_start_ts(tmp_path, summary, raw_json):
    """Re-archiving the SAME (md5, start_ts) is a no-op."""
    a = SessionArchive(tmp_path)
    first = a.archive(summary, raw_json=raw_json)
    second = a.archive(summary, raw_json=raw_json)
    assert first is not None
    assert second is None
    assert a.count == 1


def test_archive_accepts_same_md5_with_different_start_ts(tmp_path, summary, raw_json):
    """v1.0.0a51: g2408's cloud reuses the same md5 across every
    session that runs against an unchanged map. The dedup key now
    includes start_ts so a second mow after the first archives
    correctly instead of being dropped silently."""
    import dataclasses
    a = SessionArchive(tmp_path)
    first = a.archive(summary, raw_json=raw_json)
    assert first is not None

    second_summary = dataclasses.replace(
        summary,
        start_ts=summary.start_ts + 600,   # 10 min later
        end_ts=summary.end_ts + 600,
    )
    second = a.archive(second_summary, raw_json=raw_json)
    assert second is not None
    assert a.count == 2


def test_latest_returns_highest_end_ts(tmp_path):
    a = SessionArchive(tmp_path)

    class S:
        def __init__(self, md5, end_ts):
            self.md5 = md5
            self.end_ts = end_ts
            self.start_ts = end_ts - 100
            self.duration_min = 1
            self.area_mowed_m2 = 1.0
            self.map_area_m2 = 100
            self.mode = 0
            self.result = 0
            self.stop_reason = 0
            self.start_mode = 0
            self.pre_type = 0
            self.dock = None

    a.archive(S("hash-a", 1000))
    a.archive(S("hash-b", 3000))
    a.archive(S("hash-c", 2000))
    assert a.latest().md5 == "hash-b"
    assert [s.md5 for s in a.list_sessions()] == ["hash-b", "hash-c", "hash-a"]


def test_loads_existing_index_on_reopen(tmp_path, summary, raw_json):
    a1 = SessionArchive(tmp_path)
    a1.archive(summary, raw_json=raw_json)
    # New instance should see the persisted session.
    a2 = SessionArchive(tmp_path)
    assert a2.count == 1
    assert a2.latest().md5 == summary.md5


def test_corrupt_index_is_tolerated(tmp_path):
    (tmp_path / INDEX_NAME).write_text("{not valid json")
    a = SessionArchive(tmp_path)
    assert a.count == 0  # no crash, just empty


def test_load_returns_raw_json(tmp_path, summary, raw_json):
    a = SessionArchive(tmp_path)
    entry = a.archive(summary, raw_json=raw_json)
    loaded = a.load(entry)
    assert loaded == raw_json


def test_load_missing_file_returns_none(tmp_path):
    a = SessionArchive(tmp_path)
    entry = ArchivedSession(
        filename="no-such-file.json",
        start_ts=0, end_ts=0, duration_min=0, area_mowed_m2=0.0,
        map_area_m2=0, md5="",
    )
    assert a.load(entry) is None


def test_archive_without_raw_json_falls_back(tmp_path, summary):
    a = SessionArchive(tmp_path)
    entry = a.archive(summary, raw_json=None)
    loaded = a.load(entry)
    # Fallback reconstruction contains the scalar fields with a note.
    assert loaded["md5"] == summary.md5
    assert "_note" in loaded


# -------------------- in-progress entry --------------------


def test_in_progress_absent_by_default(tmp_path):
    a = SessionArchive(tmp_path)
    assert a.read_in_progress() is None
    assert a.in_progress_entry() is None


def test_in_progress_round_trip(tmp_path):
    a = SessionArchive(tmp_path)
    payload = {
        "session_start_ts": 1776840000,
        "live_path": [[1.0, 2.0], [1.5, 2.5]],
        "obstacles": [],
        "leg_md5s": [],
        "area_mowed_m2": 12.34,
        "map_area_m2": 200,
    }
    a.write_in_progress(payload)
    got = a.read_in_progress()
    assert got["session_start_ts"] == 1776840000
    assert got["live_path"] == [[1.0, 2.0], [1.5, 2.5]]
    assert got["area_mowed_m2"] == 12.34
    # Stamped automatically.
    assert got["version"] == 1
    assert got["last_update_ts"] >= got["session_start_ts"]


def test_in_progress_entry_synthesizes_archived_session(tmp_path):
    a = SessionArchive(tmp_path)
    a.write_in_progress({
        "session_start_ts": 1776840000,
        "live_path": [[0.0, 0.0]],
        "obstacles": [],
        "leg_md5s": [],
        "area_mowed_m2": 5.5,
        "map_area_m2": 150,
    })
    entry = a.in_progress_entry()
    assert entry is not None
    assert entry.still_running is True
    assert entry.start_ts == 1776840000
    assert entry.end_ts >= entry.start_ts
    assert entry.area_mowed_m2 == 5.5
    assert entry.map_area_m2 == 150
    assert entry.md5 == ""
    assert entry.filename == IN_PROGRESS_NAME


def test_in_progress_appears_at_top_of_list_sessions(tmp_path):
    a = SessionArchive(tmp_path)

    class S:
        def __init__(self, md5, end_ts):
            self.md5 = md5
            self.end_ts = end_ts
            self.start_ts = end_ts - 100
            self.duration_min = 1
            self.area_mowed_m2 = 1.0
            self.map_area_m2 = 100
            self.mode = 0
            self.result = 0
            self.stop_reason = 0
            self.start_mode = 0
            self.pre_type = 0
            self.dock = None

    a.archive(S("hash-a", 1776700000))
    a.archive(S("hash-b", 1776800000))
    a.write_in_progress({
        "session_start_ts": 1776840000,
        "live_path": [],
        "obstacles": [],
        "leg_md5s": [],
        "area_mowed_m2": 0.0,
        "map_area_m2": 0,
    })

    listed = a.list_sessions()
    assert listed[0].still_running is True
    assert listed[0].filename == IN_PROGRESS_NAME
    assert [s.md5 for s in listed[1:]] == ["hash-b", "hash-a"]
    # latest() prefers in-progress.
    assert a.latest().still_running is True


def test_in_progress_stale_is_auto_deleted(tmp_path):
    a = SessionArchive(tmp_path)
    # Write a payload with an obviously-ancient last_update_ts. The
    # writer always restamps on write, so we craft the file directly.
    path = tmp_path / IN_PROGRESS_NAME
    ancient_ts = 0  # epoch zero — well past IN_PROGRESS_MAX_AGE_S
    path.write_text(json.dumps({
        "version": 1,
        "session_start_ts": 0,
        "last_update_ts": ancient_ts,
        "live_path": [],
        "obstacles": [],
    }))
    assert a.read_in_progress() is None
    assert not path.exists()


def test_delete_in_progress_is_idempotent(tmp_path):
    a = SessionArchive(tmp_path)
    a.delete_in_progress()  # no-op when absent
    a.write_in_progress({
        "session_start_ts": 1776840000,
        "live_path": [],
        "obstacles": [],
    })
    assert (tmp_path / IN_PROGRESS_NAME).exists()
    a.delete_in_progress()
    assert not (tmp_path / IN_PROGRESS_NAME).exists()
    a.delete_in_progress()  # no-op again


def test_promote_in_progress_archives_and_clears(tmp_path, summary, raw_json):
    a = SessionArchive(tmp_path)
    a.write_in_progress({
        "session_start_ts": int(summary.start_ts) - 10,
        "live_path": [],
        "obstacles": [],
    })
    entry = a.promote_in_progress(summary, raw_json=raw_json)
    assert entry is not None
    assert a.has(summary.md5)
    assert a.in_progress_entry() is None
    assert not (tmp_path / IN_PROGRESS_NAME).exists()


def test_find_covering_session_matches_within_window(tmp_path, summary, raw_json):
    """Archive-based dedup (alpha.94): `find_covering_session` returns
    the archived entry whose start_ts is within ±window_s of the query."""
    a = SessionArchive(tmp_path)
    a.archive(summary, raw_json=raw_json)
    # Exact match.
    hit = a.find_covering_session(int(summary.start_ts))
    assert hit is not None and hit.md5 == summary.md5
    # Within window (default 120 s).
    hit = a.find_covering_session(int(summary.start_ts) + 60)
    assert hit is not None and hit.md5 == summary.md5
    hit = a.find_covering_session(int(summary.start_ts) - 119)
    assert hit is not None and hit.md5 == summary.md5
    # Outside window — no match.
    hit = a.find_covering_session(int(summary.start_ts) + 500)
    assert hit is None
    # Invalid input — no match, no error.
    assert a.find_covering_session(0) is None
    assert a.find_covering_session(-1) is None


def test_find_covering_session_with_empty_archive(tmp_path):
    a = SessionArchive(tmp_path)
    assert a.find_covering_session(1_700_000_000) is None
