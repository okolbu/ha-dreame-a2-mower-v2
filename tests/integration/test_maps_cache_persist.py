"""Tests for map-cache persistence — _load_persisted_maps / _save_persisted_maps.

Goal: after a HA reload, map-metadata sensors (Name, Area, Segments, etc.)
populate immediately from disk instead of waiting for the first cloud
roundtrip. The cache stores the raw fetch_map dict (JSON-safe) and re-
parses on load via parse_cloud_maps.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


def _make_bare_coord():
    """Return a coordinator stub wired enough to exercise the persist methods."""
    from custom_components.dreame_a2_mower.coordinator import (
        DreameA2MowerCoordinator,
    )
    coord = object.__new__(DreameA2MowerCoordinator)
    coord._cached_maps_by_id = {}
    coord._maps_cache_store = None
    return coord


def test_save_persisted_maps_writes_raw_dict_to_store():
    import asyncio
    coord = _make_bare_coord()
    store = MagicMock()
    store.async_save = AsyncMock()
    coord._maps_cache_store = store

    payload = {0: {"mapIndex": 0, "name": "Back"}, 1: {"mapIndex": 1, "name": "Front"}}
    asyncio.run(coord._save_persisted_maps(payload))

    store.async_save.assert_awaited_once_with(payload)


def test_save_persisted_maps_silent_when_store_missing():
    import asyncio
    coord = _make_bare_coord()  # store is None
    # Must not raise.
    asyncio.run(coord._save_persisted_maps({0: {"mapIndex": 0}}))


def test_load_persisted_maps_populates_cache_and_syncs_subdevices():
    """Roundtrip: a Store containing the raw fetch_map dict (str-keyed
    after JSON serialisation) is restored into _cached_maps_by_id."""
    import asyncio
    import json
    from pathlib import Path

    coord = _make_bare_coord()

    # Reuse the live cloud-response fixture; JSON serialisation via HA's
    # Store roundtrips int keys as str — mirror that here.
    fixture_path = (
        Path(__file__).parent.parent
        / "protocol" / "fixtures" / "multi_map_response.json"
    )
    fixture = json.loads(fixture_path.read_text())
    raw = {str(k): v for k, v in fixture["by_id"].items()}

    store = MagicMock()
    store.async_load = AsyncMock(return_value=raw)
    coord._maps_cache_store = store
    coord._sync_map_subdevices = MagicMock()

    asyncio.run(coord._load_persisted_maps())

    assert 0 in coord._cached_maps_by_id
    assert 1 in coord._cached_maps_by_id
    coord._sync_map_subdevices.assert_called_once()


def test_load_persisted_maps_handles_missing_cache_silently():
    """async_load returning None must not error or alter the cache."""
    import asyncio
    coord = _make_bare_coord()
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    coord._maps_cache_store = store
    coord._sync_map_subdevices = MagicMock()

    asyncio.run(coord._load_persisted_maps())

    assert coord._cached_maps_by_id == {}
    coord._sync_map_subdevices.assert_not_called()


def test_load_persisted_maps_handles_unparsable_keys():
    """Garbage in the cache file must be ignored, not crash."""
    import asyncio
    coord = _make_bare_coord()
    store = MagicMock()
    store.async_load = AsyncMock(return_value={"not-an-int": {"mapIndex": 0}})
    coord._maps_cache_store = store
    coord._sync_map_subdevices = MagicMock()

    asyncio.run(coord._load_persisted_maps())

    assert coord._cached_maps_by_id == {}


def test_load_persisted_maps_silent_when_store_missing():
    import asyncio
    coord = _make_bare_coord()  # store stays None
    # Must not raise.
    asyncio.run(coord._load_persisted_maps())
    assert coord._cached_maps_by_id == {}
