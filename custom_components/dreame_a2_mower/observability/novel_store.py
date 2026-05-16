"""Append-only JSONL persistence for novel observations.

Owns the on-disk file at ``/config/dreame_a2_mower/novel_observations.jsonl``.
Loaded once at integration setup to seed the registry's watchdog with
"things this mower has ever seen", then attached so subsequent novel
observations append exactly one line per first-seen token.

NO ``homeassistant.*`` imports at module top — the hass-aware
``append`` method is layered on top of ``append_sync`` so the core
serialization logic stays testable without an HA event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import NovelObservationRegistry

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
        replayed = 0
        try:
            content = self._path.read_text(encoding="utf-8")
        except OSError:
            LOGGER.exception(
                "novel_store: failed to read %s; treating as empty",
                self._path,
            )
            return 0
        for line_no, raw in enumerate(content.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                LOGGER.warning(
                    "novel_store: skipping malformed line %d in %s: %s",
                    line_no, self._path.name, exc,
                )
                continue
            if self._replay_into(registry, obj):
                replayed += 1
        return replayed

    def _replay_into(
        self, registry: "NovelObservationRegistry", obj: dict[str, Any]
    ) -> bool:
        """Dispatch one parsed line into the registry's record_* methods.

        Returns True if the entry was a recognised category and was
        replayed. Returns False (with a warning) for unrecognised
        categories — preserves forward-compatibility if a future
        version writes new categories the current code doesn't know.
        """
        cat = obj.get("category")
        ts = int(obj.get("ts", 0))
        try:
            if cat == "property":
                registry.record_property(int(obj["siid"]), int(obj["piid"]), ts)
            elif cat == "value":
                registry.record_value(
                    int(obj["siid"]), int(obj["piid"]), obj["value"], ts,
                )
            elif cat == "event":
                registry.record_event(
                    int(obj["siid"]),
                    int(obj["eiid"]),
                    [int(p) for p in obj.get("piids", [])],
                    ts,
                )
            elif cat == "key":
                registry.record_key(
                    str(obj["namespace"]), str(obj["key"]), ts,
                )
            else:
                LOGGER.warning(
                    "novel_store: unknown category %r in line %r",
                    cat, obj,
                )
                return False
        except (KeyError, TypeError, ValueError) as exc:
            LOGGER.warning(
                "novel_store: malformed %r entry %r: %s", cat, obj, exc,
            )
            return False
        return True

    async def append_sync(
        self,
        *,
        category: str,
        ts: int,
        siid: int | None = None,
        piid: int | None = None,
        value: Any = None,
        eiid: int | None = None,
        piids: list[int] | None = None,
        namespace: str | None = None,
        key: str | None = None,
    ) -> None:
        """Append one line to the file. Non-HA-aware variant used by
        tests and by the hass-aware ``append`` wrapper.

        Builds the JSON line from explicit kwargs (one per category-
        specific field) so callers can't accidentally serialise random
        attributes. Acquires the lock so concurrent appends don't
        produce interleaved partial lines.
        """
        obj: dict[str, Any] = {"ts": int(ts), "category": category}
        if category == "property":
            obj["siid"] = int(siid)  # type: ignore[arg-type]
            obj["piid"] = int(piid)  # type: ignore[arg-type]
        elif category == "value":
            obj["siid"] = int(siid)  # type: ignore[arg-type]
            obj["piid"] = int(piid)  # type: ignore[arg-type]
            obj["value"] = value
        elif category == "event":
            obj["siid"] = int(siid)  # type: ignore[arg-type]
            obj["eiid"] = int(eiid)  # type: ignore[arg-type]
            obj["piids"] = list(piids or [])
        elif category == "key":
            obj["namespace"] = str(namespace)
            obj["key"] = str(key)
        else:
            LOGGER.warning(
                "novel_store: refusing to append unknown category %r", category,
            )
            return
        line = json.dumps(obj, separators=(",", ":"), default=repr) + "\n"
        async with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                LOGGER.exception(
                    "novel_store: failed to append to %s; observation lost",
                    self._path,
                )
