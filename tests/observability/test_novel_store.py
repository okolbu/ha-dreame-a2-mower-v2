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
