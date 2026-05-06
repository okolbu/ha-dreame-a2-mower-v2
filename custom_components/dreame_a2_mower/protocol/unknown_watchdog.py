"""Dedupe novelty detector for unknown MQTT fields.

Background
----------
The g2408 emits telemetry at 5 s intervals during mowing. If an unmapped
`(siid, piid)` pair or an unfamiliar `method` were logged on every arrival,
the log would be swamped within minutes. This helper records the first
observation of each distinct key and reports novelty only on that first
call — any subsequent observation returns ``False`` so the caller can
skip logging.

The watchdog holds no state beyond per-process in-memory sets; a HA
restart resets it, which is exactly what we want — a restart may bring a
new integration version with different mappings, so re-flagging is
useful.

Thread-safety: the integration's MQTT callback is invoked on the paho
network thread, so every mutation happens on one thread. No locking.
"""

from __future__ import annotations

from typing import Any, Iterable


# Cap per-property value-history at this many distinct values. Bounds
# log/memory growth for properties that emit a wide range (e.g. s5p107
# was observed firing 10 distinct values; capping at 32 lets us catch
# a few times that without unbounded growth on truly random fields).
MAX_VALUES_PER_PROP = 32


class UnknownFieldWatchdog:
    """Track first-observations of unexpected MQTT fields.

    Each ``saw_*`` method returns ``True`` the first time its argument
    tuple is observed and ``False`` thereafter — callers use the bool to
    gate an ``_LOGGER.info(...)`` call so novelty is reported at most
    once per key.
    """

    def __init__(self) -> None:
        self._seen_properties: set[tuple[int, int]] = set()
        self._seen_methods: set[str] = set()
        self._seen_event_piids: dict[tuple[int, int], set[int]] = {}
        # Per-property value catalog. `_seen_values[(siid, piid)]` holds
        # the hashable representations of every distinct value seen for
        # that property, capped at MAX_VALUES_PER_PROP. Used by
        # `saw_value` to drive [PROTOCOL_VALUE_NOVEL] logging — extends
        # the existing "first time we see this property" novelty hook
        # to also catch "first time we see this VALUE for this
        # property". Critical for partially-known properties whose
        # semantics we're trying to derive from value patterns
        # (s5p107's dynamic enum, s2p2 state codes, etc.).
        self._seen_values: dict[tuple[int, int], set[Any]] = {}

    def saw_property(self, siid: int, piid: int) -> bool:
        key = (int(siid), int(piid))
        if key in self._seen_properties:
            return False
        self._seen_properties.add(key)
        return True

    def saw_method(self, method: str) -> bool:
        key = method if method is not None else ""
        if key in self._seen_methods:
            return False
        self._seen_methods.add(key)
        return True

    def saw_value(self, siid: int, piid: int, value: Any) -> bool:
        """Return True the first time this (siid, piid, value) is observed.

        Caps each property at `MAX_VALUES_PER_PROP` distinct values so a
        property that emits truly random data can't bloat memory or log
        volume unboundedly. Once the cap is hit the method returns
        False for any further values (the caller can take the cap as
        a signal that this slot is high-entropy and probably needs a
        different analysis strategy).

        Lists / dicts get hashed by their `repr` since they're
        themselves unhashable. Other unhashable types fall through to
        repr too. This is fine for log keying — collisions would
        require two distinct values with identical repr, which is a
        Python-level edge case.
        """
        key = (int(siid), int(piid))
        seen = self._seen_values.setdefault(key, set())
        if len(seen) >= MAX_VALUES_PER_PROP:
            return False
        try:
            hashable = value if isinstance(value, (int, float, str, bool, type(None))) else repr(value)
        except Exception:
            hashable = repr(value) if value is not None else None
        if hashable in seen:
            return False
        seen.add(hashable)
        return True

    def saw_event(self, siid: int, eiid: int, piids: Iterable[int]) -> bool:
        """Return True if any piid in ``piids`` is new for this (siid, eiid).

        The first call for any (siid, eiid) marks every supplied piid as
        seen and returns True. Later calls only return True when they
        introduce a piid not previously recorded for that (siid, eiid).
        """
        key = (int(siid), int(eiid))
        piid_set = {int(p) for p in piids}
        known = self._seen_event_piids.get(key)
        if known is None:
            self._seen_event_piids[key] = piid_set
            return True
        new_piids = piid_set - known
        if not new_piids:
            return False
        known.update(new_piids)
        return True

    def saw_catalog_miss(
        self,
        siid: int,
        piid: int,
        value: Any,
        catalog: dict[Any, str],
    ) -> bool:
        """Return True the first time an out-of-catalog value is observed.

        For properties whose inventory row carries a `value_catalog`,
        observed values that aren't in the catalog are interesting:
        either the catalog is incomplete or the firmware emitted a
        novel value. Either way the runtime should surface it once.

        In-catalog values return False (not a miss). Out-of-catalog
        values return True the first time and False for subsequent
        observations of the same value (dedupe). Cap shared with
        saw_value (MAX_VALUES_PER_PROP) so high-entropy fields don't
        bloat memory.
        """
        if value in catalog:
            return False
        # Reuse saw_value's storage for the dedupe — same (siid, piid, value)
        # uniqueness, same MAX_VALUES_PER_PROP cap.
        return self.saw_value(siid, piid, value)
