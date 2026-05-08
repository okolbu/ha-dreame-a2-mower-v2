"""Tests for cloud_client.write_chunked_key — chunking + endpoint."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def _make_client() -> DreameA2CloudClient:
    client = object.__new__(DreameA2CloudClient)
    client._did = "test_did"
    client.set_batch_device_datas = MagicMock(
        return_value={"code": 0, "success": True, "msg": "ok"}
    )
    return client


def test_write_chunked_key_short_value_single_chunk_no_info():
    """Values ≤ 1024 chars emit a single .0 chunk with no .info field."""
    client = _make_client()
    ok, resp = client.write_chunked_key("AI_HUMAN", '"true"')
    assert ok is True
    client.set_batch_device_datas.assert_called_once_with(
        {"AI_HUMAN.0": '"true"'}
    )


def test_write_chunked_key_long_value_chunks_with_info():
    """Values > 1024 chars split into ≤1024 chunks + .info field."""
    client = _make_client()
    value = "x" * 1500  # → chunk 0 of 1024 + chunk 1 of 476 + info=1500
    ok, resp = client.write_chunked_key("SETTINGS", value)
    assert ok is True
    expected = {
        "SETTINGS.0": "x" * 1024,
        "SETTINGS.1": "x" * 476,
        "SETTINGS.info": "1500",
    }
    client.set_batch_device_datas.assert_called_once_with(expected)


def test_write_chunked_key_exactly_1024_chars_single_chunk():
    """Boundary: value of exactly 1024 chars fits in one chunk."""
    client = _make_client()
    ok, _ = client.write_chunked_key("KEY", "x" * 1024)
    client.set_batch_device_datas.assert_called_once_with({"KEY.0": "x" * 1024})


def test_write_chunked_key_1025_chars_two_chunks():
    """Boundary: 1025 chars → chunk 0 of 1024 + chunk 1 of 1."""
    client = _make_client()
    ok, _ = client.write_chunked_key("KEY", "x" * 1025)
    client.set_batch_device_datas.assert_called_once_with({
        "KEY.0": "x" * 1024,
        "KEY.1": "x",
        "KEY.info": "1025",
    })


def test_write_chunked_key_explicit_info_override():
    """Caller can pass info= for keys where .info isn't total length."""
    client = _make_client()
    ok, _ = client.write_chunked_key("M_PATH", "abc", info="0")
    client.set_batch_device_datas.assert_called_once_with({
        "M_PATH.0": "abc",
        "M_PATH.info": "0",
    })


def test_write_chunked_key_returns_false_on_cloud_rejection():
    """code != 0 from cloud → ok=False, response preserved for caller."""
    client = _make_client()
    client.set_batch_device_datas = MagicMock(
        return_value={"code": 10007, "success": False, "msg": "bad value"}
    )
    ok, resp = client.write_chunked_key("KEY", "v")
    assert ok is False
    assert resp == {"code": 10007, "success": False, "msg": "bad value"}


def test_write_chunked_key_returns_false_on_none_response():
    client = _make_client()
    client.set_batch_device_datas = MagicMock(return_value=None)
    ok, resp = client.write_chunked_key("KEY", "v")
    assert ok is False
    assert resp is None


def test_write_chunked_key_empty_value_writes_single_empty_chunk():
    """Writing empty string → KEY.0 = '' (used to clear a slot)."""
    client = _make_client()
    ok, _ = client.write_chunked_key("KEY", "")
    client.set_batch_device_datas.assert_called_once_with({"KEY.0": ""})
