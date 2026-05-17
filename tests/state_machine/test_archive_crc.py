"""CRC32 footer helpers for in_progress.json integrity."""
from custom_components.dreame_a2_mower.archive.session import (
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
