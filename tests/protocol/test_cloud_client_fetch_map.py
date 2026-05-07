"""Tests for cloud_client.fetch_map multi-map split via MAP.info."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from custom_components.dreame_a2_mower.cloud_client import DreameA2CloudClient


def _make_client(batch_response):
    client = object.__new__(DreameA2CloudClient)
    client.get_batch_device_datas = MagicMock(return_value=batch_response)
    return client


def _build_batch(map_jsons: list[dict]) -> dict:
    """Encode a list of map JSON dicts as if they were the cloud's
    MAP.0..MAP.27 batch reply, with MAP.info giving the split point.
    """
    parts = [json.dumps([m]) for m in map_jsons]  # cloud wraps each in []
    full = "".join(parts)
    info = str(len(parts[0])) if len(parts) > 1 else "0"
    out = {f"MAP.{i}": "" for i in range(28)}
    # Pack the full string into MAP.0; other slots empty (legal).
    out["MAP.0"] = full
    out["MAP.info"] = info
    return out


def test_fetch_map_returns_dict_by_id_for_two_maps():
    map0 = {"boundary": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}, "mowingAreas": {}, "mapIndex": 0, "name": "Map 1", "totalArea": 100}
    map1 = {"boundary": {"x1": 20, "y1": 0, "x2": 30, "y2": 10}, "mowingAreas": {}, "mapIndex": 1, "name": "Map 2", "totalArea": 80}
    client = _make_client(_build_batch([map0, map1]))

    result = client.fetch_map()

    assert isinstance(result, dict)
    assert set(result.keys()) == {0, 1}
    assert result[0]["name"] == "Map 1"
    assert result[1]["name"] == "Map 2"


def test_fetch_map_returns_dict_with_single_entry_for_one_map():
    map0 = {"boundary": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}, "mowingAreas": {}, "mapIndex": 0, "name": "Map 1", "totalArea": 100}
    client = _make_client(_build_batch([map0]))

    result = client.fetch_map()

    assert isinstance(result, dict)
    assert set(result.keys()) == {0}
    assert result[0]["name"] == "Map 1"


def test_fetch_map_returns_none_on_empty_batch():
    client = _make_client({})
    assert client.fetch_map() is None


def test_fetch_map_handles_list_of_json_strings():
    """Cloud's wrapped-list-of-strings form: top-level JSON is a list
    whose entries are JSON-encoded strings (each string is a map dict).
    Old fetch_map handled this; the multi-map reshape regressed it.
    """
    map0 = {"boundary": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}, "mowingAreas": {}, "mapIndex": 0, "name": "Map 1", "totalArea": 100}
    # Build batch where MAP.0 contains a JSON list of JSON-encoded strings
    full = json.dumps([json.dumps(map0)])
    out = {f"MAP.{i}": "" for i in range(28)}
    out["MAP.0"] = full
    out["MAP.info"] = "0"
    client = _make_client(out)

    result = client.fetch_map()

    assert isinstance(result, dict)
    assert set(result.keys()) == {0}
    assert result[0]["name"] == "Map 1"
