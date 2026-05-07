"""Conftest for event tests.

Event tests import event.py which requires homeassistant.components.event.EventEntity.
We inject minimal stubs so the event module can be imported without a full HA environment.
"""
from __future__ import annotations

import sys
import types


def _stub_event_entity() -> None:
    """Insert stub for homeassistant.components.event.EventEntity."""
    if "homeassistant.components.event" in sys.modules:
        return

    ha_ce = types.ModuleType("homeassistant.components.event")

    class EventEntity:  # noqa: D101
        """Minimal stub for EventEntity base class."""

        def __init__(self):
            self.entity_id = "event.test"

        def _trigger_event(self, event_type: str, event_data: dict) -> None:
            """Stub for firing an event."""
            pass

        def async_write_ha_state(self) -> None:
            """Stub for writing state."""
            pass

    ha_ce.EventEntity = EventEntity

    sys.modules["homeassistant.components.event"] = ha_ce


_stub_event_entity()
