"""CRC32 footer helpers for in_progress.json integrity."""
import json
from pathlib import Path

from custom_components.dreame_a2_mower.archive.session import (
    SessionArchive,
    _compute_crc32,
    _verify_crc32,
)


def test_compute_crc32_stable_under_key_reorder():
    """Same payload, two different key orders, same CRC."""
    a = {"alpha": 1, "beta": 2, "gamma": [3, 4]}
    b = {"gamma": [3, 4], "alpha": 1, "beta": 2}
    assert _compute_crc32(a) == _compute_crc32(b)


def test_compute_crc32_changes_with_value():
    a = {"x": 1}
    b = {"x": 2}
    assert _compute_crc32(a) != _compute_crc32(b)


def test_verify_crc32_accepts_correct_payload():
    payload = {"foo": "bar", "n": 42}
    crc = _compute_crc32(payload)
    payload["__crc32__"] = crc
    assert _verify_crc32(payload) is True


def test_verify_crc32_rejects_tampered_payload():
    payload = {"foo": "bar"}
    payload["__crc32__"] = _compute_crc32(payload)
    payload["foo"] = "baz"  # tampered after CRC was set
    assert _verify_crc32(payload) is False


def test_verify_crc32_rejects_missing_field():
    """Old archives without __crc32__ return False (caller treats as missing)."""
    assert _verify_crc32({"foo": "bar"}) is False


def test_verify_crc32_rejects_non_int_field():
    assert _verify_crc32({"foo": "bar", "__crc32__": "not-an-int"}) is False


def test_write_in_progress_includes_crc(tmp_path: Path) -> None:
    """The written JSON file has a __crc32__ field that matches its body."""
    archive = SessionArchive(tmp_path)
    payload = {"session_start_ts": 1234567890, "legs": [], "battery_samples": []}
    archive.write_in_progress(payload)
    on_disk_path = tmp_path / "in_progress.json"
    assert on_disk_path.exists()
    disk = json.loads(on_disk_path.read_text())
    assert "__crc32__" in disk
    assert _compute_crc32(disk) == disk["__crc32__"]


def test_read_in_progress_rejects_corrupted_file(tmp_path: Path) -> None:
    """If __crc32__ doesn't match, read_in_progress returns None."""
    archive = SessionArchive(tmp_path)
    payload = {"session_start_ts": 1234567890, "legs": []}
    archive.write_in_progress(payload)
    on_disk_path = tmp_path / "in_progress.json"
    disk = json.loads(on_disk_path.read_text())
    disk["session_start_ts"] = 999  # tampered
    on_disk_path.write_text(json.dumps(disk))
    # Also invalidate the in-memory cache so read_in_progress hits disk.
    archive._in_progress_cached = (0.0, None)
    assert archive.read_in_progress() is None
