"""Novel-observation registry — timestamped wrapper over UnknownFieldWatchdog.

The watchdog at ``protocol/unknown_watchdog.py`` answers "have I seen
this key before?". The registry adds a wall-clock timestamp and a
category label (``property`` / ``value`` / ``event`` / ``key``) so HA
sensors and diagnostics can show *what* surprised the integration *when*.

Process-scoped: a HA restart drops everything. Matches the watchdog's
semantics.

NO ``homeassistant.*`` imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol.unknown_watchdog import UnknownFieldWatchdog


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

    Caps total observations at ``MAX_OBSERVATIONS`` to bound the sensor
    attribute list and the diagnostics dump size on devices with a flood
    of unknown tokens. Once capped, further novel tokens are dropped at
    record-time (the watchdog still tracks them, but they don't reach
    the sensor).
    """

    MAX_OBSERVATIONS = 200

    def __init__(self) -> None:
        self._watchdog = UnknownFieldWatchdog()
        self._observations: list[NovelObservation] = []

    def record_property(self, siid: int, piid: int, now_unix: int) -> bool:
        if not self._watchdog.saw_property(siid, piid):
            return False
        self._append("property", f"siid={siid} piid={piid}", now_unix)
        return True

    def record_value(
        self, siid: int, piid: int, value: Any, now_unix: int
    ) -> bool:
        if not self._watchdog.saw_value(siid, piid, value):
            return False
        self._append("value", f"siid={siid} piid={piid} value={value!r}", now_unix)
        return True

    def record_event(
        self, siid: int, eiid: int, piids: list[int], now_unix: int
    ) -> bool:
        if not self._watchdog.saw_event(siid, eiid, piids):
            return False
        self._append("event", f"siid={siid} eiid={eiid} piids={sorted(piids)!r}", now_unix)
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
