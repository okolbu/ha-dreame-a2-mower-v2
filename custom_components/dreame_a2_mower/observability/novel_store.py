"""Append-only JSONL persistence for novel observations.

Owns the on-disk file at ``/config/dreame_a2_mower/novel_observations.jsonl``.
Loaded once at integration setup to seed the registry's watchdog with
"things this mower has ever seen", then attached so subsequent novel
observations append exactly one line per first-seen token.

NO ``homeassistant.*`` imports — see end of file for the executor-
job wrapper used by the integration.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import NovelObservation, NovelObservationRegistry

LOGGER = logging.getLogger(__name__)


class PersistentNovelStore:
    """JSONL-backed novelty store.

    File format: one JSON object per line, fields per category:
      property: {"ts", "category": "property", "siid", "piid"}
      value:    {"ts", "category": "value", "siid", "piid", "value"}
      event:    {"ts", "category": "event", "siid", "eiid", "piids"}
      key:      {"ts", "category": "key", "namespace", "key"}
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def load(self, registry: "NovelObservationRegistry") -> int:
        """Walk the file, replay each line into ``registry`` via record_*.

        Returns the count of entries successfully replayed. Tolerates
        a missing file (returns 0). Tolerates malformed lines (logs
        a warning, skips the line, continues).
        """
        if not self._path.exists():
            return 0
        return 0  # filled in by Task 2
