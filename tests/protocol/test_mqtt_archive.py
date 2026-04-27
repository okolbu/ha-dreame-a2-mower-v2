"""Tests for the raw MQTT JSONL archive.

Every message the device client receives gets appended to a daily file,
giving an at-rest equivalent of the external probe's capture — but
from inside the HA process so nothing is missed during HA restarts.

The archive rotates on UTC-date boundaries and prunes files older than
``retain_days`` on every rotation.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from protocol.mqtt_archive import MqttArchive


@pytest.fixture
def tmp_archive_dir(tmp_path: Path) -> Path:
    return tmp_path / "mqtt_archive"


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def test_write_creates_file_named_by_utc_date(tmp_archive_dir: Path):
    archive = MqttArchive(tmp_archive_dir, clock=lambda: dt.datetime(2026, 4, 19, 10, 0))
    archive.write(topic="/status/x", payload=b'{"a":1}')

    expected = tmp_archive_dir / "2026-04-19.jsonl"
    assert expected.exists()


def test_json_decodable_payload_stored_as_structured_data(tmp_archive_dir: Path):
    archive = MqttArchive(tmp_archive_dir, clock=lambda: dt.datetime(2026, 4, 19, 10, 0))
    archive.write(topic="/status/x", payload=b'{"method":"foo"}')

    lines = _read_lines(tmp_archive_dir / "2026-04-19.jsonl")
    assert lines[0]["topic"] == "/status/x"
    assert lines[0]["payload"] == {"method": "foo"}
    assert "payload_hex" not in lines[0]


def test_non_json_payload_stored_as_hex(tmp_archive_dir: Path):
    archive = MqttArchive(tmp_archive_dir, clock=lambda: dt.datetime(2026, 4, 19, 10, 0))
    archive.write(topic="/status/x", payload=b"\xCE\x01\x02\xCE")

    lines = _read_lines(tmp_archive_dir / "2026-04-19.jsonl")
    assert lines[0]["payload_hex"] == "ce0102ce"
    assert "payload" not in lines[0]


def test_consecutive_writes_same_day_append_same_file(tmp_archive_dir: Path):
    archive = MqttArchive(tmp_archive_dir, clock=lambda: dt.datetime(2026, 4, 19, 10, 0))
    archive.write(topic="a", payload=b'{"k":1}')
    archive.write(topic="b", payload=b'{"k":2}')

    lines = _read_lines(tmp_archive_dir / "2026-04-19.jsonl")
    assert len(lines) == 2
    assert lines[0]["topic"] == "a"
    assert lines[1]["topic"] == "b"


def test_rotation_across_midnight_creates_new_file(tmp_archive_dir: Path):
    clock_time = [dt.datetime(2026, 4, 19, 23, 59, 50)]
    archive = MqttArchive(tmp_archive_dir, clock=lambda: clock_time[0])
    archive.write(topic="a", payload=b'{"k":1}')

    clock_time[0] = dt.datetime(2026, 4, 20, 0, 0, 5)
    archive.write(topic="b", payload=b'{"k":2}')

    assert (tmp_archive_dir / "2026-04-19.jsonl").exists()
    assert (tmp_archive_dir / "2026-04-20.jsonl").exists()
    lines_19 = _read_lines(tmp_archive_dir / "2026-04-19.jsonl")
    lines_20 = _read_lines(tmp_archive_dir / "2026-04-20.jsonl")
    assert lines_19[0]["topic"] == "a"
    assert lines_20[0]["topic"] == "b"


def test_rotation_prunes_files_older_than_retain_days(tmp_archive_dir: Path):
    tmp_archive_dir.mkdir(parents=True)
    # pre-seed three stale files
    (tmp_archive_dir / "2026-04-01.jsonl").write_text('{"old":1}\n')
    (tmp_archive_dir / "2026-04-10.jsonl").write_text('{"mid":1}\n')
    (tmp_archive_dir / "2026-04-17.jsonl").write_text('{"recent":1}\n')

    # retain_days=3 means anything older than 2026-04-16 (inclusive) gets pruned
    archive = MqttArchive(
        tmp_archive_dir,
        retain_days=3,
        clock=lambda: dt.datetime(2026, 4, 19, 10, 0),
    )
    archive.write(topic="now", payload=b'{"k":1}')

    assert not (tmp_archive_dir / "2026-04-01.jsonl").exists()
    assert not (tmp_archive_dir / "2026-04-10.jsonl").exists()
    assert (tmp_archive_dir / "2026-04-17.jsonl").exists()
    assert (tmp_archive_dir / "2026-04-19.jsonl").exists()


def test_prune_ignores_unrelated_files(tmp_archive_dir: Path):
    tmp_archive_dir.mkdir(parents=True)
    (tmp_archive_dir / "README").write_text("manual notes")
    (tmp_archive_dir / "not-a-date.jsonl").write_text("garbage")

    archive = MqttArchive(
        tmp_archive_dir,
        retain_days=3,
        clock=lambda: dt.datetime(2026, 4, 19, 10, 0),
    )
    archive.write(topic="now", payload=b'{"k":1}')

    assert (tmp_archive_dir / "README").exists()
    assert (tmp_archive_dir / "not-a-date.jsonl").exists()


def test_timestamp_is_milliseconds_since_epoch(tmp_archive_dir: Path):
    fixed = dt.datetime(2026, 4, 19, 10, 0, 0, 123000, tzinfo=dt.timezone.utc)
    archive = MqttArchive(tmp_archive_dir, clock=lambda: fixed)
    archive.write(topic="a", payload=b'{"k":1}')

    lines = _read_lines(tmp_archive_dir / "2026-04-19.jsonl")
    # 2026-04-19T10:00:00.123Z → ms since epoch
    assert lines[0]["ts_ms"] == int(fixed.timestamp() * 1000)


def test_write_is_safe_when_parent_directory_missing(tmp_path: Path):
    # Don't pre-create the archive dir — writer creates it lazily.
    archive = MqttArchive(
        tmp_path / "deep" / "nested" / "archive",
        clock=lambda: dt.datetime(2026, 4, 19, 10, 0),
    )
    archive.write(topic="a", payload=b'{"k":1}')
    assert (tmp_path / "deep" / "nested" / "archive" / "2026-04-19.jsonl").exists()
