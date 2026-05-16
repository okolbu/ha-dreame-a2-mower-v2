"""Tests for the persistent novel-observation JSONL store."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from custom_components.dreame_a2_mower.observability.novel_store import (
    PersistentNovelStore,
)
from custom_components.dreame_a2_mower.observability.registry import (
    NovelObservationRegistry,
)


@pytest.mark.asyncio
async def test_load_missing_file_returns_zero(tmp_path: Path) -> None:
    """First-run case: no file exists, load returns 0 and doesn't crash."""
    store = PersistentNovelStore(tmp_path / "novel_observations.jsonl")
    reg = NovelObservationRegistry()
    n = await store.load(reg)
    assert n == 0
    assert reg.snapshot().count == 0


@pytest.mark.asyncio
async def test_value_round_trip(tmp_path: Path) -> None:
    """Append a value entry, reload into a fresh registry, watchdog
    should now consider that value already-seen."""
    path = tmp_path / "novel_observations.jsonl"
    store = PersistentNovelStore(path)
    reg = NovelObservationRegistry()
    # Record a novel value — fires True the first time.
    assert reg.record_value(siid=2, piid=2, value=28, now_unix=1700000000) is True
    # Append it via the store directly (mirrors what the registry
    # would do once attach_store is wired in Task 5).
    await store.append_sync(
        category="value", ts=1700000000, siid=2, piid=2, value=28,
    )

    # Fresh registry, fresh watchdog. Reload from disk.
    reg2 = NovelObservationRegistry()
    n = await store.load(reg2)
    assert n == 1
    # The watchdog now knows value 28 — re-recording returns False.
    assert reg2.record_value(siid=2, piid=2, value=28, now_unix=1700000100) is False
    # And a different value for the same slot still returns True.
    assert reg2.record_value(siid=2, piid=2, value=70, now_unix=1700000100) is True


@pytest.mark.asyncio
async def test_load_count_matches_file_lines(tmp_path: Path) -> None:
    """Load returns the count of replayed entries."""
    path = tmp_path / "novel_observations.jsonl"
    path.write_text(
        '{"ts": 1, "category": "property", "siid": 6, "piid": 1}\n'
        '{"ts": 2, "category": "value", "siid": 6, "piid": 1, "value": 200}\n'
        '{"ts": 3, "category": "value", "siid": 6, "piid": 1, "value": 300}\n'
    )
    reg = NovelObservationRegistry()
    n = await PersistentNovelStore(path).load(reg)
    assert n == 3
