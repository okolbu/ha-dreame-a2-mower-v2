"""Novel-observation registry — timestamped wrapper over UnknownFieldWatchdog.

The watchdog at ``protocol/unknown_watchdog.py`` answers "have I seen
this key before?". The registry adds a wall-clock timestamp and a
category label (``property`` / ``value`` / ``event`` / ``key``) so HA
sensors and diagnostics can show *what* surprised the integration *when*.

Optionally backed by a ``PersistentNovelStore`` (attach via
``attach_store``) so first-observations survive HA restarts. Without
a store attached, behaves as a process-scoped registry — the
backwards-compatible default for tests and any code path that
constructs a registry without persistence.

NO ``homeassistant.*`` imports.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..protocol.unknown_watchdog import UnknownFieldWatchdog

if TYPE_CHECKING:
    from .novel_store import PersistentNovelStore


@dataclass(frozen=True)
class NovelObservation:
    """One novel-token sighting."""

    category: str           # "property" | "value" | "event" | "key"
    detail: str             # human-readable token
    first_seen_unix: int    # wall-clock time of the first sighting


@dataclass(frozen=True)
class RegistrySnapshot:
    """Read-only view of the registry suitable for sensor attributes."""

    count: int
    observations: list[NovelObservation]


class NovelObservationRegistry:
    """Records first-arrival of unknown protocol shapes.

    Methods return ``True`` the first time a token is seen, ``False`` on
    every subsequent observation — matches the watchdog's "novelty bool"
    return convention so callers can gate ``LOGGER.warning`` calls cleanly.

    Caps total in-memory observations at ``MAX_OBSERVATIONS`` to bound
    the sensor attribute list and the diagnostics dump size. The
    persistent store (when attached) is bounded by the watchdog's
    per-slot caps.
    """

    MAX_OBSERVATIONS = 200

    def __init__(self) -> None:
        self._watchdog = UnknownFieldWatchdog()
        self._observations: list[NovelObservation] = []
        self._store: "PersistentNovelStore | None" = None

    def attach_store(self, store: "PersistentNovelStore") -> None:
        """Wire a persistent store. After this call, every record_*
        that returns True will fire-and-forget an append to disk.

        Call this AFTER any one-time ``store.load(self)`` so the
        load-time replay doesn't echo back into the file.
        """
        self._store = store

    def record_property(self, siid: int, piid: int, now_unix: int) -> bool:
        if not self._watchdog.saw_property(siid, piid):
            return False
        self._append("property", f"siid={siid} piid={piid}", now_unix)
        if self._store is not None:
            asyncio.create_task(
                self._store.append_sync(
                    category="property", ts=now_unix, siid=siid, piid=piid,
                )
            )
        return True

    def record_value(
        self, siid: int, piid: int, value: Any, now_unix: int
    ) -> bool:
        if not self._watchdog.saw_value(siid, piid, value):
            return False
        self._append("value", f"siid={siid} piid={piid} value={value!r}", now_unix)
        if self._store is not None:
            asyncio.create_task(
                self._store.append_sync(
                    category="value", ts=now_unix,
                    siid=siid, piid=piid, value=value,
                )
            )
        return True

    def record_event(
        self, siid: int, eiid: int, piids: list[int], now_unix: int
    ) -> bool:
        if not self._watchdog.saw_event(siid, eiid, piids):
            return False
        self._append("event", f"siid={siid} eiid={eiid} piids={sorted(piids)!r}", now_unix)
        if self._store is not None:
            asyncio.create_task(
                self._store.append_sync(
                    category="event", ts=now_unix,
                    siid=siid, eiid=eiid, piids=list(piids),
                )
            )
        return True

    def record_key(self, namespace: str, key: str, now_unix: int) -> bool:
        """Track a JSON-blob key that's not in the expected schema.

        The watchdog's method-set is reused as the novelty store keyed
        on ``f"{namespace}.{key}"``.
        """
        token = f"{namespace}.{key}"
        if not self._watchdog.saw_method(token):
            return False
        self._append("key", token, now_unix)
        if self._store is not None:
            asyncio.create_task(
                self._store.append_sync(
                    category="key", ts=now_unix, namespace=namespace, key=key,
                )
            )
        return True

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(
            count=len(self._observations),
            observations=list(self._observations),
        )

    # ----- internal -----

    def _append(self, category: str, detail: str, now_unix: int) -> None:
        if len(self._observations) >= self.MAX_OBSERVATIONS:
            return
        self._observations.append(
            NovelObservation(
                category=category,
                detail=detail,
                first_seen_unix=int(now_unix),
            )
        )
