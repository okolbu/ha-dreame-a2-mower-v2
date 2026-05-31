"""Tests for cloud_client.list_3dmap_objects.

The s2.50 OBJ routed action with type='3dmap' lists the LiDAR PCD OSS
objects (the same `.0550.bin` objects s99.20 announces over MQTT),
newest-first. Used by the startup LiDAR backfill so fresh installs don't
wait for a live "View LiDAR Map" push.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def _client(action_return):
    client = object.__new__(DreameA2CloudClient)
    client.action = MagicMock(return_value=action_return)
    return client


def test_lists_object_names_filtering_empty_strings():
    """Returns the non-empty object-name strings from out[0].d.name."""
    client = _client({"out": [{"d": {"name": [
        "",  # the leading empty placeholder the firmware emits
        "ali_dreame/2026/05/10/BM169439/-112293549_170348301.0550.bin",
        "ali_dreame/2026/04/20/BM169439/-112293549_154157120.0550.bin",
    ]}}]})

    result = client.list_3dmap_objects()

    assert result == [
        "ali_dreame/2026/05/10/BM169439/-112293549_170348301.0550.bin",
        "ali_dreame/2026/04/20/BM169439/-112293549_154157120.0550.bin",
    ]


def test_issues_the_obj_3dmap_routed_action():
    """Calls action(siid=2, aiid=50, [{m:g, t:OBJ, d:{type:3dmap}}])."""
    client = _client({"out": [{"d": {"name": []}}]})

    client.list_3dmap_objects()

    client.action.assert_called_once_with(
        siid=2, aiid=50,
        parameters=[{"m": "g", "t": "OBJ", "d": {"type": "3dmap"}}],
    )


def test_empty_list_when_no_objects():
    """An accepted-but-empty response returns [] (NOT None) — distinguishes
    'no 3dmaps yet' from 'relay failed', so the caller can stop retrying."""
    client = _client({"out": [{"d": {"name": []}}]})
    assert client.list_3dmap_objects() == []


def test_none_on_relay_failure():
    """A failed/None action response returns None so the caller retries."""
    assert _client(None).list_3dmap_objects() is None


def test_none_on_malformed_response():
    """A response missing the out/d/name path returns None."""
    assert _client({"code": 80001}).list_3dmap_objects() is None
    assert _client({"out": []}).list_3dmap_objects() is None
