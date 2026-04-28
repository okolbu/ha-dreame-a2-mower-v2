"""Per-field freshness tracker.

The coordinator calls ``record(old_state, new_state, now)`` on every
state mutation. The tracker compares the two dataclass instances field
by field and stamps any field whose value changed with ``now``. Used by
``sensor.dreame_a2_mower_data_freshness`` (F6.7.1) to surface staleness
for the user.

NO ``homeassistant.*`` imports — layer-2.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any


class FreshnessTracker:
    def __init__(self) -> None:
        self._last_updated: dict[str, int] = {}

    def record(self, old: Any, new: Any, now_unix: int) -> None:
        """Stamp every field whose value changed between ``old`` and ``new``."""
        if old is None or new is None:
            return
        for f in fields(new):
            old_val = getattr(old, f.name, None)
            new_val = getattr(new, f.name)
            if old_val != new_val:
                self._last_updated[f.name] = int(now_unix)

    def last_updated(self, field_name: str) -> int | None:
        return self._last_updated.get(field_name)

    def age_seconds(self, field_name: str, now_unix: int) -> int | None:
        ts = self._last_updated.get(field_name)
        if ts is None:
            return None
        return int(now_unix) - int(ts)

    def snapshot(self) -> dict[str, int]:
        return dict(self._last_updated)
